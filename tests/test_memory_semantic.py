from pathlib import Path

from jarvis.memory.semantic import KnowledgeStore

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "sample.pdf"


def make_store(tmp_path) -> KnowledgeStore:
    return KnowledgeStore(persist_path=tmp_path / "chroma")


def test_ingest_text_and_search_finds_it(tmp_path):
    store = make_store(tmp_path)

    count = store.ingest_text("notes.txt", "The secret ingredient is paprika.")

    assert count == 1
    hits = store.search("what is the secret ingredient")
    assert hits
    assert "paprika" in hits[0].text
    assert hits[0].source == "notes.txt"
    assert hits[0].page is None


def test_search_on_empty_store_returns_no_hits(tmp_path):
    store = make_store(tmp_path)

    assert store.search("anything") == []


def test_reingesting_same_source_updates_not_duplicates(tmp_path):
    store = make_store(tmp_path)

    store.ingest_text("notes.txt", "first version of the text")
    store.ingest_text("notes.txt", "second version of the text")

    docs = store.list_documents()
    assert docs == [{"source": "notes.txt", "chunks": 1}]
    hits = store.search("version")
    assert any("second version" in h.text for h in hits)
    assert not any("first version" in h.text for h in hits)


def test_ingest_pdf_preserves_page_metadata(tmp_path):
    store = make_store(tmp_path)

    count = store.ingest_pdf("sample.pdf", FIXTURE_PDF)

    assert count == 2
    hits = store.search("launch code")
    assert hits
    top = hits[0]
    assert "orange banana" in top.text
    assert top.source == "sample.pdf"
    assert top.page == 2


def test_search_tool_formats_hits_with_source_and_page(tmp_path):
    store = make_store(tmp_path)
    store.ingest_pdf("sample.pdf", FIXTURE_PDF)

    result = store.search_tool({"query": "paprika"})

    assert "sample.pdf (page 1)" in result
    assert "paprika" in result


def test_search_tool_no_results_message(tmp_path):
    store = make_store(tmp_path)

    result = store.search_tool({"query": "anything"})

    assert "No matching content" in result


def test_search_tool_rejects_empty_query(tmp_path):
    import pytest

    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="no query"):
        store.search_tool({"query": ""})


def test_list_documents_reports_chunk_counts(tmp_path):
    store = make_store(tmp_path)
    store.ingest_text("a.txt", "some short text")
    store.ingest_pdf("sample.pdf", FIXTURE_PDF)

    docs = store.list_documents()

    assert {"source": "a.txt", "chunks": 1} in docs
    assert {"source": "sample.pdf", "chunks": 2} in docs


def test_forget_document_removes_all_its_chunks(tmp_path):
    store = make_store(tmp_path)
    store.ingest_text("a.txt", "keep this one")
    store.ingest_pdf("sample.pdf", FIXTURE_PDF)

    removed = store.forget_document("sample.pdf")

    assert removed == 2
    docs = store.list_documents()
    assert docs == [{"source": "a.txt", "chunks": 1}]
    hits = store.search("launch code")
    assert not any(h.source == "sample.pdf" for h in hits)


def test_forget_document_no_match_returns_zero(tmp_path):
    store = make_store(tmp_path)

    assert store.forget_document("nonexistent.txt") == 0


def test_ingest_text_ignores_blank_content(tmp_path):
    store = make_store(tmp_path)

    count = store.ingest_text("empty.txt", "   ")

    assert count == 0
    assert store.list_documents() == []
