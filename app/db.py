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

-- Ayarlar > Departmanlar'dan yönetilen birimler. Kapsama haritası ve boşluk analizi buna göre yapılır.
CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    pain_points TEXT,
    sort INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    aliases TEXT,                      -- dokümanlarda geçen diğer adlar (virgülle); proje eşleştirmede kullanılır
    tags TEXT,                         -- etiketler (virgülle), ör. Trello etiketleri: 3rd Party Firma, Dependent
    summary TEXT,
    problem TEXT,
    solution TEXT,
    department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    value_chain TEXT,                  -- v1 alanı, kullanılmıyor
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

-- ---------------------------------------------------------------- doküman bilgi katmanı
-- documents: her yüklenen dosya. Dosyanın kendisi STORAGE_DIR altında (storage_path), metni burada.
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'diger',
    type_source TEXT NOT NULL DEFAULT 'kullanici',   -- kullanici | ai | kural
    source TEXT,                                    -- Doğuş Teknoloji, Dijital Dönüşüm, ...
    doc_date TEXT,                                  -- dokümanın ait olduğu tarih / dönem
    filename TEXT NOT NULL,
    storage_path TEXT,
    sha256 TEXT,
    mime TEXT,
    size INTEGER,
    page_count INTEGER,
    char_count INTEGER,
    text_content TEXT,
    summary TEXT,
    status TEXT NOT NULL DEFAULT 'sirada',          -- sirada | isleniyor | islendi | metin_yok | hata
    ai_mode TEXT,                                   -- işlendiği mod: live (gerçek model) | mock (demo)
    error TEXT,
    initiative_id INTEGER REFERENCES initiatives(id) ON DELETE CASCADE,
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_at TEXT NOT NULL,
    processed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_documents_sha ON documents(sha256);
CREATE INDEX IF NOT EXISTS ix_documents_type ON documents(doc_type, doc_date);

-- Bir doküman birden çok projeyle ilişkili olabilir (ör. DT durum raporu 12 projeyi kapsar).
CREATE TABLE IF NOT EXISTS document_links (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    method TEXT NOT NULL,                           -- manuel | kod | isim | ai
    confidence REAL NOT NULL DEFAULT 1,
    mentions INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (document_id, project_id)
);

-- Arama ve AI bağlamı için doküman parçaları. project_id: parçanın açıkça ait olduğu proje (varsa).
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    heading TEXT,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(document_id, seq);
CREATE INDEX IF NOT EXISTS ix_chunks_project ON chunks(project_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, heading, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, heading) VALUES (new.id, new.text, new.heading);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, heading) VALUES ('delete', old.id, old.text, old.heading);
END;

-- Dokümanlardan çıkarılan yapılandırılmış bilgiler. Her bilgi kaynağını (doküman + alıntı) taşır.
-- status: bilgi (salt bilgi) | oneri (onay bekliyor) | onaylandi | reddedildi | atlandi (yerine başka değer onaylandı)
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    fact_type TEXT NOT NULL,
    field TEXT,
    subfield TEXT,
    value_text TEXT,
    value_num REAL,
    unit TEXT,
    as_of TEXT,
    confidence REAL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'bilgi',
    created_at TEXT NOT NULL,
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_facts_project ON facts(project_id, fact_type, as_of);
CREATE INDEX IF NOT EXISTS ix_facts_status ON facts(status);

-- Kalıcı iş kuyruğu: sunucu yeniden başlasa da yarım kalan işlemler devam eder.
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    ref_id INTEGER,
    status TEXT NOT NULL DEFAULT 'sirada',          -- sirada | calisiyor | tamam | hata
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status, id);

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
    source_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS security_metrics (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    note TEXT,
    UNIQUE(period, metric)
);

-- AI tarafından üretilen metinler: haftalık portföy yorumu, boşluk analizi, proje sentezi.
CREATE TABLE IF NOT EXISTS ai_insights (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,                             -- weekly | gap | project
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    source_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
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

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
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

# v1 veritabanlarında eksik kalan sütunlar (başlangıçta otomatik eklenir)
MIGRATIONS = {
    "projects": {"aliases": "TEXT", "tags": "TEXT", "department_id": "INTEGER REFERENCES departments(id) ON DELETE SET NULL"},
    "documents": {"ai_mode": "TEXT"},
    "ai_insights": {"project_id": "INTEGER", "source_document_id": "INTEGER"},
    "actions": {"source_document_id": "INTEGER"},
}


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
        legacy_docs = c.execute("SELECT 1 FROM sqlite_master WHERE name = 'documents'").fetchone() and not any(
            r[1] == "doc_type" for r in c.execute("PRAGMA table_info(documents)"))
        if legacy_docs:  # v1 doküman tablosu farklı yapıda; yeni katmana yer açmak için yeniden adlandır
            c.execute("ALTER TABLE documents RENAME TO documents_v1")
        legacy_insights = c.execute("SELECT 1 FROM sqlite_master WHERE name = 'ai_insights'").fetchone()
        if legacy_insights:
            for table, cols in MIGRATIONS.items():
                have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
                for col, decl in cols.items():
                    if have and col not in have:
                        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
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


def setting(key: str, default: str | None = None) -> str | None:
    v = scalar("SELECT value FROM settings WHERE key = ?", (key,))
    return default if v is None else v


def set_setting(key: str, value: str) -> None:
    execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def log(user_id: int | None, action: str, target_type: str | None = None, target_id: int | None = None, detail: str = "") -> None:
    insert("activity", {
        "user_id": user_id, "action": action, "target_type": target_type,
        "target_id": target_id, "detail": detail, "at": now(),
    })
