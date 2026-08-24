from jarvis.interfaces import notify


def test_notify_empty_message_is_a_noop(monkeypatch):
    calls = []
    # win11toast is imported lazily inside notify() (see notify.py's
    # docstring for why), so there's no module-level `toast` attribute to
    # patch — patch it on the win11toast package itself instead.
    monkeypatch.setattr("win11toast.toast", lambda *a, **k: calls.append((a, k)))

    notify.notify("Title", "   ")

    assert calls == []


def test_notify_calls_toast_with_title_and_message(monkeypatch):
    calls = []
    monkeypatch.setattr("win11toast.toast", lambda *a, **k: calls.append((a, k)))

    notify.notify("JARVIS — Reminders", "Reminders due: buy milk")

    assert calls == [(("JARVIS — Reminders", "Reminders due: buy milk"), {})]
