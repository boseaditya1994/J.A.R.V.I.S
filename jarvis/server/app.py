"""FastAPI server (Phase 9): the multi-device entrypoint. Wraps
Orchestrator.handle_turn() over HTTP so a phone/laptop browser (via the PWA
in jarvis/server/static/) can reach the same assistant cli.py talks to
locally — memory, tools, and command dispatch (research/ingest/remember/...,
jarvis/core/commands.py) are all reused completely unchanged.

HIGH/CRITICAL-risk tool calls (filesystem_write, shell_execute) are
auto-declined here — the Orchestrator this module wires up in production
(see main.py) is built with `confirm=lambda _: False`, the same safety-net
pattern jarvis/interfaces/proactive.py already established for its own
headless jobs. There's no synchronous human to ask over a stateless HTTP
request; a real async pause/resume confirmation flow is deliberately
deferred (see docs/ROADMAP.md Phase 9's scope note).

`create_app()` is a pure factory — it takes an already-constructed
Settings/MemoryStore/Orchestrator rather than building them itself, so
tests can inject fakes without ever touching a real Anthropic client or
data/memory.db. Production wiring lives in main.py, imported only when the
server actually runs.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

import anthropic
from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from jarvis.core import commands
from jarvis.core.config import Settings
from jarvis.core.orchestrator import Orchestrator
from jarvis.interfaces import proactive
from jarvis.memory.store import MemoryStore
from jarvis.server import push
from jarvis.server.auth import require_auth

REMINDER_CHECK_INTERVAL_SECONDS = 15 * 60
STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    needs_confirmation: bool = False


class PushSubscribeRequest(BaseModel):
    subscription: dict


def make_push_notify_fn(store: MemoryStore, settings: Settings) -> Callable[[str, str], None]:
    """The server's `notify_fn` for jarvis/interfaces/proactive.py's
    run_morning_brief/run_reminder_check — a drop-in replacement for
    jarvis/interfaces/notify.py's Windows toast. Fans a notification out to
    every subscribed device (phone, laptop browser, ...); a subscription
    that fails to deliver (e.g. expired) is dropped rather than retried
    forever."""

    def notify(title: str, message: str) -> None:
        for subscription in store.list_push_subscriptions():
            if not push.send_push(subscription, title, message, settings):
                store.remove_push_subscription(subscription["endpoint"])

    return notify


async def run_scheduler_once(
    store: MemoryStore,
    settings: Settings,
    client: anthropic.Anthropic,
    notify_fn: Callable[[str, str], None],
    last_morning_brief_date: object | None,
    morning_brief_hour: int = 7,
) -> object | None:
    """One tick of the background scheduler — factored out from the
    infinite loop so it's directly testable. Returns the (possibly updated)
    `last_morning_brief_date` the caller should pass back in next tick.

    `morning_brief_hour` is interpreted in the server's local system clock
    — set the VM's timezone during setup (see README) rather than doing
    timezone math here.
    """
    await asyncio.to_thread(proactive.run_reminder_check, store, settings, notify_fn)

    now = datetime.now()
    if now.hour == morning_brief_hour and last_morning_brief_date != now.date():
        await asyncio.to_thread(proactive.run_morning_brief, client, settings, store, notify_fn)
        last_morning_brief_date = now.date()

    return last_morning_brief_date


async def _scheduler_loop(
    store: MemoryStore, settings: Settings, client: anthropic.Anthropic, notify_fn: Callable[[str, str], None]
) -> None:
    last_morning_brief_date = None
    while True:
        try:
            last_morning_brief_date = await run_scheduler_once(
                store, settings, client, notify_fn, last_morning_brief_date
            )
        except Exception:
            # A transient failure (network blip, API error) shouldn't kill
            # the scheduler for the rest of the process's life.
            pass
        await asyncio.sleep(REMINDER_CHECK_INTERVAL_SECONDS)


def create_app(settings: Settings, store: MemoryStore, orchestrator: Orchestrator) -> FastAPI:
    if not settings.api_auth_token:
        raise RuntimeError(
            "API_AUTH_TOKEN must be set in .env to run the Phase 9 server — "
            "see config/settings.example.env."
        )

    auth_dependency = require_auth(settings)
    notify_fn = make_push_notify_fn(store, settings)
    # Single-user server: one pending-forget slot is enough, mirroring
    # cli.py's own single in-process confirmation prompt.
    pending_forget: dict[str, str | None] = {"user_text": None}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(_scheduler_loop(store, settings, orchestrator.client, notify_fn))
        yield
        task.cancel()

    app = FastAPI(lifespan=lifespan)

    @app.post("/chat", response_model=ChatResponse, dependencies=[Depends(auth_dependency)])
    def chat(request: ChatRequest) -> ChatResponse:
        if pending_forget["user_text"] is not None:
            # A previous turn asked to forget everything and the user sent
            # something else instead of confirming — treat as a decline,
            # same as cli.py's "anything but yes" branch.
            store.log_turn(pending_forget["user_text"], "Okay — I left your memory as it was.")
            pending_forget["user_text"] = None

        reply = orchestrator.handle_turn(request.message)

        if reply == commands.FORGET_EVERYTHING:
            pending_forget["user_text"] = request.message
            return ChatResponse(
                reply=(
                    "This deletes all stored facts, tasks, and history. "
                    "POST /forget-everything/confirm to proceed, or send "
                    "another message to cancel."
                ),
                needs_confirmation=True,
            )

        return ChatResponse(reply=reply)

    @app.post(
        "/forget-everything/confirm",
        response_model=ChatResponse,
        dependencies=[Depends(auth_dependency)],
    )
    def confirm_forget() -> ChatResponse:
        if pending_forget["user_text"] is None:
            raise HTTPException(status_code=400, detail="Nothing pending confirmation.")
        store.forget_everything()
        reply = "Done. I've forgotten everything I knew."
        store.log_turn(pending_forget["user_text"], reply)
        pending_forget["user_text"] = None
        return ChatResponse(reply=reply)

    @app.get("/vapid-public-key", dependencies=[Depends(auth_dependency)])
    def vapid_public_key() -> dict:
        return {"public_key": settings.vapid_public_key}

    @app.post("/push/subscribe", dependencies=[Depends(auth_dependency)])
    def push_subscribe(request: PushSubscribeRequest) -> dict:
        store.add_push_subscription(request.subscription)
        return {"ok": True}

    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app
