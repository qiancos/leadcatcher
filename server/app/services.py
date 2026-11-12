"""业务编排层：解析 → 校验 → 去重 → 落库，以及看板查询和统计口径。

所有"口径"都在这里，不在前端算 —— 前端只负责显示，
否则改一次统计规则要改两个仓库。
"""

import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone

from . import config, dedup, llm, phone as phone_mod

CN_TZ = timezone(timedelta(hours=8))


class LeadError(ValueError):
    """可预期的业务错误，API 层转成 4xx。"""

    def __init__(self, message: str, code: str = "BAD_REQUEST"):
        super().__init__(message)
        self.code = code


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _row_to_lead(row) -> dict:
    lead = dict(row)
    lead["phone_masked"] = phone_mod.mask(lead.get("phone"))
    lead["is_duplicate"] = bool(lead.get("is_duplicate"))
    return lead


# ---------------------------------------------------------------- 录入与解析

async def parse_and_store(conn, text: str, force: bool = False) -> dict:
    text = (text or "").strip()
    if not text:
        raise LeadError("请粘贴对话内容", "EMPTY_TEXT")
    if len(text) > config.MAX_TEXT_LEN:
        raise LeadError(
            f"内容 {len(text)} 字，超过 {config.MAX_TEXT_LEN} 字上限，请截取关键片段", "TOO_LONG"
        )

    h = text_hash(text)
    existed = conn.execute(
        "SELECT * FROM leads WHERE text_hash = ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
        (h,),
    ).fetchone()
    if existed and not force:
        return {
            "status": "duplicate_text",
            "message": "该内容已录入过，确认仍要录入吗？",
            "existing": _row_to_lead(existed),
        }

    outcome = await llm.parse_text(text)
    data = outcome.data or {}

    intent = data.get("intent_level") or "低"
    parse_status = "failed" if outcome.error else "success"

    # 第二道关：以正则为准，不信模型给的号码（PRD FR-2.4）
    resolved_phone, phone_raw = phone_mod.resolve_phone(text, data.get("phone"))
    if intent == "无效":
        resolved_phone = None          # 广告里的号码不是商机，保留原文备查即可

    strong_dup = dedup.find_strong_duplicate(conn, resolved_phone)
    weak_dup = None if strong_dup else dedup.find_weak_duplicate(conn, data.get("demand"))

    now = now_iso()
    cur = conn.execute(
        """
        INSERT INTO leads (
            raw_text, text_hash, phone, phone_raw, customer_industry, demand,
            budget_hint, intent_level, risk_note, parse_status, parse_error, parse_ms,
            prompt_version, is_duplicate, duplicate_of, follow_status, human_verified,
            created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            text, h, resolved_phone, phone_raw,
            data.get("customer_industry"), data.get("demand"),
            data.get("budget_hint"), intent, data.get("risk_note"),
            parse_status, outcome.error, outcome.elapsed_ms,
            config.PROMPT_VERSION,
            1 if strong_dup else 0, strong_dup,
            "pending", "unchecked", now, now,
        ),
    )
    lead_id = cur.lastrowid
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()

    return {
        "status": "ok",
        "lead": _row_to_lead(row),
        "duplicate": {
            "is_duplicate": bool(strong_dup),
            "duplicate_of": strong_dup,
            "reason": "phone" if strong_dup else None,
            "weak": weak_dup,
        },
        "meta": {
            "provider": outcome.provider,
            "elapsed_ms": outcome.elapsed_ms,
            "prompt_version": config.PROMPT_VERSION,
            "parse_error": outcome.error,
        },
    }


async def retry_parse(conn, lead_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM leads WHERE id = ? AND deleted_at IS NULL", (lead_id,)
    ).fetchone()
    if not row:
        raise LeadError("线索不存在", "NOT_FOUND")

    outcome = await llm.parse_text(row["raw_text"])
    data = outcome.data or {}
    resolved_phone, phone_raw = phone_mod.resolve_phone(row["raw_text"], data.get("phone"))

    conn.execute(
        """
        UPDATE leads SET customer_industry=?, demand=?, budget_hint=?, intent_level=?,
               risk_note=?, phone=?, phone_raw=?, parse_status=?, parse_error=?, parse_ms=?,
               prompt_version=?, updated_at=?
        WHERE id=?
        """,
        (
            data.get("customer_industry"), data.get("demand"), data.get("budget_hint"),
            data.get("intent_level") or row["intent_level"], data.get("risk_note"),
            resolved_phone, phone_raw,
            "failed" if outcome.error else "success", outcome.error, outcome.elapsed_ms,
            config.PROMPT_VERSION, now_iso(), lead_id,
        ),
    )
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return {"status": "ok", "lead": _row_to_lead(row)}


# ---------------------------------------------------------------- 看板查询

def list_leads(
    conn,
    intents: list[str] | None = None,
    follow_status: list[str] | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    only_dup: bool = False,
    only_failed: bool = False,
    page: int = 1,
    size: int = 20,
) -> dict:
    where = ["deleted_at IS NULL"]
    params: list = []

    if intents:
        where.append(f"intent_level IN ({','.join('?' * len(intents))})")
        params.extend(intents)
    if follow_status:
        where.append(f"follow_status IN ({','.join('?' * len(follow_status))})")
        params.extend(follow_status)
    if q:
        like = f"%{q.strip()}%"
        where.append(
            "(phone LIKE ? OR phone_raw LIKE ? OR demand LIKE ? "
            "OR customer_industry LIKE ? OR raw_text LIKE ?)"
        )
        params.extend([like] * 5)
    if date_from:
        where.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("created_at <= ?")
        params.append(date_to)
    if only_dup:
        where.append("is_duplicate = 1")
    if only_failed:
        where.append("parse_status = 'failed'")

    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) c FROM leads WHERE {where_sql}", params).fetchone()["c"]

    size = max(1, min(size, 100))
    offset = (max(1, page) - 1) * size

    rows = conn.execute(
        f"""
        SELECT * FROM leads WHERE {where_sql}
        ORDER BY
          CASE parse_status WHEN 'failed' THEN 0 ELSE 1 END,
          CASE follow_status WHEN 'pending' THEN 0 ELSE 1 END,
          CASE intent_level WHEN '高' THEN 0 WHEN '中' THEN 1 WHEN '低' THEN 2 ELSE 3 END,
          created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, size, offset],
    ).fetchall()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [_row_to_lead(r) for r in rows],
    }


def get_lead(conn, lead_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM leads WHERE id = ? AND deleted_at IS NULL", (lead_id,)
    ).fetchone()
    if not row:
        raise LeadError("线索不存在", "NOT_FOUND")
    lead = _row_to_lead(row)
    lead["feedbacks"] = [
        {**dict(r), "wrong_fields": json.loads(r["wrong_fields"]),
         "correct_values": json.loads(r["correct_values"])}
        for r in conn.execute(
            "SELECT * FROM feedbacks WHERE lead_id = ? ORDER BY id DESC", (lead_id,)
        ).fetchall()
    ]
    return lead


EDITABLE = {
    "phone", "customer_industry", "demand", "budget_hint",
    "intent_level", "risk_note", "follow_status", "is_duplicate",
}


def update_lead(conn, lead_id: int, payload: dict) -> dict:
    row = conn.execute(
        "SELECT * FROM leads WHERE id = ? AND deleted_at IS NULL", (lead_id,)
    ).fetchone()
    if not row:
        raise LeadError("线索不存在", "NOT_FOUND")

    sets, params = [], []
    for key, value in payload.items():
        if key not in EDITABLE:
            continue
        if key == "intent_level" and value not in config.INTENT_LEVELS:
            raise LeadError(f"意向等级非法：{value}", "BAD_ENUM")
        if key == "follow_status" and value not in config.FOLLOW_STATUS:
            raise LeadError(f"跟进状态非法：{value}", "BAD_ENUM")
        if key == "phone" and value:
            digits = "".join(ch for ch in str(value) if ch.isdigit())
            if len(digits) != 11:
                raise LeadError("手机号必须是 11 位数字", "BAD_PHONE")
            value = digits
        if key == "is_duplicate":
            value = 1 if value else 0
        sets.append(f"{key} = ?")
        params.append(value)

    if not sets:
        raise LeadError("没有可更新的字段", "NO_FIELD")

    sets.append("updated_at = ?")
    params.extend([now_iso(), lead_id])
    conn.execute(f"UPDATE leads SET {', '.join(sets)} WHERE id = ?", params)
    return get_lead(conn, lead_id)


def delete_lead(conn, lead_id: int) -> dict:
    now = now_iso()
    cur = conn.execute(
        "UPDATE leads SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
        (now, now, lead_id),
    )
    if cur.rowcount == 0:
        raise LeadError("线索不存在或已删除", "NOT_FOUND")
    # 被它标记为重复的那些线索，恢复成普通线索，避免悬空引用（PRD 6.3 验收）
    conn.execute(
        "UPDATE leads SET is_duplicate = 0, duplicate_of = NULL WHERE duplicate_of = ?", (lead_id,)
    )
    return {"status": "ok", "deleted_id": lead_id, "restorable": True}


def restore_lead(conn, lead_id: int) -> dict:
    cur = conn.execute(
        "UPDATE leads SET deleted_at = NULL, updated_at = ? WHERE id = ?", (now_iso(), lead_id)
    )
    if cur.rowcount == 0:
        raise LeadError("线索不存在", "NOT_FOUND")
    return get_lead(conn, lead_id)


def verify_lead(conn, lead_id: int, result: str) -> dict:
    if result not in ("correct", "wrong", "unchecked"):
        raise LeadError("result 只能是 correct / wrong / unchecked", "BAD_ENUM")
    conn.execute(
        "UPDATE leads SET human_verified = ?, updated_at = ? WHERE id = ?",
        (result, now_iso(), lead_id),
    )
    return {"status": "ok", "id": lead_id, "human_verified": result}


# ---------------------------------------------------------------- 反馈

def create_feedback(conn, payload: dict) -> dict:
    lead_id = payload.get("lead_id")
    if not lead_id:
        raise LeadError("缺少 lead_id", "BAD_REQUEST")
    row = conn.execute("SELECT id FROM leads WHERE id = ?", (lead_id,)).fetchone()
    if not row:
        raise LeadError("线索不存在", "NOT_FOUND")

    wrong_fields = payload.get("wrong_fields") or []
    correct_values = payload.get("correct_values") or {}
    if not isinstance(wrong_fields, list) or not wrong_fields:
        raise LeadError("至少勾选一个错误字段", "BAD_FEEDBACK")

    cur = conn.execute(
        """
        INSERT INTO feedbacks (lead_id, wrong_fields, correct_values, error_category, note, status, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            lead_id,
            json.dumps(wrong_fields, ensure_ascii=False),
            json.dumps(correct_values, ensure_ascii=False),
            payload.get("error_category") or "BC-6",
            payload.get("note"),
            "open",
            now_iso(),
        ),
    )
    conn.execute(
        "UPDATE leads SET human_verified = 'wrong', updated_at = ? WHERE id = ?",
        (now_iso(), lead_id),
    )
    return {"status": "ok", "id": cur.lastrowid}


def list_feedbacks(conn, status: str | None = None, limit: int = 100) -> list[dict]:
    sql = """
        SELECT f.*, l.raw_text, l.demand, l.intent_level AS ai_intent, l.phone AS ai_phone
        FROM feedbacks f JOIN leads l ON l.id = f.lead_id
    """
    params: list = []
    if status:
        sql += " WHERE f.status = ?"
        params.append(status)
    sql += " ORDER BY f.id DESC LIMIT ?"
    params.append(limit)

    out = []
    for r in conn.execute(sql, params).fetchall():
        item = dict(r)
        item["wrong_fields"] = json.loads(item["wrong_fields"])
        item["correct_values"] = json.loads(item["correct_values"])
        out.append(item)
    return out


def close_feedback(conn, feedback_id: int) -> dict:
    cur = conn.execute("UPDATE feedbacks SET status = 'closed' WHERE id = ?", (feedback_id,))
    if cur.rowcount == 0:
        raise LeadError("反馈不存在", "NOT_FOUND")
    return {"status": "ok", "id": feedback_id}


# ---------------------------------------------------------------- 统计大盘

def stats(conn, days: int = 7) -> dict:
    days = max(1, min(days, 90))
    today = datetime.now(CN_TZ).date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    window_start = f"{dates[0]}T00:00:00Z"

    def scalar(sql: str, params=()) -> int:
        row = conn.execute(sql, params).fetchone()
        return int(row[0] or 0) if row else 0

    total = scalar("SELECT COUNT(*) FROM leads WHERE deleted_at IS NULL")
    valid = scalar(
        "SELECT COUNT(*) FROM leads WHERE deleted_at IS NULL "
        "AND parse_status = 'success' AND intent_level != '无效'"
    )
    pending = scalar(
        "SELECT COUNT(*) FROM leads WHERE deleted_at IS NULL AND follow_status = 'pending'"
    )
    failed = scalar(
        "SELECT COUNT(*) FROM leads WHERE deleted_at IS NULL AND parse_status = 'failed'"
    )
    dup = scalar("SELECT COUNT(*) FROM leads WHERE deleted_at IS NULL AND is_duplicate = 1")

    intent_rows = conn.execute(
        "SELECT intent_level, COUNT(*) c FROM leads "
        "WHERE deleted_at IS NULL AND parse_status = 'success' GROUP BY intent_level"
    ).fetchall()
    intent_dist = {lvl: 0 for lvl in config.INTENT_LEVELS}
    for r in intent_rows:
        intent_dist[r["intent_level"]] = r["c"]

    def trend(sql: str) -> dict:
        return {
            r[0]: r[1]
            for r in conn.execute(sql, (window_start,)).fetchall()
        }

    added = trend(
        "SELECT date(created_at, '+8 hours') d, COUNT(*) c FROM leads "
        "WHERE deleted_at IS NULL AND created_at >= ? GROUP BY d"
    )
    failed_by_day = trend(
        "SELECT date(created_at, '+8 hours') d, COUNT(*) c FROM leads "
        "WHERE deleted_at IS NULL AND parse_status = 'failed' AND created_at >= ? GROUP BY d"
    )

    verified_correct = scalar(
        "SELECT COUNT(*) FROM leads WHERE deleted_at IS NULL AND human_verified = 'correct'"
    )
    verified_wrong = scalar(
        "SELECT COUNT(*) FROM leads WHERE deleted_at IS NULL AND human_verified = 'wrong'"
    )
    checked = verified_correct + verified_wrong

    return {
        "range_days": days,
        "cards": {
            "total": total,
            "valid": valid,
            "pending": pending,
            "failed": failed,
            "duplicate": dup,
        },
        "intent_dist": intent_dist,
        "valid_ratio": round(valid / total, 4) if total else 0,
        "daily": [{"date": d, "count": added.get(d, 0), "failed": failed_by_day.get(d, 0)}
                  for d in dates],
        "accuracy": {
            "checked": checked,
            "correct": verified_correct,
            "wrong": verified_wrong,
            "rate": round(verified_correct / checked, 4) if checked else None,
        },
        "feedback": {"open": scalar("SELECT COUNT(*) FROM feedbacks WHERE status = 'open'")},
    }


def export_csv(conn) -> str:
    rows = conn.execute(
        "SELECT id, created_at, phone, customer_industry, demand, budget_hint, "
        "intent_level, follow_status, risk_note, prompt_version FROM leads "
        "WHERE deleted_at IS NULL ORDER BY id DESC"
    ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["ID", "录入时间(UTC)", "手机号", "客户行业", "需求摘要", "预算",
         "意向等级", "跟进状态", "风险备注", "Prompt版本"]
    )
    for r in rows:
        writer.writerow(list(r))
    return buf.getvalue()
