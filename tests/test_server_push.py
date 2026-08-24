"""Tests for jarvis/server/push.py (Web Push / VAPID delivery)."""

import json

from py_vapid import Vapid02

from jarvis.core.config import Settings
from jarvis.server import push


def make_settings(vapid_private_key: str) -> Settings:
    return Settings(
        jarvis_name="JARVIS",
        anthropic_api_key="sk-test",
        llm_model_default="haiku-model",
        llm_model_complex="sonnet-model",
        stt_model="base",
        tts_voice="en-US-GuyNeural",
        vapid_private_key=vapid_private_key,
        vapid_public_key="unused-here",
    )


def test_generate_vapid_keys_returns_bare_base64url_no_pem_armor():
    private_key, public_key = push.generate_vapid_keys()

    assert private_key  # non-empty
    assert public_key  # non-empty
    assert "-----BEGIN" not in private_key
    assert "\n" not in private_key
    assert "\\n" not in private_key


def test_generate_vapid_keys_private_key_is_actually_parseable_by_py_vapid():
    # Regression test for a real bug found live: the original
    # generate_vapid_keys() produced a full PEM, which py_vapid's
    # Vapid.from_string() (what pywebpush calls internally) can't parse —
    # it strips newlines and base64url-decodes the *whole* string, so a
    # PEM's "-----BEGIN/END-----" armor breaks it with an opaque ASN.1
    # error. A mocked webpush() call would never have caught this, so this
    # test goes through the real py_vapid parser instead.
    private_key, _ = push.generate_vapid_keys()

    parsed = Vapid02.from_string(private_key)

    assert parsed.private_key is not None


def test_generate_vapid_keys_round_trips_through_send_push(monkeypatch):
    private_key, public_key = push.generate_vapid_keys()
    settings = make_settings(vapid_private_key=private_key)
    captured = {}

    def fake_webpush(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(push, "webpush", fake_webpush)

    subscription = {"endpoint": "https://push.example.com/abcd", "keys": {"p256dh": "x", "auth": "y"}}
    result = push.send_push(subscription, "Title", "Body text", settings)

    assert result is True
    assert captured["subscription_info"] == subscription
    assert json.loads(captured["data"]) == {"title": "Title", "body": "Body text"}
    assert captured["vapid_private_key"] == private_key


def test_send_push_returns_false_and_logs_on_any_exception(monkeypatch, caplog):
    settings = make_settings(vapid_private_key="not-a-real-key")

    def raising_webpush(**kwargs):
        raise RuntimeError("expired subscription")

    monkeypatch.setattr(push, "webpush", raising_webpush)

    with caplog.at_level("ERROR"):
        result = push.send_push({"endpoint": "https://example.com/x", "keys": {}}, "Title", "Body", settings)

    assert result is False
    assert "send_push failed" in caplog.text
