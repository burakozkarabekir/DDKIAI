"""SQLite veri katmanı. Küçük ekip ve tek sunucu için yeterli; ileride PostgreSQL'e taşınabilir."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    title TEXT,
    organization TEXT NOT NULL DEFAULT 'Doğuş Otomotiv',
    role TEXT NOT NULL DEFAULT 'viewer',
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    last_login TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    summary TEXT,
    problem TEXT,
    solution TEXT,
    value_chain TEXT,
    business_unit TEXT,
    brands TEXT,
    ai_type TEXT,
    stage TEXT NOT NULL DEFAULT 'fikir',
    health TEXT NOT NULL DEFAULT 'yesil',
    priority TEXT DEFAULT 'Orta',
    sponsor TEXT,
    owner TEXT,
    dt_lead TEXT,
    start_date TEXT,
    target_date TEXT,
    golive_date TEXT,
    measurement_status TEXT NOT NULL DEFAULT 'yok',
    estimated_value REAL,
    realized_value REAL,
    fte_saving REAL,
    security_review TEXT NOT NULL DEFAULT 'yok',
    data_class TEXT,
    visible_to_dt INTEGER NOT NULL DEFAULT 1,
    ai_risk_score INTEGER,
    ai_risk_note TEXT,
    last_status_at TEXT,
    trello_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kpis (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    unit TEXT,
    direction TEXT NOT NULL DEFAULT 'up',
    baseline REAL,
    target REAL,
    actual REAL,
    method TEXT,
    measured_at TEXT
);

CREATE TABLE IF NOT EXISTS stage_history (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    from_stage TEXT,
    to_stage TEXT NOT NULL,
    note TEXT,
    missing_criteria TEXT,
    user_id INTEGER REFERENCES users(id),
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS initiatives (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'guvenlik',
    description TEXT,
    owner TEXT,
    status TEXT,
    health TEXT NOT NULL DEFAULT 'yesil',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    initiative_id INTEGER REFERENCES initiatives(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT,
    filename TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    mime TEXT,
    size INTEGER,
    text_content TEXT,
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_reports (
    id INTEGER PRIMARY KEY,
    week_start TEXT NOT NULL,
    title TEXT NOT NULL,
    filename TEXT,
    stored_name TEXT,
    text_content TEXT,
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_at TEXT NOT NULL,
    ai_status TEXT NOT NULL DEFAULT 'bekliyor',
    ai_summary TEXT,
    ai_raw TEXT,
    ai_error TEXT,
    applied INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS report_updates (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES weekly_reports(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    project_ref TEXT,
    status_text TEXT,
    suggested_health TEXT,
    risk_score INTEGER,
    risk_reasons TEXT,
    blockers TEXT,
    next_steps TEXT,
    ai_comment TEXT
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'yorum',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_comments_target ON comments(target_type, target_id);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    owner TEXT,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'acik',
    source TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS org_units (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES org_units(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'birim',
    value_chain TEXT,
    headcount INTEGER,
    description TEXT,
    pain_points TEXT
);

CREATE TABLE IF NOT EXISTS security_metrics (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    note TEXT,
    UNIQUE(period, metric)
);

CREATE TABLE IF NOT EXISTS ai_insights (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    source_report_id INTEGER REFERENCES weekly_reports(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    target_type TEXT,
    target_id INTEGER,
    detail TEXT,
    at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def tx():
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
    with tx() as c:
        c.executescript(SCHEMA)


def rows(sql: str, params=()) -> list[dict]:
    with tx() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def row(sql: str, params=()) -> dict | None:
    with tx() as c:
        r = c.execute(sql, params).fetchone()
        return dict(r) if r else None


def scalar(sql: str, params=()):
    with tx() as c:
        r = c.execute(sql, params).fetchone()
        return r[0] if r else None


def execute(sql: str, params=()) -> int:
    with tx() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def insert(table: str, data: dict) -> int:
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    return execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))


def update(table: str, id_: int, data: dict) -> None:
    if not data:
        return
    sets = ", ".join(f"{k} = ?" for k in data)
    execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*data.values(), id_))


def log(user_id: int | None, action: str, target_type: str | None = None, target_id: int | None = None, detail: str = "") -> None:
    insert("activity", {
        "user_id": user_id, "action": action, "target_type": target_type,
        "target_id": target_id, "detail": detail, "at": now(),
    })
