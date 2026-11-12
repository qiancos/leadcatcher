"""线索去重。

PRD 6.3 的立场：**只提示，不合并，不自动删除。**
同一个手机号可能是老板、采购、前台三个人——自动合并会把一条真实商机吃掉。
所以这里只做"判定 + 标记"，把最终决定权留给人。
"""

import re

from . import config

_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return _PUNCT_RE.sub("", text)


def ngram_set(text: str | None, n: int = 3) -> set[str]:
    s = normalize_text(text)
    if len(s) < n:
        return {s} if s else set()
    return {s[i: i + n] for i in range(len(s) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def similarity(text_a: str | None, text_b: str | None) -> float:
    return jaccard(ngram_set(text_a), ngram_set(text_b))


def find_strong_duplicate(conn, phone: str | None) -> int | None:
    """强重复：归一化手机号完全相同（不限时间窗口）。返回最早一条的 id。"""
    if not phone:
        return None
    row = conn.execute(
        "SELECT id FROM leads WHERE phone = ? AND deleted_at IS NULL ORDER BY id ASC LIMIT 1",
        (phone,),
    ).fetchone()
    return row["id"] if row else None


def find_weak_duplicate(conn, demand: str | None, exclude_id: int | None = None) -> dict | None:
    """疑似重复：摘要 3-gram Jaccard ≥ 阈值，且落在观察窗口内。

    只用作"提示"，不写入 is_duplicate —— PRD 里明确要求这类不占标记。
    """
    if not demand:
        return None

    rows = conn.execute(
        f"""
        SELECT id, demand, phone, created_at FROM leads
        WHERE deleted_at IS NULL
          AND created_at >= datetime('now', '-{config.DEDUP_WINDOW_DAYS} days')
        ORDER BY id DESC LIMIT 200
        """
    ).fetchall()

    best = None
    for row in rows:
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        score = similarity(demand, row["demand"])
        if score >= config.DEDUP_THRESHOLD and (best is None or score > best["score"]):
            best = {"id": row["id"], "score": round(score, 3), "demand": row["demand"]}
    return best
