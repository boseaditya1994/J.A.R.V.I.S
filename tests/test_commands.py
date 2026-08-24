import pytest

from jarvis.core import commands
from jarvis.memory import semantic
from jarvis.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(db_path=tmp_path / "memory.db")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Scopes filesystem/knowledge-base tools to tmp_path for ingest tests."""
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("KNOWLEDGE_DIR", str(tmp_path / "chroma"))
    semantic.reset_store()
    yield tmp_path
    semantic.reset_store()


def test_non_matching_text_returns_none(store):
    assert commands.try_handle("what's the weather like today?", store) is None


def test_remember_that_stores_a_fact(store):
    reply = commands.try_handle("remember that my favorite language is Python", store)

    assert reply is not None
    assert "Python" in reply
    facts = store.list_facts()
    assert facts[0].text == "my favorite language is Python"


def test_remember_without_that_also_matches(store):
    commands.try_handle("remember I'm allergic to peanuts", store)

    facts = store.list_facts()
    assert facts[0].text == "I'm allergic to peanuts"


def test_remind_me_to_stores_a_task(store):
    reply = commands.try_handle("remind me to buy milk", store)

    assert "buy milk" in reply
    tasks = store.list_open_tasks()
    assert tasks[0].text == "buy milk"
    assert tasks[0].due_at is None


def test_remind_me_to_with_time_parses_due_at(store):
    reply = commands.try_handle("remind me to call Mom at 7pm", store)

    tasks = store.list_open_tasks()
    assert len(tasks) == 1
    assert "call Mom" in tasks[0].text
    assert tasks[0].due_at is not None
    assert "due" in reply.lower()


def test_what_do_you_remember_with_nothing_stored(store):
    reply = commands.try_handle("what do you remember about me?", store)

    assert "don't have anything" in reply.lower()


def test_what_do_you_remember_lists_facts_and_tasks(store):
    store.add_fact("allergic to peanuts")
    store.add_task("buy milk")

    reply = commands.try_handle("what do you remember about me", store)

    assert "allergic to peanuts" in reply
    assert "buy milk" in reply


def test_what_do_you_remember_without_about_me_also_matches(store):
    store.add_fact("allergic to peanuts")

    reply = commands.try_handle("what do you remember?", store)

    assert "allergic to peanuts" in reply


def test_forget_removes_matching_fact(store):
    store.add_fact("allergic to peanuts")

    reply = commands.try_handle("forget peanuts", store)

    assert "Forgotten" in reply
    assert store.list_facts() == []


def test_forget_no_match_reports_nothing_found(store):
    reply = commands.try_handle("forget shellfish", store)

    assert "didn't have anything" in reply.lower()


@pytest.mark.parametrize("phrase", ["forget everything", "clear my memory", "clear memory"])
def test_forget_everything_variants_return_sentinel_without_deleting(store, phrase):
    store.add_fact("allergic to peanuts")

    reply = commands.try_handle(phrase, store)

    assert reply == commands.FORGET_EVERYTHING
    # try_handle must not itself delete — the caller gates this on confirmation.
    assert store.list_facts() != []


# -- Knowledge base commands (Phase 6) --------------------------------------


def test_ingest_text_file(store, workspace):
    (workspace / "notes.txt").write_text("The meeting is on Thursday.", encoding="utf-8")

    reply = commands.try_handle("ingest notes.txt", store)

    assert "Ingested" in reply
    assert "1 chunk" in reply
    docs = semantic.get_store().list_documents()
    assert docs == [{"source": "notes.txt", "chunks": 1}]


def test_ingest_rejects_unsupported_extension(store, workspace):
    (workspace / "data.csv").write_text("a,b,c", encoding="utf-8")

    reply = commands.try_handle("ingest data.csv", store)

    assert "Unsupported file type" in reply
    assert semantic.get_store().list_documents() == []


def test_ingest_rejects_missing_file(store, workspace):
    reply = commands.try_handle("ingest nope.txt", store)

    assert "is not a file" in reply


def test_ingest_rejects_oversized_file(store, workspace, monkeypatch):
    monkeypatch.setattr(commands, "MAX_INGEST_BYTES", 10)
    (workspace / "big.txt").write_text("x" * 100, encoding="utf-8")

    reply = commands.try_handle("ingest big.txt", store)

    assert "too large" in reply
    assert semantic.get_store().list_documents() == []


def test_ingest_rejects_traversal_outside_workspace(store, workspace):
    # validate_path rejects on containment before checking existence, so the
    # target doesn't need to exist for this to be caught.
    reply = commands.try_handle("ingest ../secret.txt", store)

    assert "outside the allowed workspace" in reply


def test_ingest_rejects_env_file(store, workspace):
    (workspace / ".env").write_text("ANTHROPIC_API_KEY=secret", encoding="utf-8")

    reply = commands.try_handle("ingest .env", store)

    assert "protected file" in reply


def test_what_have_you_ingested_with_nothing(store, workspace):
    reply = commands.try_handle("what have you ingested?", store)

    assert "haven't ingested" in reply.lower()


def test_what_have_you_ingested_lists_documents(store, workspace):
    (workspace / "notes.txt").write_text("some content here", encoding="utf-8")
    commands.try_handle("ingest notes.txt", store)

    reply = commands.try_handle("what documents do you know about?", store)

    assert "notes.txt" in reply


def test_forget_document_removes_it(store, workspace):
    (workspace / "notes.txt").write_text("some content here", encoding="utf-8")
    commands.try_handle("ingest notes.txt", store)

    reply = commands.try_handle("forget document notes.txt", store)

    assert "Removed" in reply
    assert semantic.get_store().list_documents() == []


def test_forget_document_no_match(store, workspace):
    reply = commands.try_handle("forget document nonexistent.txt", store)

    assert "don't have anything ingested" in reply.lower()


def test_forget_document_checked_before_generic_forget(store, workspace):
    # A broad "forget <substring>" regex would otherwise swallow this as a
    # (failing) fact-forget attempt instead of routing to document removal —
    # the two handlers use distinctly different not-found phrasing.
    reply = commands.try_handle("forget document report.pdf", store)

    assert "don't have anything ingested" in reply.lower()
    assert "stored matching" not in reply.lower()


# -- Research agent dispatch matcher (Phase 7) ------------------------------


def test_match_research_extracts_topic():
    assert commands.match_research("research small on-device language models") == (
        "small on-device language models"
    )


def test_match_research_is_case_insensitive():
    assert commands.match_research("Research quantum computing") == "quantum computing"


def test_match_research_non_matching_text_returns_none():
    assert commands.match_research("what's the weather like today?") is None
    assert commands.match_research("remember that I like Python") is None


def test_match_research_does_not_collide_with_try_handle(store):
    # match_research is checked first by the orchestrator, before try_handle
    # — but try_handle itself should not also treat "research ..." as some
    # other command (there's no overlapping regex today; this pins that).
    assert commands.try_handle("research quantum computing", store) is None
