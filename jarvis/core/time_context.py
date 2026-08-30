"""Shared helper for injecting the current date/time into system prompts.

Claude has no live clock and isn't fed wall-clock time by default — found
live: asked "what's the date and time now?", JARVIS answered the date
(guessed from training data) but correctly said it had no access to the
actual time of day. Fixed by computing this fresh on every call (never
cached — the Orchestrator and the server process are long-lived, so a
value computed once at startup would go stale) and prepending it to every
system prompt that benefits from knowing "now": main chat
(jarvis/core/orchestrator.py), the research agent (jarvis/agents/research.py),
and the morning brief (jarvis/interfaces/proactive.py).

Lives in its own small module, not on Orchestrator itself, since
orchestrator.py already imports jarvis.agents.research — research.py
importing back from orchestrator.py would be a circular import.
"""

from __future__ import annotations

from datetime import datetime


def current_datetime_context() -> str:
    """A human-readable "current date and time" line, computed fresh each
    call from the process's local system clock — matches whatever
    timezone the machine/VM is actually configured for (see README's
    timezone setup note for the deployed server)."""
    now = datetime.now()
    return f"Current date and time: {now.strftime('%A, %B %d, %Y, %I:%M %p')}."
