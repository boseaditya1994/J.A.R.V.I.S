"""KnowledgeStore: the Phase 6 RAG layer — explicit document ingestion +
semantic search over the user's own files.

Explicit-only, same policy as structured memory (jarvis/memory/store.py):
nothing gets embedded unless the user runs `ingest <path>` themselves (see
jarvis/core/commands.py) — no automatic directory scanning, per the
project brief's warning that blind-embedding everything creates noise and
privacy exposure.

Uses Chroma's default embedding function (a small local ONNX MiniLM model,
~80MB, downloaded once on first use) — no API key, no document content
ever leaves the machine for embedding. Telemetry is explicitly disabled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings
from pypdf import PdfReader

from jarvis.core.config import PROJECT_ROOT

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
DEFAULT_TOP_K = 4


def _default_persist_path() -> Path:
    return Path(os.getenv("KNOWLEDGE_DIR", str(PROJECT_ROOT / "data" / "chroma"))).resolve()


def _chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


@dataclass(frozen=True)
class SearchHit:
    text: str
    source: str
    page: int | None


class KnowledgeStore:
    def __init__(self, persist_path: Path | None = None):
        path = persist_path or _default_persist_path()
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(path), settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection("knowledge")

    # -- Ingestion ---------------------------------------------------------

    def ingest_text(self, source: str, text: str) -> int:
        chunks = _chunk_text(text)
        if not chunks:
            return 0
        ids = [f"{source}::{i}" for i in range(len(chunks))]
        metadatas = [{"source": source, "chunk": i} for i in range(len(chunks))]
        self.collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
        return len(chunks)

    def ingest_pdf(self, source: str, path: Path) -> int:
        reader = PdfReader(str(path))
        ids: list[str] = []
        docs: list[str] = []
        metadatas: list[dict] = []
        for page_num, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            for i, chunk in enumerate(_chunk_text(page_text)):
                ids.append(f"{source}::p{page_num}::{i}")
                docs.append(chunk)
                metadatas.append({"source": source, "page": page_num, "chunk": i})
        if not docs:
            return 0
        self.collection.upsert(ids=ids, documents=docs, metadatas=metadatas)
        return len(docs)

    # -- Retrieval ---------------------------------------------------------

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchHit]:
        if self.collection.count() == 0:
            return []
        results = self.collection.query(query_texts=[query], n_results=top_k)
        docs = results.get("documents") or [[]]
        metadatas = results.get("metadatas") or [[]]
        hits = []
        for doc, meta in zip(docs[0], metadatas[0]):
            hits.append(SearchHit(text=doc, source=meta.get("source", "unknown"), page=meta.get("page")))
        return hits

    def search_tool(self, tool_input: dict) -> str:
        query = str(tool_input.get("query", "")).strip()
        if not query:
            raise ValueError("no query provided")

        hits = self.search(query)
        if not hits:
            return "No matching content found in the ingested knowledge base."

        blocks = []
        for hit in hits:
            location = hit.source if hit.page is None else f"{hit.source} (page {hit.page})"
            blocks.append(f"[{location}]\n{hit.text}")
        return "\n\n".join(blocks)

    # -- Inspection / deletion ----------------------------------------------

    def list_documents(self) -> list[dict]:
        items = self.collection.get()
        counts: dict[str, int] = {}
        for meta in items.get("metadatas", []):
            source = meta.get("source", "unknown")
            counts[source] = counts.get(source, 0) + 1
        return [{"source": s, "chunks": c} for s, c in sorted(counts.items())]

    def forget_document(self, source: str) -> int:
        matched = self.collection.get(where={"source": source})
        ids = matched.get("ids", [])
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)


_store: KnowledgeStore | None = None


def get_store() -> KnowledgeStore:
    global _store
    if _store is None:
        _store = KnowledgeStore()
    return _store


def reset_store() -> None:
    """Test-only: clear the cached singleton so the next get_store() call
    picks up a freshly-monkeypatched KNOWLEDGE_DIR."""
    global _store
    _store = None
