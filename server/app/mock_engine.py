"""本地规则引擎（无 LLM Key 时的降级模式，也是评测的"基线"）。

存在意义有三个，都不是凑数：
1. Demo 离线可跑 —— 面试官打开链接时不能因为没配 Key 就白屏；
2. 降级兜底 —— PRD 风险表 R1 要求"LLM 不可用时不白屏"；
3. 对照基线 —— 有了规则版，才能说清"上大模型到底提升了几个点"。

它不是"伪装成 AI"，输出里会明确标注 provider=mock。
"""

import re

from . import phone as phone_mod

INDUSTRY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("医疗", ("口腔", "牙科", "诊所", "医院", "医疗", "体检", "门诊")),
    ("教育", ("培训", "少儿编程", "招生", "课程", "教育", "幼儿园", "学校", "早教")),
    ("餐饮", ("火锅", "餐厅", "餐饮", "奶茶", "咖啡", "烧烤", "面馆", "快餐", "小吃", "食品")),
    ("美业", ("美容", "美甲", "美发", "医美", "皮肤管理", "spa", "养生")),
    ("房产", ("楼盘", "房产", "地产", "公寓", "售楼", "物业")),
    ("汽车", ("汽车", "4s", "车行", "二手车", "4s店")),
    ("金融", ("贷款", "金融", "保险", "理财", "信贷")),
    ("零售", ("便利店", "超市", "家具", "卖场", "服装店", "零售", "商城")),
    ("本地生活", ("本地生活", "团购", "到店", "美团", "本地推广")),
    ("制造", ("工厂", "制造", "加工", "厂房", "生产")),
    ("互联网", ("互联网公司", "软件公司", "app开发", "saas", "平台开发")),
]

AD_PATTERNS = ("代运营", "代投", "推广服务", "营销服务", "我司", "已服务", "价格优惠", "欢迎咨询")
PEER_PATTERNS = ("我也是做这行", "同行", "同行业", "做这行的", "同行交流", "报价体系")
NON_MARKETING = ("地址", "地铁", "怎么走", "投诉", "售后", "找客服", "客服电话")

LOW_SIGNALS = ("再看看", "先看看", "随便看看", "随便问", "不着急", "暂时没有", "有需要再联系",
               "帮朋友", "帮他问", "帮我问", "帮别人问", "先了解一下")
PURCHASE_SIGNALS = ("报价", "报个价", "方案", "上门", "到店", "详聊", "可以定", "定了",
                    "这周", "本周", "面谈", "见面", "下单", "签约", "签约")

SCENE_HINTS = ("店", "公司", "厂", "机构", "诊所", "门店", "连锁", "总部", "卖场", "商行")


_CLAUSE_RE = re.compile(r"[。！？!?\n，,；;]+")


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk / len(text)


def detect_invalid(text: str) -> tuple[bool, str | None]:
    """按 PRD 的短路顺序，先判无效。"""
    if len(text.strip()) > 8 and _cjk_ratio(text) < 0.2:
        return True, "乱码无意义"

    if any(k in text for k in ("招聘", "急招", "底薪", "提成", "简历")):
        return True, "招聘广告"

    if any(k in text for k in AD_PATTERNS) and ("我们" in text or "我司" in text or "本公司" in text):
        return True, "广告推销"

    if any(k in text for k in PEER_PATTERNS):
        return True, "疑似同行"

    if any(k in text for k in NON_MARKETING):
        return True, "非营销咨询"

    return False, None


def detect_industry(text: str) -> str | None:
    best, best_hits = None, 0
    lowered = text.lower()
    for industry, keywords in INDUSTRY_RULES:
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits > best_hits:
            best, best_hits = industry, hits
    return best


def detect_budget(text: str) -> str | None:
    """按"分句"取预算，而不是用一条全局正则去扫。

    之前的写法会从 20 字开外开始吞，把"平台的推广，预算大概3万左右，方便的话加我"整段当预算，
    属于给业务添堵。分句取最贴近原文，也最短。
    """
    for phrase in ("预算还没定", "预算未定", "暂时没有预算", "没有预算", "预算充足", "预算不明"):
        if phrase in text:
            return phrase

    for clause in _CLAUSE_RE.split(text):
        clause = clause.strip()
        if "预算" in clause and (re.search(r"\d", clause) or "万" in clause or "元" in clause):
            return clause[:40]

    # 兜底：没写"预算"两个字，但出现了金额
    m = re.search(r"[^。！？\n]{0,10}?\d+(?:\.\d+)?\s*(?:万|元|块)", text)
    return m.group(0).strip()[:40] if m else None


ACTION_RE = re.compile(
    r"想|要|需要|打算|计划|准备|做|开|投|合作|咨询|了解|价格|价位|收费|方案|报价|"
    r"团购|推广|引流|获客|官网|小程序|上门|到店|店|公司|工厂|机构|聊|推|定|签"
)
BUDGET_ONLY_RE = re.compile(r"^预算")
MONEY_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:万|元|块)")
# 摘要里要抹掉的号码形态（含空格/横线分隔的写法）
PHONE_IN_TEXT_RE = re.compile(r"1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4}|[\d\-]{9,}")
# 纯联系方式句（"方便的话加我…详聊"）不算需求，抹掉号码后就是噪声
CONTACT_ONLY_RE = re.compile(r"加我|微信|vx|电话|手机号|联系我|私信|详聊")
# 注意顺序：长前缀在前，否则"我们"会被"我"抢先匹配，切出"们做…"这种残句
STRIP_PREFIX_RE = re.compile(
    r"^(我想问一下|我想问下|想问一下|想问下|我这边是|我们这边是|我们是|我是|"
    r"你好|您好|请问|我先|我就|我们|我)"
)


def build_demand(text: str, industry: str | None) -> str:
    clauses = [c.strip() for c in _CLAUSE_RE.split(text) if c.strip()]
    keep: list[str] = []
    for clause in clauses:
        if len(clause) < 4:
            continue
        stripped = STRIP_PREFIX_RE.sub("", clause).strip()
        if len(stripped) < 4:
            stripped = clause

        # 纯预算句不算需求（预算已单独成字段）；但带明确金额的必须留下，业务要看到数
        if BUDGET_ONLY_RE.match(stripped):
            if MONEY_RE.search(stripped):
                keep.append(stripped)
            continue

        if ACTION_RE.search(stripped):
            if CONTACT_ONLY_RE.search(stripped) and not re.search(r"想|要|做|开|投|合作|咨询|了解|推广|引流|获客|方案", stripped):
                continue          # "方便的话加我…详聊" 这类联系方式句，不是需求
            keep.append(stripped)
        if len("，".join(keep)) >= 50:
            break

    if not keep:
        keep = clauses[:1]

    # 按整句累加，超长就丢掉最后一句，绝不在句子中间切断（截断的摘要读起来是事故）
    result = ""
    for sentence in keep:
        candidate = f"{result}，{sentence}" if result else sentence
        if len(candidate) > 60:
            break
        result = candidate
    result = result or keep[0][:60]

    # 摘要里不能出现完整手机号：一是不该重复展示，二是列表宽度有限
    result = PHONE_IN_TEXT_RE.sub("", result)
    return re.sub(r"[，,]\s*(?=[，,])", "", result).strip("，, ")


def decide_intent(text: str, industry: str | None, budget: str | None, has_phone: bool) -> str:
    has_scene = bool(industry) or any(h in text for h in SCENE_HINTS)
    has_budget = bool(budget)
    signal = any(s in text for s in PURCHASE_SIGNALS)
    low = any(s in text for s in LOW_SIGNALS)

    if low and not (has_phone and has_budget):
        return "低"
    if has_phone and (has_scene or has_budget) and (signal or has_budget):
        return "高"
    if has_scene or has_budget:
        return "中"
    return "低"


def parse(text: str) -> dict:
    """返回与 P1 Prompt 完全一致的六字段结构。"""
    text = text.strip()
    invalid, invalid_risk = detect_invalid(text)

    phone, phone_raw = phone_mod.resolve_phone(text, None)
    risks: list[str] = []
    candidates = phone_mod.extract_candidates(text)
    if candidates and any(c["owner"] == "agent" for c in candidates):
        risks.append("含业务员/渠道号码，已排除")
    if phone_mod.has_chinese_numeral_phone(text):
        risks.append("号码为中文数字，需人工确认")

    if invalid:
        return {
            "phone": None,
            "customer_industry": None,
            "demand": build_demand(text, None),
            "budget_hint": None,
            "intent_level": "无效",
            "risk_note": invalid_risk,
        }

    industry = detect_industry(text)
    budget = detect_budget(text)
    intent = decide_intent(text, industry, budget, bool(phone))

    if not phone and any("业务员" in (c["context"] or "") for c in candidates):
        risks.append("仅出现业务员号码")
    if len(text) < 20:
        risks.append("内容过短")

    return {
        "phone": phone,
        "phone_raw": phone_raw,
        "customer_industry": industry,
        "demand": build_demand(text, industry),
        "budget_hint": budget,
        "intent_level": intent,
        "risk_note": "；".join(dict.fromkeys(risks)) or None,
    }
