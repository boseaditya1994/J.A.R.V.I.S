"""Tests for jarvis/server/push.py (Web Push / VAPID delivery)."""

import json

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


def test_generate_vapid_keys_round_trips_through_send_push(monkeypatch):
    private_for_env, public_b64url = push.generate_vapid_keys()
    assert public_b64url  # non-empty
    assert private_for_env.startswith("-----BEGIN PRIVATE KEY-----")

    settings = make_settings(vapid_private_key=private_for_env)
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
    # The private key passed through has real newlines, not the escaped \n
    # stored in the env value.
    assert "\\n" not in captured["vapid_private_key"]
    assert "\n" in captured["vapid_private_key"]


def test_send_push_returns_false_on_webpush_exception(monkeypatch):
    settings = make_settings(vapid_private_key="-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n")

    def raising_webpush(**kwargs):
        raise push.WebPushException("expired subscription")

    monkeypatch.setattr(push, "webpush", raising_webpush)

    result = push.send_push({"endpoint": "x", "keys": {}}, "Title", "Body", settings)

    assert result is False
