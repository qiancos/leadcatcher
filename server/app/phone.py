"""手机号处理：LLM 抽取之后的"第二道关"。

PRD FR-2.4 的核心主张：**以正则为准，不以模型为准**。
模型负责理解"哪个号码是客户的"，正则负责保证"这串数字真的像个手机号"。
两道关卡各司其职，缺一不可。
"""

import re

FULLWIDTH = str.maketrans(
    "０１２３４５６７８９－　（）",
    "0123456789- ()",
)

# 允许 +86 前缀、空格、横线；主体必须是 1[3-9] 开头的 11 位
PHONE_RE = re.compile(r"(?:\+?86[\s\-]?)?(1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4})")

# 出现在号码前 25 个字符内 ⇒ 这个号码更可能是"对方业务员"的
AGENT_CUES = (
    "业务员", "销售", "客服", "渠道", "顾问", "经理",
    "座机", "热线", "公司电话", "我们公司", "门店电话",
)


def to_halfwidth(text: str) -> str:
    return text.translate(FULLWIDTH)


def _digits(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def is_valid_cn_mobile(phone: str | None) -> bool:
    return bool(phone) and bool(re.fullmatch(r"1[3-9]\d{9}", phone))


def extract_candidates(text: str) -> list[dict]:
    """返回原文里所有号码候选，并标注归属（customer / agent）。"""
    text = to_halfwidth(text)
    out = []
    for m in PHONE_RE.finditer(text):
        digits = _digits(m.group(1))
        if not is_valid_cn_mobile(digits):
            continue
        ctx = text[max(0, m.start() - 25): m.start()]
        owner = "agent" if any(cue in ctx for cue in AGENT_CUES) else "customer"
        out.append({
            "phone": digits,
            "raw": m.group(0).strip(),
            "owner": owner,
            "context": ctx.strip(),
        })
    return out


def resolve_phone(text: str, llm_phone: str | None) -> tuple[str | None, str | None]:
    """决定最终入库的号码，返回 (归一化号码, 原文片段)。

    决策顺序：
    1. 原文里没有任何候选 → 模型给什么都不信（防幻觉），返回 (None, None)
    2. 有候选 → 优先取"客户方"号码；全是"业务员"号码则返回 None
    3. 完全相同则采纳；不一致时以正则结果为准，原文片段留痕备查
    """
    candidates = extract_candidates(text)
    if not candidates:
        return None, None

    customers = [c for c in candidates if c["owner"] == "customer"]
    if not customers:
        return None, candidates[0]["raw"]

    chosen = customers[0]
    return chosen["phone"], chosen["raw"]


def mask(phone: str | None) -> str | None:
    """列表展示脱敏：138****1234（PRD 6.7 安全要求）。"""
    if not phone or len(phone) != 11:
        return phone
    return f"{phone[:3]}****{phone[7:]}"


def has_chinese_numeral_phone(text: str) -> bool:
    """识别"一三八零零一一二三三"这类中文数字号码，用于补 risk_note。"""
    pattern = r"[零一二三四五六七八九]{3,}[零一二三四五六七八九\s]{5,}"
    return re.search(pattern, text) is not None
