"""SQLite: подключение, миграции, резервные копии.

Принципы:
* все объекты имеют неизменяемый внутренний ID (uuid4 hex), имя — просто поле;
* миграции только добавляют (никогда не удаляют данные);
* перед применением миграций к существующей БД делается backup.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Iterable

from . import VERSION
from .config import BACKUP_DIR, DB_PATH, ensure_dirs


def new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------- migrations
# Каждая миграция — (номер, описание, SQL или функция(conn)). Только добавлять в конец.
MIGRATIONS: list[tuple[int, str, str | Callable[[sqlite3.Connection], None]]] = [
    (1, "Начальная схема", """
        CREATE TABLE orders(
            id TEXT PRIMARY KEY,
            number TEXT NOT NULL DEFAULT '',
            client TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            date TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE products(
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            name TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT 'shower',
            position INTEGER NOT NULL DEFAULT 0,
            data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_products_order ON products(order_id);
        -- Универсальная библиотека: производители, категории, фурнитура, профили,
        -- комплекты, шаблоны конструкций, шаблоны обработки и т.д.
        CREATE TABLE library(
            id TEXT PRIMARY KEY,
            collection TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_library_collection ON library(collection);
        CREATE TABLE dxf_files(
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            original_filename TEXT NOT NULL DEFAULT '',
            stored_name TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """),
    (2, "CRM: сделки, контакты, компании, задачи, лента, автоматизация, каналы", """
        CREATE TABLE crm_users(
            id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT '#1f6f8b',
            active INTEGER NOT NULL DEFAULT 1, data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE companies(
            id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', inn TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE contacts(
            id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            phone_norm TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
            company_id TEXT REFERENCES companies(id) ON DELETE SET NULL, position TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_contacts_phone ON contacts(phone_norm);
        CREATE INDEX idx_contacts_email ON contacts(email);
        CREATE TABLE pipelines(
            id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE stages(
            id TEXT PRIMARY KEY, pipeline_id TEXT NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
            name TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT '#cfe3ea', position INTEGER NOT NULL DEFAULT 0,
            kind TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE deals(
            id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', pipeline_id TEXT, stage_id TEXT,
            amount REAL NOT NULL DEFAULT 0, contact_id TEXT REFERENCES contacts(id) ON DELETE SET NULL,
            company_id TEXT REFERENCES companies(id) ON DELETE SET NULL,
            order_id TEXT REFERENCES orders(id) ON DELETE SET NULL,
            responsible_id TEXT, source TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '', closed_at TEXT, stage_changed_at TEXT,
            data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_deals_stage ON deals(stage_id);
        CREATE INDEX idx_deals_contact ON deals(contact_id);
        CREATE INDEX idx_deals_order ON deals(order_id);
        CREATE TABLE tasks(
            id TEXT PRIMARY KEY, text TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'call',
            due_at TEXT, done INTEGER NOT NULL DEFAULT 0, done_at TEXT, result TEXT NOT NULL DEFAULT '',
            deal_id TEXT REFERENCES deals(id) ON DELETE CASCADE,
            contact_id TEXT REFERENCES contacts(id) ON DELETE CASCADE,
            responsible_id TEXT, data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_tasks_due ON tasks(done, due_at);
        CREATE TABLE events(
            id TEXT PRIMARY KEY, deal_id TEXT REFERENCES deals(id) ON DELETE CASCADE,
            contact_id TEXT REFERENCES contacts(id) ON DELETE CASCADE,
            kind TEXT NOT NULL DEFAULT 'note', text TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}',
            author TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE INDEX idx_events_deal ON events(deal_id, created_at);
        CREATE INDEX idx_events_contact ON events(contact_id, created_at);
        CREATE TABLE automations(
            id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
            trigger TEXT NOT NULL DEFAULT 'stage_enter', stage_id TEXT, data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE channels(
            id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'form',
            active INTEGER NOT NULL DEFAULT 1, token TEXT NOT NULL DEFAULT '',
            data TEXT NOT NULL DEFAULT '{}', state TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
    """),
]


def _current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL, applied_at TEXT NOT NULL, app_version TEXT NOT NULL DEFAULT '')"
    )
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return row["v"] or 0


def backup_db(reason: str = "manual") -> str | None:
    """Копия БД в BACKUP_DIR. Используется sqlite backup API (безопасно при работе)."""
    ensure_dirs()
    if not DB_PATH.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"glasscad-{stamp}-{reason}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    _rotate_backups()
    return str(target)


def _rotate_backups(keep: int = 60) -> None:
    files = sorted(BACKUP_DIR.glob("glasscad-*.db"))
    for f in files[:-keep]:
        f.unlink(missing_ok=True)


def migrate() -> list[int]:
    ensure_dirs()
    existed = DB_PATH.exists() and DB_PATH.stat().st_size > 0
    conn = connect()
    try:
        current = _current_version(conn)
        pending = [m for m in MIGRATIONS if m[0] > current]
        if pending and existed and current > 0:
            backup_db(f"pre-migrate-v{current}")
        applied = []
        for version, _desc, step in pending:
            conn.execute("BEGIN")
            try:
                if callable(step):
                    step(conn)
                else:
                    for stmt in _split_sql(step):
                        conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_version(version, applied_at, app_version) VALUES (?,?,?)",
                    (version, now_iso(), VERSION),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            applied.append(version)
        return applied
    finally:
        conn.close()


def _split_sql(sql: str) -> Iterable[str]:
    for part in sql.split(";"):
        lines = [ln for ln in part.splitlines() if not ln.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if stmt:
            yield stmt


def schema_version() -> int:
    conn = connect()
    try:
        return _current_version(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------- helpers
def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    if "data" in d:
        try:
            d["data"] = json.loads(d["data"] or "{}")
        except json.JSONDecodeError:
            d["data"] = {}
    return d


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
