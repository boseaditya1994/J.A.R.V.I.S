"""Tests for the Phase 7 research agent (jarvis/agents/research.py) — a
read-only, web/knowledge-scoped worker built on the shared tool loop."""

from types import SimpleNamespace

from jarvis.agents import research
from jarvis.core.config import Settings
from jarvis.memory.store import MemoryStore


def make_settings() -> Settings:
    return Settings(
        jarvis_name="JARVIS",
        anthropic_api_key="sk-test",
        llm_model_default="haiku-model",
        llm_model_complex="sonnet-model",
        stt_model="base",
        tts_voice="en-US-GuyNeural",
    )


class ScriptedMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = {**kwargs, "messages": list(kwargs["messages"])}
        response = self._responses[self.call_count]
        self.call_count += 1
        return response


class FakeClient:
    def __init__(self, messages):
        self.messages = messages


def _tool_use_response(tool_name: str, tool_input: dict, tool_use_id: str = "toolu_1"):
    block = SimpleNamespace(type="tool_use", name=tool_name, input=tool_input, id=tool_use_id)
    return SimpleNamespace(content=[block], stop_reason="tool_use", container=None)


def _text_response(text: str):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block], stop_reason="end_turn", container=None)


def test_run_uses_only_the_scoped_tools(tmp_path):
    messages = ScriptedMessages([_text_response("# Report\n\nDone.")])
    client = FakeClient(messages)
    store = MemoryStore(db_path=tmp_path / "memory.db")

    research.run("some topic", client, make_settings(), store, confirm=lambda _: True)

    tool_names = {t.get("name") for t in messages.last_kwargs["tools"]}
    assert tool_names == {"knowledge_search", "web_search", "web_fetch"}
    assert "filesystem_write" not in tool_names
    assert "shell_execute" not in tool_names
    assert "calculator" not in tool_names


def test_run_uses_high_complexity(tmp_path):
    messages = ScriptedMessages([_text_response("# Report\n\nDone.")])
    client = FakeClient(messages)
    settings = make_settings()
    store = MemoryStore(db_path=tmp_path / "memory.db")

    research.run("some topic", client, settings, store, confirm=lambda _: True)

    assert messages.last_kwargs["model"] == settings.llm_model_complex


def test_run_returns_synthesized_report_after_tool_round_trip(tmp_path):
    messages = ScriptedMessages(
        [
            _tool_use_response("knowledge_search", {"query": "some topic"}),
            _text_response("# Some Topic\n\n## Summary\nSynthesized report."),
        ]
    )
    client = FakeClient(messages)
    store = MemoryStore(db_path=tmp_path / "memory.db")

    report = research.run(
        "some topic", client, make_settings(), store, confirm=lambda _: True
    )

    assert report == "# Some Topic\n\n## Summary\nSynthesized report."
    assert messages.call_count == 2


def test_run_rejects_disallowed_tool_even_if_model_requests_it(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    messages = ScriptedMessages(
        [
            _tool_use_response("filesystem_write", {"path": "x.txt", "content": "hi"}),
            _text_response("Done."),
        ]
    )
    client = FakeClient(messages)
    store = MemoryStore(db_path=tmp_path / "memory.db")

    research.run("some topic", client, make_settings(), store, confirm=lambda _: True)

    assert not (tmp_path / "x.txt").exists()
    second_call_messages = messages.last_kwargs["messages"]
    tool_result_turn = second_call_messages[-1]
    assert "Unknown tool" in tool_result_turn["content"][0]["content"]


def test_slugify_basic():
    assert research.slugify("Small On-Device Language Models!") == "small-on-device-language-models"


def test_slugify_truncates_to_60_chars():
    slug = research.slugify("x" * 100)
    assert len(slug) == 60


def test_slugify_empty_falls_back_to_topic():
    assert research.slugify("???") == "topic"
