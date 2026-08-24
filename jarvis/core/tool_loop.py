"""The shared request/response tool-calling loop and per-call gating.

Extracted in Phase 7 from what was originally Orchestrator.handle_turn /
_execute_tool (Phase 3). An "agent" (jarvis/agents/) is fundamentally the
same loop run with a different system prompt and a *restricted* tool
subset — not a new execution paradigm. Parameterizing `find_tool` is the
"controlled interface" the project brief asks agents to use rather than
sharing unrestricted access: the main Orchestrator binds it to
registry.find_tool (every client tool); an agent binds it to a lookup over
only the tools it's allowed to touch.
"""

from __future__ import annotations

from typing import Callable

import anthropic

from jarvis.core import permissions, router
from jarvis.memory.store import MemoryStore
from jarvis.tools.spec import ToolSpec

FindTool = Callable[[str], ToolSpec | None]
Confirm = Callable[[str], bool]


def run_tool_loop(
    client: anthropic.Anthropic,
    settings,
    system: str,
    messages: list[router.Message],
    tools: list[dict],
    execute_tool: Callable[[str, dict], str],
    complexity: str = "normal",
    max_iterations: int = 5,
) -> str:
    """Run the capped tool-calling loop, mutating `messages` in place.

    `execute_tool(name, tool_input) -> str` is the caller's tool dispatch —
    see `execute_tool` below for the standard validate/confirm/audit-log
    implementation both Orchestrator and agents use.
    """
    response = None
    container_id = None
    for _ in range(max_iterations):
        response = router.generate(
            client=client,
            settings=settings,
            system=system,
            messages=messages,
            tools=tools,
            complexity=complexity,
            container=container_id,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.container is not None:
            # The dynamic-filtering web_search/web_fetch variants (complexity
            # "high") run inside a server-side code-execution sandbox; any
            # follow-up call in this same loop must re-attach it by id or the
            # API rejects the request with "container_id is required" (found
            # via live testing of the Phase 7 research agent — a client tool
            # like knowledge_search forcing a second round after one of these
            # tools ran was enough to trigger it).
            container_id = response.container.id

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result_text = execute_tool(block.name, block.input)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result_text}
            )
        messages.append({"role": "user", "content": tool_results})

    reply = router.extract_text(response) if response else ""
    if not reply:
        reply = (
            "I wasn't able to finish that after several tool calls — "
            "let me know if you'd like me to try a narrower request."
        )
    return reply


def execute_tool(
    name: str,
    tool_input: dict,
    find_tool: FindTool,
    confirm: Confirm,
    store: MemoryStore,
    agent_name: str = "JARVIS",
) -> str:
    """Validate (hard boundary) -> confirm (risk-gated) -> run -> audit-log.

    `find_tool` scopes which tools are reachable at all — an agent that
    doesn't pass a name through its own `find_tool` gets "Unknown tool"
    regardless of what's in the global registry.
    """
    spec = find_tool(name)
    if spec is None:
        return f"Unknown tool: {name}"

    if spec.validate is not None:
        try:
            spec.validate(tool_input)
        except Exception as exc:  # noqa: BLE001 — surfaced to the model as a rejection
            store.log_tool_call(name, tool_input, spec.risk, False, f"rejected: {exc}")
            return f"This tool call was rejected before execution: {exc}"

    approved = True
    if permissions.needs_confirmation(spec.risk):
        readable_input = format_input_for_confirmation(tool_input)
        prompt = (
            f"{agent_name} wants to run '{name}' (risk: {spec.risk}) "
            f"with input {readable_input}."
        )
        approved = confirm(prompt)
        if not approved:
            store.log_tool_call(name, tool_input, spec.risk, False, "declined by user")
            return "The user declined to allow this tool call."

    try:
        result = spec.handler(tool_input)
    except Exception as exc:  # noqa: BLE001 — surfaced to the model as a tool error
        store.log_tool_call(name, tool_input, spec.risk, approved, f"error: {exc}")
        return f"Tool error: {exc}"

    store.log_tool_call(name, tool_input, spec.risk, approved, result[:200])
    return result


def format_input_for_confirmation(tool_input: dict, max_len: int = 200) -> dict:
    """Truncate long values (e.g. file content) so the confirmation prompt
    shown to the user stays readable instead of dumping up to 100KB."""
    formatted = {}
    for key, value in tool_input.items():
        text = str(value)
        if len(text) > max_len:
            text = f"{text[:max_len]}... ({len(text)} chars total)"
        formatted[key] = text
    return formatted
