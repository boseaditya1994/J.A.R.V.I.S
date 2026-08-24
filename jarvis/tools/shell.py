"""shell_execute: an allowlisted, non-shell command runner.

The allowlist is a hard boundary, separate from and enforced BEFORE the
CRITICAL risk tier's confirmation gate — an executable not on the list (or
a command with forbidden syntax) is rejected via ToolSpec.validate, which
the orchestrator calls before ever asking the user to confirm anything. A
command that was never going to run shouldn't cost the user a decision.
Commands run via subprocess with shell=False (an argument list handed
straight to the named executable, no shell interpretation at all) inside
the same workspace root filesystem tools use.

Deliberately excludes cmd.exe built-ins (dir, echo, type, ...) — those only
work inside a shell interpreter and would force shell=True, reopening the
injection surface this design avoids.
"""

from __future__ import annotations

import shlex
import subprocess

from jarvis.tools.filesystem import workspace_root
from jarvis.tools.spec import ToolSpec

ALLOWED_COMMANDS = {"git", "python", "node", "npm", "uv", "where"}
FORBIDDEN_CHARS = set("&|;`<>$\n")
TIMEOUT_SECONDS = 20
MAX_OUTPUT_CHARS = 4000


def _parse_and_validate(tool_input: dict) -> list[str]:
    """Parse the command and enforce the allowlist. Raises ValueError.

    Called twice on an approved call (once by the orchestrator pre-check,
    once here from _run_command) — validation is cheap and side-effect
    free, so re-running it is simpler than threading parsed state through
    the orchestrator, which only ever hands tools a plain input dict.
    """
    command = str(tool_input.get("command", "")).strip()
    if not command:
        raise ValueError("no command provided")
    if any(ch in command for ch in FORBIDDEN_CHARS):
        raise ValueError(
            "command contains forbidden shell operators/characters "
            f"({''.join(sorted(FORBIDDEN_CHARS))})"
        )

    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        raise ValueError(f"couldn't parse command: {exc}") from exc
    if not parts:
        raise ValueError("no command provided")

    executable = parts[0].strip('"').lower()
    if executable not in ALLOWED_COMMANDS:
        raise ValueError(
            f"'{parts[0]}' is not an allowed command. Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}"
        )

    return parts


def _run_command(tool_input: dict) -> str:
    parts = _parse_and_validate(tool_input)

    try:
        result = subprocess.run(
            parts,
            cwd=workspace_root(),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"command timed out after {TIMEOUT_SECONDS}s") from exc
    except FileNotFoundError as exc:
        raise ValueError(f"command not found: {exc}") from exc

    output = ((result.stdout or "") + (result.stderr or "")).strip() or "(no output)"
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
    return f"exit code {result.returncode}\n{output}"


def _validate(tool_input: dict) -> None:
    _parse_and_validate(tool_input)


SHELL_EXECUTE = ToolSpec(
    name="shell_execute",
    description=(
        "Run a command-line tool inside the JARVIS project workspace. Only "
        f"these executables are allowed: {', '.join(sorted(ALLOWED_COMMANDS))}. "
        "No shell operators (pipes, redirects, chaining) are supported. "
        "Always requires the user's explicit confirmation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "e.g. 'git status' or 'python --version'",
            }
        },
        "required": ["command"],
    },
    risk="critical",
    handler=_run_command,
    validate=_validate,
)
