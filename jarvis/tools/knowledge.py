"""knowledge_search: LLM-callable retrieval over the user's ingested
personal knowledge base.

Ingestion itself is a deterministic command (jarvis/core/commands.py), not
a tool — explicit by design (see jarvis/memory/semantic.py). Search is the
part where the model's judgment about *when* a question needs the
knowledge base is actually useful, so it's the one piece exposed as a tool.
"""

from __future__ import annotations

from jarvis.memory import semantic
from jarvis.tools.spec import ToolSpec


def _search(tool_input: dict) -> str:
    return semantic.get_store().search_tool(tool_input)


KNOWLEDGE_SEARCH = ToolSpec(
    name="knowledge_search",
    description=(
        "Search content the user has already ingested into their personal knowledge "
        "base via the 'ingest' command. This is a semantic search over indexed text — "
        "it does NOT need or accept a file path, only a natural-language query. "
        "Try this FIRST, before filesystem_read or shell_execute, whenever the user "
        "refers to 'my document', 'my notes', 'the file I added', or asks a question "
        "that names or implies a document they may have ingested — do not try to "
        "locate or open the raw file yourself when this tool might already have the "
        "content indexed. Always cite the source filename (and page number, for PDFs) "
        "when using retrieved content."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for"}
        },
        "required": ["query"],
    },
    risk="low",
    handler=_search,
)
