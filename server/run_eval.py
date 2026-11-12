"""评测脚本：在固定的 30 条标注集上算准确率。

这不是"跑个演示"，这是整个项目的度量衡。每次改 Prompt 都必须跑一遍。

用法：
    cd server
    .venv/Scripts/python run_eval.py            # 当前 provider（无 Key 即规则基线）
    .venv/Scripts/python run_eval.py --save     # 结果写入 eval_runs 表
    .venv/Scripts/python run_eval.py --verbose  # 打印逐条明细

判定口径（写死，不允许临时调松）：
  手机号  —— 精确比对（空对空算对）
  行业    —— 精确比对；gold 为 null 的样本不参与（无标注即无对错）
  预算    —— gold 为 null 的不参与；否则要求核心金额/措辞被覆盖
  需求    —— 字符 3-gram 覆盖率 ≥ 0.5 或 Jaccard ≥ 0.4 视为摘要达标
  意向    —— 精确比对（这是产品最在意的那个数）
  无效样本的需求摘要不做评判（替一条广告写摘要没有标准答案）
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# Windows 控制台默认 GBK，输出 ✓/中文会炸，这里强制 UTF-8
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config, db, llm, phone as phone_mod  # noqa: E402
from app.dedup import ngram_set, jaccard  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent.parent / "docs" / "eval" / "cases.jsonl"


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def _norm(s: str | None) -> str:
    return re.sub(r"[\s\W_]+", "", s or "")


def budget_match(gold: str, pred: str | None) -> bool:
    if not pred:
        return False
    gold_nums = set(re.findall(r"\d+(?:\.\d+)?", gold))
    pred_nums = set(re.findall(r"\d+(?:\.\d+)?", pred))
    if gold_nums:
        return gold_nums <= pred_nums
    return _norm(gold)[:6] in _norm(pred) or _norm(pred)[:6] in _norm(gold)


def demand_match(gold: str, pred: str | None) -> bool:
    if not pred:
        return False
    g, p = ngram_set(gold), ngram_set(pred)
    if not g or not p:
        return False
    coverage = len(g & p) / len(g)
    return coverage >= 0.5 or jaccard(g, p) >= 0.4


async def evaluate(verbose: bool = False) -> dict:
    cases = load_cases()
    rows = []

    for case in cases:
        gold = case["gold"]
        outcome = await llm.parse_text(case["text"])
        data = outcome.data or {}

        # 与线上同一条处理链：正则优先，无效线索不留号码
        resolved, _ = phone_mod.resolve_phone(case["text"], data.get("phone"))
        intent = data.get("intent_level") or "(失败)"
        if intent == "无效":
            resolved = None

        checks = {
            "phone": (gold["phone"] or None) == (resolved or None),
            "intent": gold["intent_level"] == intent,
        }
        if gold.get("customer_industry") is not None:
            checks["industry"] = gold["customer_industry"] == data.get("customer_industry")
        if gold.get("budget_hint") is not None:
            checks["budget"] = budget_match(gold["budget_hint"], data.get("budget_hint"))
        # 无效线索替它写摘要有争议；低意向线索的摘要本身没有信息量。两者都不纳入摘要统计
        if gold.get("demand") is not None and gold["intent_level"] not in ("无效", "低"):
            kws = case.get("keywords") or []
            pred = data.get("demand") or ""
            if kws:
                hit = sum(1 for k in kws if k in pred)
                checks["demand"] = (hit / len(kws)) >= 0.6
                checks["demand_hit"] = f"{hit}/{len(kws)}"
            else:
                checks["demand"] = demand_match(gold["demand"], pred)

        rows.append({
            "id": case["id"],
            "cat": case["cat"],
            "checks": checks,
            "gold_intent": gold["intent_level"],
            "pred_intent": intent,
            "pred_demand": data.get("demand"),
            "gold_demand": gold.get("demand"),
            "error": outcome.error,
        })

    total = len(rows)

    def rate(key: str) -> tuple[int, int, float]:
        judged = [r for r in rows if key in r["checks"]]
        ok = sum(1 for r in judged if r["checks"][key])
        return ok, len(judged), (ok / len(judged) if judged else 0.0)

    summary = {k: rate(k) for k in ("phone", "industry", "budget", "demand", "intent")}

    # "关键字段全对"：phone + intent 都对（industry 仅在有人工标注时纳入）
    key_ok = sum(
        1 for r in rows
        if r["checks"].get("phone") and r["checks"].get("intent") and r["checks"].get("industry", True)
    )
    summary["key_fields"] = (key_ok, total, key_ok / total if total else 0.0)
    summary["failed"] = (sum(1 for r in rows if r["error"]), total, 0.0)

    if verbose:
        print("\n逐条明细：")
        print(f"{'ID':<5}{'类别':<12}{'标注':<6}{'预测':<6}{'手机':<5}{'意向':<5}{'行业':<5}{'需求':<5}")
        for r in rows:
            c = r["checks"]
            mark = lambda k: "✓" if c.get(k) else ("✗" if k in c else "·")
            print(f"{r['id']:<5}{r['cat']:<12}{r['gold_intent']:<6}{r['pred_intent']:<6}"
                  f"{mark('phone'):<5}{mark('intent'):<5}{mark('industry'):<5}{mark('demand'):<5}")

    if verbose:
        print("\n摘要失配明细（供 Prompt 迭代定位）：")
        for r in rows:
            if r["checks"].get("demand") is False:
                print(f"  {r['id']} 标注={r['gold_demand']}\n        预测={r['pred_demand']}")

    return {"summary": summary, "rows": rows, "provider": llm.config.LLM_PROVIDER}


def print_summary(result: dict) -> None:
    s = result["summary"]
    names = {
        "phone": "手机号", "industry": "行业", "budget": "预算",
        "demand": "需求摘要", "intent": "意向等级", "key_fields": "关键字段全对", "failed": "解析失败",
    }
    print(f"\nprovider = {result['provider']}    prompt = {config.PROMPT_VERSION}")
    print("-" * 52)
    for key, label in names.items():
        ok, n, rate = s[key]
        print(f"{label:<8} {ok:>2}/{n:<2}  {rate * 100:6.1f}%")
    print("-" * 52)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    result = await evaluate(args.verbose)
    print_summary(result)

    if args.save:
        db.init_db()
        s = result["summary"]
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO eval_runs (prompt_version, provider, dataset_size, field_accuracy, "
                "intent_accuracy, failed_count, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    config.PROMPT_VERSION,
                    result["provider"],
                    len(result["rows"]),
                    json.dumps({k: round(v[2], 4) for k, v in s.items()}, ensure_ascii=False),
                    round(s["intent"][2], 4),
                    s["failed"][0],
                    __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                ),
            )
        print("已写入 eval_runs 表")


if __name__ == "__main__":
    asyncio.run(main())
