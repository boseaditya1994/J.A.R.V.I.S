"""Filesystem tools: read (Phase 3) and write (Phase 5), both scoped to a
single workspace root with a sensitive-file denylist.

The denylist applies to read as well as write. filesystem_read is LOW risk
(auto-approved, no human review) — without a denylist, a prompt injection
from fetched web content (the risk Phase 4 flagged) could trick JARVIS into
reading .env and echoing the API key back into its own response.
"""

from __future__ import annotations

import os
from pathlib import Path

from jarvis.core.config import PROJECT_ROOT
from jarvis.tools.spec import ToolSpec

MAX_READ_BYTES = 100_000
MAX_WRITE_BYTES = 100_000

_DENYLISTED_NAMES = {".env"}
_DENYLISTED_SUFFIXES = {".pem", ".key"}


def workspace_root() -> Path:
    return Path(os.getenv("TOOLS_WORKSPACE_DIR", str(PROJECT_ROOT))).resolve()


def validate_path(raw_path: str) -> Path:
    if not raw_path:
        raise ValueError("no path provided")

    root = workspace_root()
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"'{raw_path}' is outside the allowed workspace ({root})") from exc

    if ".git" in candidate.parts:
        raise ValueError(f"'{raw_path}' is inside .git — not accessible to tools")
    if candidate.name in _DENYLISTED_NAMES or candidate.suffix in _DENYLISTED_SUFFIXES:
        raise ValueError(f"'{raw_path}' is a protected file and cannot be accessed by tools")

    return candidate


def _read_file(tool_input: dict) -> str:
    raw_path = str(tool_input.get("path", "")).strip()
    candidate = validate_path(raw_path)

    if not candidate.is_file():
        raise ValueError(f"'{raw_path}' is not a file")

    data = candidate.read_bytes()
    if len(data) > MAX_READ_BYTES:
        raise ValueError(
            f"'{raw_path}' is too large to read ({len(data)} bytes, limit {MAX_READ_BYTES})"
        )
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"'{raw_path}' is not a text file") from exc


def _write_file(tool_input: dict) -> str:
    raw_path = str(tool_input.get("path", "")).strip()
    content = tool_input.get("content", "")
    if not isinstance(content, str):
        raise ValueError("content must be a string")

    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise ValueError(
            f"content is too large to write ({len(encoded)} bytes, limit {MAX_WRITE_BYTES})"
        )

    candidate = validate_path(raw_path)
    existed = candidate.exists()
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(content, encoding="utf-8")

    verb = "Overwrote" if existed else "Created"
    return f"{verb} '{raw_path}' ({len(content)} characters)."


FILESYSTEM_READ = ToolSpec(
    name="filesystem_read",
    description=(
        "Read the text contents of a file inside the JARVIS project workspace. "
        "Cannot read files outside the workspace or protected files (.env, .git, "
        "keys/certs)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace root"}
        },
        "required": ["path"],
    },
    risk="low",
    handler=_read_file,
)

FILESYSTEM_WRITE = ToolSpec(
    name="filesystem_write",
    description=(
        "Create or overwrite a text file inside the JARVIS project workspace. "
        "Cannot write outside the workspace or to protected files (.env, .git, "
        "keys/certs). Always requires the user's explicit confirmation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace root"},
            "content": {"type": "string", "description": "Full text content to write"},
        },
        "required": ["path", "content"],
    },
    risk="high",
    handler=_write_file,
)
