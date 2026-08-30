"""SQLite connection + schema for JARVIS memory (Phase 2).

Lives under the project root, not anywhere synced/cloud-backed — see
`docs/ENVIRONMENT.md` on why that matters for a file being written to while
potentially syncing.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from jarvis.core.config import PROJECT_ROOT

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "memory.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    due_at TEXT,
    created_at TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS episodic_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    risk TEXT NOT NULL,
    approved INTEGER NOT NULL,
    result_summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL UNIQUE,
    subscription_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: Phase 9's server touches this connection from
    # several threads (FastAPI's threadpool, the background scheduler) —
    # MemoryStore's own threading.Lock is what actually keeps access safe;
    # this flag just stops sqlite3 rejecting cross-thread use outright.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive, idempotent schema patches CREATE TABLE IF NOT EXISTS can't
    retrofit onto an already-populated table (Phase 8's first need for this:
    tasks.notified_at). Checked via PRAGMA table_info rather than catching
    sqlite3.OperationalError, so an unrelated failure isn't misread as
    "already migrated"."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "notified_at" not in existing:
        conn.execute("ALTER TABLE tasks ADD COLUMN notified_at TEXT")
    if "recurrence" not in existing:
        # NULL = one-time (existing behavior); "weekday" = reschedules
        # itself to the next Mon-Fri occurrence instead of being marked
        # notified forever — see jarvis/interfaces/proactive.py's
        # run_reminder_check.
        conn.execute("ALTER TABLE tasks ADD COLUMN recurrence TEXT")
