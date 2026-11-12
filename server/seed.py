"""灌演示数据：跑一遍 30 条标注样本，并铺开时间/状态，让看板和大盘不是空的。

用法：
    cd server
    .venv/Scripts/python seed.py            # 已有数据则跳过
    .venv/Scripts/python seed.py --reset    # 清空重灌
"""

import argparse
import asyncio
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import db, services  # noqa: E402

CASES = Path(__file__).resolve().parent.parent / "docs" / "eval" / "cases.jsonl"


async def main(reset: bool = False) -> None:
    random.seed(42)
    db.init_db()

    with db.get_conn() as conn:
        if reset:
            conn.execute("DELETE FROM leads")
            conn.execute("DELETE FROM feedbacks")
            # AUTOINCREMENT 的序列不会随 DELETE 归零，不重置的话演示里第一条线索会是 #31
            conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('leads', 'feedbacks')")
            print("已清空旧数据")

        if conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"] > 0:
            print("库里已有数据，跳过。要重灌请加 --reset")
            return

        cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
        now = datetime.now(timezone.utc)
        created = 0

        for index, case in enumerate(cases):
            result = await services.parse_and_store(conn, case["text"])
            if result["status"] != "ok":
                print(f"  跳过 {case['id']}: {result['status']}")
                continue

            # 铺开最近 7 天，越近越多，让趋势图看起来像真实增长而不是一条平线
            days_ago = random.choices(range(7), weights=[1, 2, 2, 3, 4, 5, 6])[0]
            stamp = now - timedelta(days=days_ago, hours=random.randint(0, 9), minutes=random.randint(0, 59))
            conn.execute(
                "UPDATE leads SET created_at = ?, updated_at = ? WHERE id = ?",
                (stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), result["lead"]["id"]),
            )
            created += 1

        # 额外灌一条"解析失败"样本：用来演示失败兜底路径（原文保留 / 待补录 / 可重试）
        stamp = now - timedelta(hours=3)
        conn.execute(
            """
            INSERT INTO leads (raw_text, text_hash, phone, customer_industry, demand, intent_level,
                parse_status, parse_error, parse_ms, prompt_version, follow_status, human_verified,
                created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "（演示样本）在吗 多少钱",
                services.text_hash("demo-failed-lead"),
                None, None, "",
                "低", "failed", "模拟：模型返回内容不是合法 JSON（已重试 1 次）", 0,
                "v2", "pending", "unchecked",
                stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )

        # 让看板有"已跟进/已放弃"，并造两条复核记录，指标卡才不是零
        rows = conn.execute("SELECT id FROM leads ORDER BY id").fetchall()
        ids = [r["id"] for r in rows]
        for lead_id in ids[: max(1, len(ids) // 4)]:
            conn.execute("UPDATE leads SET follow_status = 'followed' WHERE id = ?", (lead_id,))
        for lead_id in ids[-4:-1]:      # 跳过最后一条（那是故意留的"解析失败"演示样本）
            conn.execute("UPDATE leads SET follow_status = 'invalid' WHERE id = ?", (lead_id,))

        for lead_id in ids[:6]:
            conn.execute("UPDATE leads SET human_verified = 'correct' WHERE id = ?", (lead_id,))
        if ids:
            conn.execute("UPDATE leads SET human_verified = 'wrong' WHERE id = ?", (ids[8],))
            conn.execute(
                "INSERT INTO feedbacks (lead_id, wrong_fields, correct_values, error_category, note, status, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    ids[8],
                    json.dumps(["intent_level"], ensure_ascii=False),
                    json.dumps({"intent_level": "中"}, ensure_ascii=False),
                    "BC-2",
                    "客户只说先看看，判成高偏乐观",
                    "open",
                    services.now_iso(),
                ),
            )

        total = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
        print(f"灌入 {created} 条线索，库中共 {total} 条")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.reset))
