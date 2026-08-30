from datetime import datetime

from jarvis.core import time_context


def test_current_datetime_context_includes_expected_prefix():
    result = time_context.current_datetime_context()

    assert result.startswith("Current date and time: ")


def test_current_datetime_context_reflects_the_system_clock(monkeypatch):
    class FixedDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 8, 25, 21, 5)

    monkeypatch.setattr(time_context, "datetime", FixedDateTime)

    result = time_context.current_datetime_context()

    assert result == "Current date and time: Tuesday, August 25, 2026, 09:05 PM."


def test_current_datetime_context_is_computed_fresh_each_call(monkeypatch):
    # Never cached — a long-lived Orchestrator/server process would
    # otherwise go stale.
    calls = {"count": 0}
    real_now = datetime.now

    class SpyDateTime:
        @classmethod
        def now(cls):
            calls["count"] += 1
            return real_now()

    monkeypatch.setattr(time_context, "datetime", SpyDateTime)

    time_context.current_datetime_context()
    time_context.current_datetime_context()

    assert calls["count"] == 2
