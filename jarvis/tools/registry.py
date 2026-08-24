"""The tool registry: aggregates every client-side tool and the two
Anthropic-hosted server-side tool declarations.

Client-side tools (calculator, filesystem_read/write, shell_execute,
knowledge_search) are ToolSpecs with a risk level and a handler that runs
locally — see jarvis/tools/spec.py, filesystem.py, shell.py, knowledge.py.
Server-side tools (web_search, web_fetch) have no handler here — Anthropic
executes them and the result appears inline in the same response.
"""

from __future__ import annotations

import ast
import operator

from jarvis.tools.filesystem import FILESYSTEM_READ, FILESYSTEM_WRITE
from jarvis.tools.knowledge import KNOWLEDGE_SEARCH
from jarvis.tools.shell import SHELL_EXECUTE
from jarvis.tools.spec import ToolSpec

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("only numbers are allowed")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and (abs(left) > 10_000 or abs(right) > 1_000):
            raise ValueError("exponent too large")
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"unsupported expression syntax: {ast.dump(node)}")


def _calculate(tool_input: dict) -> str:
    expression = str(tool_input.get("expression", "")).strip()
    if not expression:
        raise ValueError("no expression provided")
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree)
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError) as exc:
        raise ValueError(f"couldn't evaluate '{expression}': {exc}") from exc
    return str(result)


CALCULATOR = ToolSpec(
    name="calculator",
    description=(
        "Evaluate a basic arithmetic expression (+, -, *, /, **, parentheses). "
        "Use this for any numeric computation instead of doing the math yourself."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "e.g. '47 * 812 + 19'"}
        },
        "required": ["expression"],
    },
    risk="low",
    handler=_calculate,
)


def client_tools() -> list[ToolSpec]:
    return [CALCULATOR, FILESYSTEM_READ, FILESYSTEM_WRITE, SHELL_EXECUTE, KNOWLEDGE_SEARCH]


def to_api_schema(spec: ToolSpec) -> dict:
    return {"name": spec.name, "description": spec.description, "input_schema": spec.input_schema}


def find_tool(name: str) -> ToolSpec | None:
    for spec in client_tools():
        if spec.name == name:
            return spec
    return None


def web_search_tool_dict(complexity: str) -> dict:
    """Anthropic-hosted web search — no client handler, no API key needed.

    The dynamic-filtering variant (web_search_20260209) requires a
    Sonnet-5/Opus-tier model; Haiku-tier (today's default complexity) uses
    the basic variant instead.
    """
    if complexity == "high":
        return {"type": "web_search_20260209", "name": "web_search"}
    return {"type": "web_search_20250305", "name": "web_search"}


def web_fetch_tool_dict(complexity: str) -> dict:
    """Anthropic-hosted web fetch — no client handler, no API key needed.

    Only fetches URLs already present in the conversation (Anthropic's own
    constraint) — the model can't point it at an arbitrary URL it invents.
    Citations are enabled so retrieved content carries source attribution,
    per the project's Phase 4 requirement to distinguish known vs.
    freshly-retrieved information.
    """
    if complexity == "high":
        return {"type": "web_fetch_20260209", "name": "web_fetch", "citations": {"enabled": True}}
    return {"type": "web_fetch_20250910", "name": "web_fetch", "citations": {"enabled": True}}
