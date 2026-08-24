import pytest

from jarvis.memory import semantic
from jarvis.tools.knowledge import KNOWLEDGE_SEARCH


@pytest.fixture(autouse=True)
def isolated_knowledge_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_DIR", str(tmp_path / "chroma"))
    semantic.reset_store()
    yield
    semantic.reset_store()


def test_knowledge_search_tool_spec_shape():
    assert KNOWLEDGE_SEARCH.name == "knowledge_search"
    assert KNOWLEDGE_SEARCH.risk == "low"
    assert KNOWLEDGE_SEARCH.validate is None


def test_knowledge_search_handler_finds_ingested_content():
    semantic.get_store().ingest_text("notes.txt", "The meeting is on Thursday at 3pm.")

    result = KNOWLEDGE_SEARCH.handler({"query": "when is the meeting"})

    assert "notes.txt" in result
    assert "Thursday" in result


def test_knowledge_search_handler_no_results():
    result = KNOWLEDGE_SEARCH.handler({"query": "anything"})

    assert "No matching content" in result


def test_knowledge_search_handler_rejects_empty_query():
    with pytest.raises(ValueError):
        KNOWLEDGE_SEARCH.handler({"query": ""})
