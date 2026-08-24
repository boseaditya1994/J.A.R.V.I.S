"""Tests for the shared tool-calling loop extracted in Phase 7
(jarvis/core/tool_loop.py) — the same behavior previously exercised only
through Orchestrator, now tested directly against the reusable module so
both Orchestrator and jarvis/agents/ can rely on it with confidence."""

from types import SimpleNamespace

from jarvis.core import tool_loop
from jarvis.core.config import Settings
from jarvis.memory.store import MemoryStore
from jarvis.tools.spec import ToolSpec


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
    """Returns pre-built responses in sequence, one per .create() call."""

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


def make_store(tmp_path) -> MemoryStore:
    return MemoryStore(db_path=tmp_path / "memory.db")


def test_tool_use_round_trip_calls_execute_and_returns_final_text(tmp_path):
    messages_api = ScriptedMessages(
        [
            _tool_use_response("calculator", {"expression": "2 + 2"}),
            _text_response("It's 4."),
        ]
    )
    client = FakeClient(messages_api)
    settings = make_settings()
    history = [{"role": "user", "content": "what's 2 + 2?"}]
    calls = []

    def execute(name, tool_input):
        calls.append((name, tool_input))
        return "4"

    reply = tool_loop.run_tool_loop(
        client=client,
        settings=settings,
        system="system prompt",
        messages=history,
        tools=[],
        execute_tool=execute,
        complexity="normal",
        max_iterations=5,
    )

    assert reply == "It's 4."
    assert calls == [("calculator", {"expression": "2 + 2"})]
    assert messages_api.call_count == 2
    tool_result_turn = history[-2]
    assert tool_result_turn["role"] == "user"
    assert tool_result_turn["content"][0]["type"] == "tool_result"
    assert tool_result_turn["content"][0]["content"] == "4"


def test_loop_forwards_container_id_to_next_call(tmp_path):
    # The dynamic-filtering web_search/web_fetch variants run inside a
    # server-side code-execution sandbox; any follow-up call in the same
    # loop must re-attach it by id or the real API rejects the request —
    # found via live testing (see jarvis/core/tool_loop.py's comment).
    first = _tool_use_response("calculator", {"expression": "1 + 1"})
    first.container = SimpleNamespace(id="container_abc123")
    messages_api = ScriptedMessages([first, _text_response("Done.")])
    client = FakeClient(messages_api)
    settings = make_settings()

    tool_loop.run_tool_loop(
        client=client,
        settings=settings,
        system="system prompt",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        execute_tool=lambda name, tool_input: "2",
        complexity="high",
        max_iterations=5,
    )

    assert messages_api.call_count == 2
    assert messages_api.last_kwargs["container"] == "container_abc123"


def test_loop_stops_at_max_iterations(tmp_path):
    always_tool_use = [_tool_use_response("calculator", {"expression": "1 + 1"}) for _ in range(10)]
    messages_api = ScriptedMessages(always_tool_use)
    client = FakeClient(messages_api)
    settings = make_settings()

    reply = tool_loop.run_tool_loop(
        client=client,
        settings=settings,
        system="system prompt",
        messages=[{"role": "user", "content": "keep going forever"}],
        tools=[],
        execute_tool=lambda name, tool_input: "2",
        complexity="normal",
        max_iterations=3,
    )

    assert messages_api.call_count == 3
    assert "narrower request" in reply


def test_execute_tool_unknown_tool_returns_message_without_running_anything(tmp_path):
    store = make_store(tmp_path)

    result = tool_loop.execute_tool(
        "nonexistent",
        {},
        find_tool=lambda name: None,
        confirm=lambda _: True,
        store=store,
    )

    assert result == "Unknown tool: nonexistent"


def test_execute_tool_validate_rejection_happens_before_confirmation(tmp_path):
    store = make_store(tmp_path)
    confirm_calls = []

    def confirm(prompt: str) -> bool:
        confirm_calls.append(prompt)
        return True  # would approve if asked — proving it was never asked

    def validate(tool_input):
        raise ValueError("bad input")

    fake_tool = ToolSpec(
        name="fake",
        description="test only",
        input_schema={"type": "object", "properties": {}},
        risk="high",
        handler=lambda _: "should not run",
        validate=validate,
    )

    result = tool_loop.execute_tool(
        "fake",
        {},
        find_tool=lambda name: fake_tool if name == "fake" else None,
        confirm=confirm,
        store=store,
    )

    assert confirm_calls == []
    assert result.startswith("This tool call was rejected before execution:")
    row = store.conn.execute(
        "SELECT tool_name, approved, result_summary FROM tool_audit_log"
    ).fetchone()
    assert row[0] == "fake"
    assert row[1] == 0
    assert row[2].startswith("rejected:")


def test_execute_tool_low_risk_runs_without_confirmation(tmp_path):
    store = make_store(tmp_path)
    confirm_calls = []
    fake_tool = ToolSpec(
        name="fake_low",
        description="test only",
        input_schema={"type": "object", "properties": {}},
        risk="low",
        handler=lambda _: "ran",
    )

    result = tool_loop.execute_tool(
        "fake_low",
        {},
        find_tool=lambda name: fake_tool if name == "fake_low" else None,
        confirm=lambda p: confirm_calls.append(p) or True,
        store=store,
    )

    assert result == "ran"
    assert confirm_calls == []
    row = store.conn.execute(
        "SELECT tool_name, approved, result_summary FROM tool_audit_log"
    ).fetchone()
    assert row == ("fake_low", 1, "ran")


def test_execute_tool_high_risk_declined(tmp_path):
    store = make_store(tmp_path)
    ran = []
    fake_tool = ToolSpec(
        name="fake_high",
        description="test only",
        input_schema={"type": "object", "properties": {}},
        risk="high",
        handler=lambda _: ran.append(True) or "should not run",
    )

    result = tool_loop.execute_tool(
        "fake_high",
        {},
        find_tool=lambda name: fake_tool if name == "fake_high" else None,
        confirm=lambda _: False,
        store=store,
    )

    assert ran == []
    assert result == "The user declined to allow this tool call."
    row = store.conn.execute(
        "SELECT tool_name, approved, result_summary FROM tool_audit_log"
    ).fetchone()
    assert row == ("fake_high", 0, "declined by user")


def test_execute_tool_high_risk_approved(tmp_path):
    store = make_store(tmp_path)
    ran = []
    fake_tool = ToolSpec(
        name="fake_high",
        description="test only",
        input_schema={"type": "object", "properties": {}},
        risk="high",
        handler=lambda _: ran.append(True) or "ran successfully",
    )

    result = tool_loop.execute_tool(
        "fake_high",
        {},
        find_tool=lambda name: fake_tool if name == "fake_high" else None,
        confirm=lambda _: True,
        store=store,
    )

    assert ran == [True]
    assert result == "ran successfully"
    row = store.conn.execute(
        "SELECT tool_name, approved, result_summary FROM tool_audit_log"
    ).fetchone()
    assert row == ("fake_high", 1, "ran successfully")


def test_execute_tool_confirmation_prompt_uses_agent_name(tmp_path):
    store = make_store(tmp_path)
    prompts = []
    fake_tool = ToolSpec(
        name="fake_high",
        description="test only",
        input_schema={"type": "object", "properties": {}},
        risk="high",
        handler=lambda _: "ran",
    )

    def confirm(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    tool_loop.execute_tool(
        "fake_high",
        {},
        find_tool=lambda name: fake_tool if name == "fake_high" else None,
        confirm=confirm,
        store=store,
        agent_name="JARVIS's research agent",
    )

    assert prompts[0].startswith("JARVIS's research agent wants to run 'fake_high'")


def test_execute_tool_truncates_long_input_in_confirmation_prompt(tmp_path):
    store = make_store(tmp_path)
    long_content = "x" * 5000
    prompts = []
    fake_tool = ToolSpec(
        name="fake_high",
        description="test only",
        input_schema={"type": "object", "properties": {}},
        risk="high",
        handler=lambda _: "ran",
    )

    def confirm(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    tool_loop.execute_tool(
        "fake_high",
        {"content": long_content},
        find_tool=lambda name: fake_tool if name == "fake_high" else None,
        confirm=confirm,
        store=store,
    )

    assert len(prompts[0]) < len(long_content)
    assert "chars total" in prompts[0]


def test_execute_tool_handler_error_is_logged_and_reported(tmp_path):
    store = make_store(tmp_path)

    def raising_handler(_):
        raise RuntimeError("boom")

    fake_tool = ToolSpec(
        name="fake_low",
        description="test only",
        input_schema={"type": "object", "properties": {}},
        risk="low",
        handler=raising_handler,
    )

    result = tool_loop.execute_tool(
        "fake_low",
        {},
        find_tool=lambda name: fake_tool if name == "fake_low" else None,
        confirm=lambda _: True,
        store=store,
    )

    assert result == "Tool error: boom"
    row = store.conn.execute(
        "SELECT tool_name, approved, result_summary FROM tool_audit_log"
    ).fetchone()
    assert row == ("fake_low", 1, "error: boom")


def test_format_input_for_confirmation_truncates_long_values():
    formatted = tool_loop.format_input_for_confirmation({"content": "x" * 500}, max_len=200)

    assert len(formatted["content"]) < 500
    assert "chars total" in formatted["content"]


def test_format_input_for_confirmation_leaves_short_values_untouched():
    formatted = tool_loop.format_input_for_confirmation({"path": "new.txt"})

    assert formatted == {"path": "new.txt"}
