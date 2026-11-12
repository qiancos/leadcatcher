"""SQLite 数据层。裸 SQL，不引 ORM——Demo 阶段可读性 > 抽象。

三张核心表对应 PRD 第 8 章：leads / feedbacks / prompt_versions。
"""

import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text          TEXT    NOT NULL,
    text_hash         TEXT    NOT NULL,
    phone             TEXT,
    phone_raw         TEXT,
    customer_industry TEXT,
    demand            TEXT,
    budget_hint       TEXT,
    intent_level      TEXT    NOT NULL DEFAULT '低',
    risk_note         TEXT,
    parse_status      TEXT    NOT NULL DEFAULT 'success',
    parse_error       TEXT,
    parse_ms          INTEGER,
    prompt_version    TEXT    NOT NULL DEFAULT 'v2',
    is_duplicate      INTEGER NOT NULL DEFAULT 0,
    duplicate_of      INTEGER,
    follow_status     TEXT    NOT NULL DEFAULT 'pending',
    human_verified    TEXT    NOT NULL DEFAULT 'unchecked',
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    deleted_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_phone   ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_leads_intent  ON leads(intent_level, follow_status);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at);
CREATE INDEX IF NOT EXISTS idx_leads_hash    ON leads(text_hash);

CREATE TABLE IF NOT EXISTS feedbacks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id        INTEGER NOT NULL,
    wrong_fields   TEXT    NOT NULL DEFAULT '[]',
    correct_values TEXT    NOT NULL DEFAULT '{}',
    error_category TEXT    NOT NULL DEFAULT 'BC-6',
    note           TEXT,
    status         TEXT    NOT NULL DEFAULT 'open',
    created_at     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fb_lead ON feedbacks(lead_id);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    stage        TEXT NOT NULL,
    version      TEXT NOT NULL,
    content      TEXT,
    note         TEXT,
    activated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_version  TEXT NOT NULL,
    provider        TEXT NOT NULL,
    dataset_size    INTEGER NOT NULL,
    field_accuracy  TEXT,
    intent_accuracy REAL,
    failed_count    INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
