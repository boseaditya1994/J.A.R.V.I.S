"""MemoryStore: CRUD over the JARVIS memory database.

Explicit-only policy (confirmed with the user): nothing lands here unless
the user explicitly asked for it via a "remember"/"remind me" command
(see jarvis/core/commands.py), or it's the automatic episodic log of the
conversation the user was already having.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jarvis.memory.db import connect


@dataclass(frozen=True)
class Fact:
    id: int
    text: str
    created_at: str


@dataclass(frozen=True)
class Task:
    id: int
    text: str
    due_at: str | None
    created_at: str
    done: bool
    notified_at: str | None = None
    recurrence: str | None = None  # None = one-time; "weekday" = Mon-Fri recurring


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryStore:
    def __init__(self, db_path: Path | None = None):
        self.conn = connect(db_path)
        # Phase 9's server touches the same MemoryStore from several
        # threads at once (FastAPI's threadpool per request, plus the
        # background scheduler's asyncio.to_thread calls) — sqlite3
        # connections aren't safe for concurrent use across threads, so
        # every method below serializes through this lock. cli.py and
        # proactive.py are single-threaded and pay only the (negligible)
        # cost of an uncontended lock.
        self._lock = threading.Lock()

    def close(self) -> None:
        self.conn.close()

    # -- Facts ---------------------------------------------------------

    def add_fact(self, text: str) -> Fact:
        text = text.strip()
        created = _now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO facts (text, created_at) VALUES (?, ?)", (text, created)
            )
            self.conn.commit()
        return Fact(id=cur.lastrowid, text=text, created_at=created)

    def list_facts(self) -> list[Fact]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, text, created_at FROM facts ORDER BY id"
            ).fetchall()
        return [Fact(*row) for row in rows]

    def delete_facts_matching(self, substring: str) -> list[Fact]:
        needle = substring.strip().lower()
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, text, created_at FROM facts ORDER BY id"
            ).fetchall()
            matches = [f for f in (Fact(*row) for row in rows) if needle in f.text.lower()]
            if matches:
                self.conn.executemany(
                    "DELETE FROM facts WHERE id = ?", [(f.id,) for f in matches]
                )
                self.conn.commit()
        return matches

    # -- Tasks -----------------------------------------------------------

    def add_task(
        self, text: str, due_at: str | None = None, recurrence: str | None = None
    ) -> Task:
        text = text.strip()
        created = _now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO tasks (text, due_at, created_at, done, recurrence) VALUES (?, ?, ?, 0, ?)",
                (text, due_at, created, recurrence),
            )
            self.conn.commit()
        return Task(
            id=cur.lastrowid, text=text, due_at=due_at, created_at=created, done=False,
            recurrence=recurrence,
        )

    def list_open_tasks(self) -> list[Task]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, text, due_at, created_at, done, notified_at, recurrence FROM tasks "
                "WHERE done = 0 ORDER BY id"
            ).fetchall()
        return [
            Task(id=r[0], text=r[1], due_at=r[2], created_at=r[3], done=bool(r[4]),
                 notified_at=r[5], recurrence=r[6])
            for r in rows
        ]

    def list_due_unnotified_tasks(self, now_iso: str) -> list[Task]:
        """`now_iso` must be naive local time (`datetime.now().isoformat()`),
        matching how `due_at` is stored by commands.py's dateparser-based
        `_handle_remind` — not the tz-aware UTC convention `_now()` uses
        elsewhere in this store (a known, accepted mismatch; see
        docs/ROADMAP.md Phase 8)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, text, due_at, created_at, done, notified_at, recurrence FROM tasks "
                "WHERE done = 0 AND notified_at IS NULL "
                "AND due_at IS NOT NULL AND due_at <= ? ORDER BY due_at",
                (now_iso,),
            ).fetchall()
        return [
            Task(id=r[0], text=r[1], due_at=r[2], created_at=r[3], done=bool(r[4]),
                 notified_at=r[5], recurrence=r[6])
            for r in rows
        ]

    def mark_task_notified(self, task_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE tasks SET notified_at = ? WHERE id = ?", (_now(), task_id)
            )
            self.conn.commit()

    def reschedule_task(self, task_id: int, new_due_at: str) -> None:
        """For a recurring task: move it to its next occurrence and clear
        notified_at, so list_due_unnotified_tasks picks it up again once
        the new due_at passes — instead of mark_task_notified's permanent
        "done for good" (used for one-time reminders)."""
        with self._lock:
            self.conn.execute(
                "UPDATE tasks SET due_at = ?, notified_at = NULL WHERE id = ?",
                (new_due_at, task_id),
            )
            self.conn.commit()

    # -- Episodic log ----------------------------------------------------

    def log_turn(self, user_text: str, assistant_text: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO episodic_log (timestamp, user_text, assistant_text) VALUES (?, ?, ?)",
                (_now(), user_text, assistant_text),
            )
            self.conn.commit()

    # -- Tool audit log ----------------------------------------------------

    def log_tool_call(
        self,
        tool_name: str,
        tool_input: dict,
        risk: str,
        approved: bool,
        result_summary: str,
    ) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO tool_audit_log "
                "(timestamp, tool_name, input_json, risk, approved, result_summary) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_now(), tool_name, json.dumps(tool_input), risk, int(approved), result_summary),
            )
            self.conn.commit()

    # -- Notifications (Phase 8) -------------------------------------------

    def log_notification(self, kind: str, content: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO notifications_log (timestamp, kind, content) VALUES (?, ?, ?)",
                (_now(), kind, content),
            )
            self.conn.commit()

    def count_notifications_since(self, since_iso: str) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM notifications_log WHERE timestamp >= ?", (since_iso,)
            ).fetchone()
        return row[0]

    # -- Push subscriptions (Phase 9) ---------------------------------------

    def add_push_subscription(self, subscription: dict) -> None:
        """Idempotent on `endpoint` — re-subscribing the same device updates
        its stored keys rather than duplicating the row."""
        endpoint = subscription["endpoint"]
        with self._lock:
            self.conn.execute(
                "INSERT INTO push_subscriptions (endpoint, subscription_json, created_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(endpoint) DO UPDATE SET subscription_json = excluded.subscription_json",
                (endpoint, json.dumps(subscription), _now()),
            )
            self.conn.commit()

    def list_push_subscriptions(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT subscription_json FROM push_subscriptions ORDER BY id"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def remove_push_subscription(self, endpoint: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
            self.conn.commit()

    # -- Nuclear option ----------------------------------------------------

    def forget_everything(self) -> None:
        # Deliberately doesn't touch push_subscriptions — those are device
        # registrations, not personal memory, and wiping facts/tasks
        # shouldn't silently unsubscribe your phone/laptop from push.
        with self._lock:
            self.conn.execute("DELETE FROM facts")
            self.conn.execute("DELETE FROM tasks")
            self.conn.execute("DELETE FROM episodic_log")
            self.conn.execute("DELETE FROM tool_audit_log")
            self.conn.execute("DELETE FROM notifications_log")
            self.conn.commit()
