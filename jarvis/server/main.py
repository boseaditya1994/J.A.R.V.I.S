"""Production entrypoint: `uv run uvicorn jarvis.server.main:app`.

Separate from app.py's `create_app()` factory so importing this module —
which touches real settings, the real memory.db, and a real Anthropic
client — never happens as a side effect of testing app.py.
"""

from __future__ import annotations

import logging

from jarvis.core.config import load_settings
from jarvis.core.orchestrator import Orchestrator
from jarvis.memory.store import MemoryStore
from jarvis.server.app import create_app

# Explicit, not relying on uvicorn's own logging setup to cover our own
# loggers (jarvis.server.*) — the background scheduler logs real failures
# (see app.py's _scheduler_loop, push.py's send_push) and those need to
# reliably reach `journalctl -u jarvis`, not silently vanish.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = load_settings()
store = MemoryStore()
# confirm=lambda _: False: no synchronous human to ask over HTTP — see
# app.py's module docstring for why HIGH/CRITICAL-risk tools are
# auto-declined rather than given a real confirmation flow in this phase.
orchestrator = Orchestrator(settings, store, confirm=lambda _: False)

app = create_app(settings, store, orchestrator)
