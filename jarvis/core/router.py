"""Model routing: a provider-agnostic entrypoint for LLM calls.

Only Anthropic is wired up. `complexity` and `privacy` are accepted now so
later phases (local model fallback, multi-provider) can extend the routing
logic here without changing any call sites.

`generate()` returns the raw Message response (not extracted text) — Phase
3's tool-calling loop needs `stop_reason` and the raw content blocks to
detect and act on `tool_use`. Use `extract_text()` for the simple case.
"""

from __future__ import annotations

from typing import Literal, TypedDict

import anthropic

from jarvis.core.config import Settings

Role = Literal["user", "assistant"]


class Message(TypedDict):
    role: Role
    content: str | list


def generate(
    client: anthropic.Anthropic,
    settings: Settings,
    system: str,
    messages: list[Message],
    tools: list[dict] | None = None,
    complexity: Literal["normal", "high"] = "normal",
    privacy: Literal["normal", "sensitive"] = "normal",
    container: str | None = None,
) -> anthropic.types.Message:
    """Call the model and return its raw response.

    `privacy="sensitive"` is accepted for forward-compatibility with a local
    model route (not implemented yet — Phase 1 always calls the cloud API).

    `container` re-attaches the server-side code-execution sandbox the
    dynamic-filtering web_search/web_fetch variants (complexity="high")
    create — required on any follow-up call in the same turn/tool-loop once
    one of those tools has run, or the API rejects the request (see
    jarvis/core/tool_loop.py, which tracks and passes this through).

    `max_tokens=4096`: found live via the shopping agent
    (jarvis/agents/shopping.py) — a turn that fires off several server-side
    web_search calls piles up thinking + tool_use + tool_result content
    against this same budget before any final text gets written, and the
    old value (1024) was routinely exhausted by even a handful of
    multi-result searches, cutting the response off at stop_reason
    "max_tokens" with zero text produced. Billing is by tokens actually
    generated, not this ceiling, so raising it costs nothing on its own —
    it only avoids truncating a response that already needed the room.
    """
    model = settings.llm_model_complex if complexity == "high" else settings.llm_model_default

    kwargs = {}
    if tools:
        kwargs["tools"] = tools
    if container:
        kwargs["container"] = container

    return client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=messages,
        **kwargs,
    )


def extract_text(response: anthropic.types.Message) -> str:
    return "".join(block.text for block in response.content if block.type == "text")
