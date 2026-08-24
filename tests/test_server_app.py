"""Tests for the Phase 9 FastAPI server (jarvis/server/app.py).

Uses create_app()'s factory directly with a fake Orchestrator/real
temp-file MemoryStore — never imports jarvis/server/main.py, which would
touch real settings, a real Anthropic client, and the real data/memory.db.
"""

from fastapi.testclient import TestClient

from jarvis.core import commands
from jarvis.core.config import Settings
from jarvis.memory.store import MemoryStore
from jarvis.server import app as server_app
from jarvis.server.app import create_app


def make_settings(api_auth_token: str = "test-token") -> Settings:
    return Settings(
        jarvis_name="JARVIS",
        anthropic_api_key="sk-test",
        llm_model_default="haiku-model",
        llm_model_complex="sonnet-model",
        stt_model="base",
        tts_voice="en-US-GuyNeural",
        api_auth_token=api_auth_token,
        vapid_public_key="test-public-key",
        vapid_private_key="test-private-key",
    )


class FakeOrchestrator:
    """Stands in for jarvis.core.orchestrator.Orchestrator — create_app only
    calls .handle_turn() and reads .client (for the background scheduler,
    never exercised directly by these HTTP-level tests)."""

    def __init__(self, replies=None):
        self._replies = list(replies or [])
        self.calls = []
        self.client = object()  # never actually used unless hour == 7

    def handle_turn(self, text: str) -> str:
        self.calls.append(text)
        if self._replies:
            return self._replies.pop(0)
        return "a canned reply"


def make_app(tmp_path, replies=None, api_auth_token="test-token"):
    settings = make_settings(api_auth_token=api_auth_token)
    store = MemoryStore(db_path=tmp_path / "memory.db")
    orchestrator = FakeOrchestrator(replies=replies)
    app = create_app(settings, store, orchestrator)
    return app, store, orchestrator


def auth_headers(token="test-token"):
    return {"Authorization": f"Bearer {token}"}


def test_chat_requires_auth(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "hi"})
    assert response.status_code == 401


def test_chat_rejects_wrong_token(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/chat", json={"message": "hi"}, headers=auth_headers("wrong-token")
        )
    assert response.status_code == 401


def test_chat_calls_orchestrator_and_returns_reply(tmp_path):
    app, _, orchestrator = make_app(tmp_path, replies=["hello there"])
    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "hi"}, headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == {"reply": "hello there", "needs_confirmation": False}
    assert orchestrator.calls == ["hi"]


def test_create_app_requires_auth_token_configured(tmp_path):
    settings = make_settings(api_auth_token="")
    store = MemoryStore(db_path=tmp_path / "memory.db")
    orchestrator = FakeOrchestrator()
    try:
        create_app(settings, store, orchestrator)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "API_AUTH_TOKEN" in str(exc)


# -- forget everything two-step flow ----------------------------------------


def test_forget_everything_flow_returns_needs_confirmation(tmp_path):
    app, store, _ = make_app(tmp_path, replies=[commands.FORGET_EVERYTHING])
    store.add_fact("allergic to peanuts")

    with TestClient(app) as client:
        response = client.post(
            "/chat", json={"message": "forget everything"}, headers=auth_headers()
        )

    assert response.status_code == 200
    data = response.json()
    assert data["needs_confirmation"] is True
    assert "deletes all stored facts" in data["reply"]
    assert store.list_facts() != []  # not deleted yet


def test_forget_everything_confirm_wipes_and_logs(tmp_path):
    app, store, _ = make_app(tmp_path, replies=[commands.FORGET_EVERYTHING])
    store.add_fact("allergic to peanuts")

    with TestClient(app) as client:
        client.post("/chat", json={"message": "forget everything"}, headers=auth_headers())
        response = client.post("/forget-everything/confirm", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["reply"] == "Done. I've forgotten everything I knew."
    assert store.list_facts() == []
    row = store.conn.execute(
        "SELECT user_text, assistant_text FROM episodic_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row == ("forget everything", "Done. I've forgotten everything I knew.")


def test_confirm_forget_without_pending_returns_400(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/forget-everything/confirm", headers=auth_headers())
    assert response.status_code == 400


def test_sending_another_message_instead_of_confirming_cancels_forget(tmp_path):
    app, store, _ = make_app(
        tmp_path, replies=[commands.FORGET_EVERYTHING, "sure, what's up?"]
    )
    store.add_fact("allergic to peanuts")

    with TestClient(app) as client:
        client.post("/chat", json={"message": "forget everything"}, headers=auth_headers())
        client.post("/chat", json={"message": "never mind"}, headers=auth_headers())
        # A later confirm attempt now has nothing pending.
        response = client.post("/forget-everything/confirm", headers=auth_headers())

    assert response.status_code == 400
    assert store.list_facts() != []


# -- push subscriptions -------------------------------------------------


def test_vapid_public_key_endpoint(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/vapid-public-key", headers=auth_headers())
    assert response.json() == {"public_key": "test-public-key"}


def test_push_subscribe_stores_subscription(tmp_path):
    app, store, _ = make_app(tmp_path)
    subscription = {
        "endpoint": "https://push.example.com/abcd",
        "keys": {"p256dh": "key1", "auth": "key2"},
    }
    with TestClient(app) as client:
        response = client.post(
            "/push/subscribe", json={"subscription": subscription}, headers=auth_headers()
        )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert store.list_push_subscriptions() == [subscription]


# -- make_push_notify_fn (Phase 9) -------------------------------------------


def test_make_push_notify_fn_returns_true_when_at_least_one_delivery_succeeds(tmp_path, monkeypatch):
    store = MemoryStore(db_path=tmp_path / "memory.db")
    store.add_push_subscription({"endpoint": "https://push.example.com/a", "keys": {}})
    store.add_push_subscription({"endpoint": "https://push.example.com/b", "keys": {}})
    settings = make_settings()

    results = {"https://push.example.com/a": False, "https://push.example.com/b": True}
    monkeypatch.setattr(
        server_app.push, "send_push",
        lambda subscription, title, message, settings: results[subscription["endpoint"]],
    )

    notify_fn = server_app.make_push_notify_fn(store, settings)
    delivered = notify_fn("Title", "Message")

    assert delivered is True
    # The failing subscription gets dropped, the succeeding one stays.
    assert store.list_push_subscriptions() == [{"endpoint": "https://push.example.com/b", "keys": {}}]


def test_make_push_notify_fn_returns_false_when_all_deliveries_fail(tmp_path, monkeypatch):
    store = MemoryStore(db_path=tmp_path / "memory.db")
    store.add_push_subscription({"endpoint": "https://push.example.com/a", "keys": {}})
    settings = make_settings()

    monkeypatch.setattr(server_app.push, "send_push", lambda *a, **k: False)

    notify_fn = server_app.make_push_notify_fn(store, settings)
    delivered = notify_fn("Title", "Message")

    assert delivered is False
    assert store.list_push_subscriptions() == []


def test_make_push_notify_fn_returns_false_with_no_subscriptions(tmp_path):
    store = MemoryStore(db_path=tmp_path / "memory.db")
    settings = make_settings()

    notify_fn = server_app.make_push_notify_fn(store, settings)
    delivered = notify_fn("Title", "Message")

    assert delivered is False
