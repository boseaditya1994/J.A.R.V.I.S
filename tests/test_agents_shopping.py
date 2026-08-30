"""Tests for the shopping-compare agent (jarvis/agents/shopping.py) — a
read-only, web-scoped worker built on the shared tool loop, parallel to
the Phase 7 research agent."""

from types import SimpleNamespace

from jarvis.agents import shopping
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


def test_run_uses_only_web_search_and_web_fetch(tmp_path):
    messages = ScriptedMessages([_text_response("# Item\n\n## Options found\nDone.")])
    client = FakeClient(messages)
    store = MemoryStore(db_path=tmp_path / "memory.db")

    shopping.run("1kg atta", client, make_settings(), store, confirm=lambda _: True)

    tool_names = {t.get("name") for t in messages.last_kwargs["tools"]}
    assert tool_names == {"web_search", "web_fetch"}
    assert "knowledge_search" not in tool_names
    assert "filesystem_write" not in tool_names
    assert "shell_execute" not in tool_names
    assert "calculator" not in tool_names


def test_run_system_prompt_includes_current_datetime(tmp_path):
    messages = ScriptedMessages([_text_response("# Item\n\nDone.")])
    client = FakeClient(messages)
    store = MemoryStore(db_path=tmp_path / "memory.db")

    shopping.run("1kg atta", client, make_settings(), store, confirm=lambda _: True)

    assert "Current date and time:" in messages.last_kwargs["system"]


def test_run_mentions_the_named_shopping_sites_in_the_system_prompt(tmp_path):
    messages = ScriptedMessages([_text_response("# Item\n\nDone.")])
    client = FakeClient(messages)
    store = MemoryStore(db_path=tmp_path / "memory.db")

    shopping.run("1kg atta", client, make_settings(), store, confirm=lambda _: True)

    system_prompt = messages.last_kwargs["system"]
    for site in ("Amazon", "Flipkart", "Zepto", "Blinkit", "Myntra"):
        assert site in system_prompt


def test_run_uses_high_complexity(tmp_path):
    messages = ScriptedMessages([_text_response("# Item\n\nDone.")])
    client = FakeClient(messages)
    settings = make_settings()
    store = MemoryStore(db_path=tmp_path / "memory.db")

    shopping.run("1kg atta", client, settings, store, confirm=lambda _: True)

    assert messages.last_kwargs["model"] == settings.llm_model_complex


def test_run_returns_synthesized_comparison_after_tool_round_trip(tmp_path):
    messages = ScriptedMessages(
        [
            _tool_use_response("web_search", {"query": "1kg atta price"}),
            _text_response("# 1kg Atta\n\n## Options found\n- **Amazon** — ₹300"),
        ]
    )
    client = FakeClient(messages)
    store = MemoryStore(db_path=tmp_path / "memory.db")

    reply = shopping.run("1kg atta", client, make_settings(), store, confirm=lambda _: True)

    assert reply == "# 1kg Atta\n\n## Options found\n- **Amazon** — ₹300"
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

    shopping.run("1kg atta", client, make_settings(), store, confirm=lambda _: True)

    assert not (tmp_path / "x.txt").exists()
    second_call_messages = messages.last_kwargs["messages"]
    tool_result_turn = second_call_messages[-1]
    assert "Unknown tool" in tool_result_turn["content"][0]["content"]
