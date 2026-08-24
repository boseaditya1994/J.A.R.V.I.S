"""Deterministic, LLM-free detection of explicit memory commands.

Checked before a turn goes to the LLM (see jarvis/core/orchestrator.py).
Regex-based on purpose: no extra LLM call, fully predictable, zero
hallucination risk for reads/deletes. Known limitation, accepted for Phase
2: a phrase like "remember when we talked about X?" will misfire as a store
command. Phase 3's real tool-calling (the LLM judging intent itself) is the
proper fix for that — not worth chasing with more regex here.
"""

from __future__ import annotations

import re

from dateparser.search import search_dates

from jarvis.memory import semantic
from jarvis.memory.store import MemoryStore
from jarvis.tools.filesystem import validate_path

FORGET_EVERYTHING = "__FORGET_EVERYTHING__"
MAX_INGEST_BYTES = 5_000_000
_SUPPORTED_INGEST_SUFFIXES = {".txt", ".md", ".pdf"}

_FORGET_EVERYTHING_RE = re.compile(r"^(forget everything|clear (my )?memory)[.!]?$", re.IGNORECASE)
_FORGET_DOCUMENT_RE = re.compile(r"^forget (?:the )?document (.+)$", re.IGNORECASE)
_INGEST_RE = re.compile(r"^ingest (.+)$", re.IGNORECASE)
_WHAT_INGESTED_RE = re.compile(
    r"^what (?:have you ingested|documents do you know about)\??$", re.IGNORECASE
)
_REMEMBER_RE = re.compile(r"^remember (?:that )?(.+)$", re.IGNORECASE)
_REMIND_RE = re.compile(r"^remind me to (.+)$", re.IGNORECASE)
_WHAT_REMEMBER_RE = re.compile(r"^what do you remember(?: about me)?\??$", re.IGNORECASE)
_FORGET_RE = re.compile(r"^forget (?:that )?(.+)$", re.IGNORECASE)
_RESEARCH_RE = re.compile(r"^research (.+)$", re.IGNORECASE)


def match_research(text: str) -> str | None:
    """A plain regex matcher, deliberately with no LLM/store access — unlike
    running the research agent itself (jarvis/core/orchestrator.py), which
    needs the API client and lives there instead. Keeps every command in
    this module free of API calls, so commands.py's tests never need one."""
    match = _RESEARCH_RE.match(text.strip())
    return match.group(1).strip() if match else None


def try_handle(text: str, store: MemoryStore) -> str | None:
    """Return a reply if `text` matched a memory command, else None."""
    text = text.strip()
    if not text:
        return None

    if _FORGET_EVERYTHING_RE.match(text):
        return FORGET_EVERYTHING

    # Checked before the generic _FORGET_RE below, same reason
    # FORGET_EVERYTHING is checked first — a broad regex would otherwise
    # swallow "forget document X" as a (failing) fact-forget attempt.
    if match := _FORGET_DOCUMENT_RE.match(text):
        return _handle_forget_document(match.group(1).strip())

    if match := _INGEST_RE.match(text):
        return _handle_ingest(match.group(1).strip())

    if _WHAT_INGESTED_RE.match(text):
        return _format_ingested_summary()

    if match := _REMEMBER_RE.match(text):
        fact_text = match.group(1).strip()
        store.add_fact(fact_text)
        return f"Got it — I'll remember that {fact_text}."

    if match := _REMIND_RE.match(text):
        return _handle_remind(match.group(1).strip(), store)

    if _WHAT_REMEMBER_RE.match(text):
        return _format_memory_summary(store)

    if match := _FORGET_RE.match(text):
        target = match.group(1).strip()
        removed = store.delete_facts_matching(target)
        if removed:
            listed = "; ".join(f.text for f in removed)
            return f"Forgotten: {listed}."
        return f'I didn\'t have anything stored matching "{target}".'

    return None


def _handle_ingest(raw_path: str) -> str:
    try:
        candidate = validate_path(raw_path)
    except ValueError as exc:
        return f"Can't ingest '{raw_path}': {exc}"

    if not candidate.is_file():
        return f"'{raw_path}' is not a file."

    suffix = candidate.suffix.lower()
    if suffix not in _SUPPORTED_INGEST_SUFFIXES:
        supported = ", ".join(sorted(_SUPPORTED_INGEST_SUFFIXES))
        return f"Unsupported file type '{suffix}'. Supported: {supported}"

    size = candidate.stat().st_size
    if size > MAX_INGEST_BYTES:
        return (
            f"'{raw_path}' is too large to ingest ({size} bytes, "
            f"limit {MAX_INGEST_BYTES})."
        )

    store = semantic.get_store()
    try:
        if suffix == ".pdf":
            chunk_count = store.ingest_pdf(raw_path, candidate)
        else:
            text = candidate.read_text(encoding="utf-8")
            chunk_count = store.ingest_text(raw_path, text)
    except Exception as exc:  # noqa: BLE001 — reported back to the user as-is
        return f"Couldn't ingest '{raw_path}': {exc}"

    if chunk_count == 0:
        return f"'{raw_path}' didn't have any extractable text to ingest."
    return f"Ingested '{raw_path}' — {chunk_count} chunk(s) added to the knowledge base."


def _format_ingested_summary() -> str:
    docs = semantic.get_store().list_documents()
    if not docs:
        return "I haven't ingested any documents yet."
    lines = ["Ingested documents:"]
    lines.extend(f"- {d['source']} ({d['chunks']} chunk(s))" for d in docs)
    return "\n".join(lines)


def _handle_forget_document(source: str) -> str:
    removed = semantic.get_store().forget_document(source)
    if removed:
        return f"Removed '{source}' from the knowledge base ({removed} chunk(s))."
    return f"I don't have anything ingested matching '{source}'."


def _handle_remind(task_text: str, store: MemoryStore) -> str:
    due_at = None
    due_note = ""
    try:
        found = search_dates(task_text, settings={"PREFER_DATES_FROM": "future"})
    except Exception:
        found = None

    if found:
        _, parsed = found[-1]
        due_at = parsed.isoformat()
        due_note = f" (due {parsed.strftime('%Y-%m-%d %H:%M')})"

    store.add_task(task_text, due_at=due_at)
    return f"Okay, I'll remember to {task_text}.{due_note}"


def _format_memory_summary(store: MemoryStore) -> str:
    facts = store.list_facts()
    tasks = store.list_open_tasks()

    if not facts and not tasks:
        return "I don't have anything stored about you yet."

    lines: list[str] = []
    if facts:
        lines.append("Facts:")
        lines.extend(f"- {f.text}" for f in facts)
    if tasks:
        lines.append("Open tasks:")
        for t in tasks:
            due = f" (due {t.due_at})" if t.due_at else ""
            lines.append(f"- {t.text}{due}")
    return "\n".join(lines)
