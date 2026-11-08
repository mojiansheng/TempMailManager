"""SQLite 连接与表结构初始化。"""

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    parent_id  INTEGER,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (parent_id) REFERENCES groups (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mailboxes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT    NOT NULL UNIQUE,
    uuid            TEXT    NOT NULL UNIQUE,
    recovery_phrase TEXT    DEFAULT '',
    lifetime        TEXT    DEFAULT '30d',
    auto_renew      INTEGER NOT NULL DEFAULT 1,
    cookies         TEXT    DEFAULT '',
    note            TEXT    DEFAULT '',
    mailbox_type    INTEGER NOT NULL DEFAULT 1,
    group_id        INTEGER,
    status          TEXT    NOT NULL DEFAULT 'active',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    last_checked_at TEXT,
    last_renewed_at TEXT,
    last_error      TEXT    DEFAULT '',
    sort_order      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS emails (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mailbox_id  INTEGER NOT NULL,
    remote_id   TEXT    NOT NULL,
    sender      TEXT    DEFAULT '',
    subject     TEXT    DEFAULT '',
    received_at TEXT    DEFAULT '',
    body_html   TEXT    DEFAULT '',
    body_text   TEXT    DEFAULT '',
    is_read     INTEGER NOT NULL DEFAULT 0,
    fetched_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (mailbox_id, remote_id),
    FOREIGN KEY (mailbox_id) REFERENCES mailboxes (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_emails_mailbox ON emails (mailbox_id, id DESC);


CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    kind        TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'running',
    total       INTEGER NOT NULL DEFAULT 0,
    done        INTEGER NOT NULL DEFAULT 0,
    lifetime    TEXT    DEFAULT '30d',
    current     TEXT    DEFAULT '',
    error       TEXT    DEFAULT '',
    started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS job_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT    NOT NULL,
    seq         INTEGER NOT NULL DEFAULT 0,
    mailbox_id  INTEGER,
    email       TEXT    DEFAULT '',
    ok          INTEGER NOT NULL DEFAULT 0,
    new_count   INTEGER DEFAULT 0,
    total_count INTEGER DEFAULT 0,
    error       TEXT    DEFAULT '',
    at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_job_items_job ON job_items (job_id, seq);


CREATE TABLE IF NOT EXISTS access_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    method      TEXT    DEFAULT '',
    path        TEXT    DEFAULT '',
    query       TEXT    DEFAULT '',
    status      INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    ip          TEXT    DEFAULT '',
    request_body TEXT   DEFAULT '',
    error       TEXT    DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_access_logs_time ON access_logs (id DESC);

CREATE TABLE IF NOT EXISTS http_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    method        TEXT    DEFAULT '',
    url           TEXT    DEFAULT '',
    status        INTEGER DEFAULT 0,
    duration_ms   INTEGER DEFAULT 0,
    request_body  TEXT    DEFAULT '',
    response_body TEXT    DEFAULT '',
    error         TEXT    DEFAULT '',
    job_id        TEXT    DEFAULT '',
    mailbox_id    INTEGER,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_http_logs_time ON http_logs (id DESC);

-- 按分组查邮箱（老版本在迁移函数里建过，这里保证全新库也带上）
CREATE INDEX IF NOT EXISTS idx_mailboxes_group ON mailboxes (group_id);

CREATE TABLE IF NOT EXISTS settings_kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    level      TEXT NOT NULL DEFAULT 'info',
    action     TEXT DEFAULT '',
    mailbox_id INTEGER,
    message    TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


_REQUIRED_TABLES = ("groups", "mailboxes", "emails", "logs", "jobs",
                    "job_items", "settings_kv", "access_logs", "http_logs")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """每次连接都轻量校验一次表结构，避免数据库文件被外部删除后报 no such table。"""
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        existing = {row["name"] for row in rows}
    except sqlite3.DatabaseError:
        existing = set()
    if not set(_REQUIRED_TABLES).issubset(existing):
        conn.executescript(SCHEMA)
    # 结构版本检查：每连接只读版本号（verify=False），完整结构比对放在启动时做
    from .migrations import migrate

    migrate(conn, verify=False)


def init_db() -> None:
    """启动时建表并做一次完整结构校验 + 升级（需要时先备份整库）。"""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        from .migrations import migrate

        migrate(conn)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
