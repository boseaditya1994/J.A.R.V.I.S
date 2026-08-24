"""Tests for the Phase 8 proactive jobs (jarvis/interfaces/proactive.py)."""

from datetime import datetime
from types import SimpleNamespace

from jarvis.core.config import Settings
from jarvis.interfaces import proactive
from jarvis.memory.store import MemoryStore


def make_settings(max_notifications_per_day: int = 10) -> Settings:
    return Settings(
        jarvis_name="JARVIS",
        anthropic_api_key="sk-test",
        llm_model_default="haiku-model",
        llm_model_complex="sonnet-model",
        stt_model="base",
        tts_voice="en-US-GuyNeural",
        max_notifications_per_day=max_notifications_per_day,
    )


def make_store(tmp_path) -> MemoryStore:
    return MemoryStore(db_path=tmp_path / "memory.db")


class ScriptedMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = {**kwargs, "messages": list(kwargs["messages"])}
        response = self._responses[self.call_count]
        self.call_count += 1
        return response


class FakeClient:
    def __init__(self, messages):
        self.messages = messages


def _text_response(text: str):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block], stop_reason="end_turn", container=None)


# -- Morning brief -----------------------------------------------------------


def test_morning_brief_uses_only_scoped_tools(tmp_path):
    messages = ScriptedMessages([_text_response("Good morning! Nothing urgent today.")])
    client = FakeClient(messages)
    store = make_store(tmp_path)

    proactive.run_morning_brief(client, make_settings(), store, notify_fn=lambda t, m: None)

    tool_names = {t.get("name") for t in messages.last_kwargs["tools"]}
    assert tool_names == {"knowledge_search", "web_search"}
    assert "web_fetch" not in tool_names
    assert "filesystem_write" not in tool_names
    assert "shell_execute" not in tool_names
    assert "calculator" not in tool_names


def test_morning_brief_uses_haiku_complexity(tmp_path):
    messages = ScriptedMessages([_text_response("Good morning!")])
    client = FakeClient(messages)
    settings = make_settings()
    store = make_store(tmp_path)

    proactive.run_morning_brief(client, settings, store, notify_fn=lambda t, m: None)

    assert messages.last_kwargs["model"] == settings.llm_model_default


def test_morning_brief_delivers_via_notify_fn_and_logs(tmp_path):
    messages = ScriptedMessages([_text_response("Good morning! Nothing urgent today.")])
    client = FakeClient(messages)
    store = make_store(tmp_path)
    notified = []

    proactive.run_morning_brief(
        client, make_settings(), store, notify_fn=lambda title, msg: notified.append((title, msg))
    )

    assert notified == [("JARVIS — Morning Brief", "Good morning! Nothing urgent today.")]
    row = store.conn.execute(
        "SELECT kind, content FROM notifications_log"
    ).fetchone()
    assert row == ("morning_brief", "Good morning! Nothing urgent today.")


def test_morning_brief_skips_when_rate_limit_reached(tmp_path):
    store = make_store(tmp_path)
    store.log_notification("reminder_check", "already sent")
    messages = ScriptedMessages([_text_response("Good morning!")])
    client = FakeClient(messages)
    notified = []

    proactive.run_morning_brief(
        client, make_settings(max_notifications_per_day=1), store,
        notify_fn=lambda t, m: notified.append((t, m)) or True,
    )

    assert notified == []
    assert messages.call_count == 0


# -- Reminder check ------------------------------------------------------


def test_reminder_check_only_notifies_due_unnotified_tasks(tmp_path):
    store = make_store(tmp_path)
    due = store.add_task("call Mom", due_at="2026-08-20T09:00:00")
    store.add_task("future task", due_at="2026-08-25T09:00:00")
    no_due_date = store.add_task("no due date")
    notified = []

    proactive.run_reminder_check(
        store, make_settings(), notify_fn=lambda t, m: notified.append((t, m)) or True,
        now=datetime.fromisoformat("2026-08-20T12:00:00"),
    )

    assert len(notified) == 1
    title, message = notified[0]
    assert title == "JARVIS — Reminders"
    assert "call Mom" in message
    assert "future task" not in message
    updated = {t.id: t for t in store.list_open_tasks()}
    assert updated[due.id].notified_at is not None
    assert updated[no_due_date.id].notified_at is None


def test_reminder_check_batches_multiple_due_tasks_into_one_notification(tmp_path):
    store = make_store(tmp_path)
    store.add_task("call Mom", due_at="2026-08-20T09:00:00")
    store.add_task("buy milk", due_at="2026-08-20T10:00:00")
    notified = []

    proactive.run_reminder_check(
        store, make_settings(), notify_fn=lambda t, m: notified.append((t, m)) or True,
        now=datetime.fromisoformat("2026-08-20T12:00:00"),
    )

    assert len(notified) == 1
    assert "call Mom" in notified[0][1]
    assert "buy milk" in notified[0][1]


def test_reminder_check_does_not_renotify_on_second_call(tmp_path):
    store = make_store(tmp_path)
    store.add_task("call Mom", due_at="2026-08-20T09:00:00")
    notified = []
    now = datetime.fromisoformat("2026-08-20T12:00:00")

    proactive.run_reminder_check(store, make_settings(), notify_fn=lambda t, m: notified.append((t, m)) or True, now=now)
    proactive.run_reminder_check(store, make_settings(), notify_fn=lambda t, m: notified.append((t, m)) or True, now=now)

    assert len(notified) == 1


def test_reminder_check_no_due_tasks_does_not_notify(tmp_path):
    store = make_store(tmp_path)
    store.add_task("future task", due_at="2026-08-25T09:00:00")
    notified = []

    proactive.run_reminder_check(
        store, make_settings(), notify_fn=lambda t, m: notified.append((t, m)),
        now=datetime.fromisoformat("2026-08-20T12:00:00"),
    )

    assert notified == []


def test_reminder_check_does_not_mark_notified_when_delivery_fails(tmp_path):
    # Regression test for a real bug found live: notify_fn used to be
    # allowed to raise on failure, and mark_task_notified only ran if it
    # didn't — but once notify_fn started catching its own errors (so a
    # bad push subscription can't crash the scheduler), that safety net
    # disappeared, and a real delivery failure got silently marked
    # "notified" and never retried. notify_fn's return value is now what
    # gates marking, not whether it happened to raise.
    store = make_store(tmp_path)
    store.add_task("call Mom", due_at="2026-08-20T09:00:00")
    notified = []

    proactive.run_reminder_check(
        store, make_settings(), notify_fn=lambda t, m: notified.append((t, m)) or False,
        now=datetime.fromisoformat("2026-08-20T12:00:00"),
    )

    assert len(notified) == 1  # delivery was attempted
    assert store.list_open_tasks()[0].notified_at is None  # but not marked, since it failed

    # A later successful call should still pick it up and retry.
    proactive.run_reminder_check(
        store, make_settings(), notify_fn=lambda t, m: notified.append((t, m)) or True,
        now=datetime.fromisoformat("2026-08-20T12:00:00"),
    )
    assert len(notified) == 2
    assert store.list_open_tasks()[0].notified_at is not None


def test_reminder_check_skips_when_rate_limit_reached(tmp_path):
    store = make_store(tmp_path)
    store.add_task("call Mom", due_at="2026-08-20T09:00:00")
    store.log_notification("morning_brief", "already sent")
    notified = []

    proactive.run_reminder_check(
        store, make_settings(max_notifications_per_day=1),
        notify_fn=lambda t, m: notified.append((t, m)) or True,
        now=datetime.fromisoformat("2026-08-20T12:00:00"),
    )

    assert notified == []
    assert store.list_open_tasks()[0].notified_at is None
