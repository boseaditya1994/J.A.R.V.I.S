from types import SimpleNamespace

from jarvis.core import commands
from jarvis.core.config import Settings
from jarvis.core.orchestrator import Orchestrator
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


class FakeMessages:
    """Always returns a single canned end_turn text reply."""

    def __init__(self):
        self.call_count = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        block = SimpleNamespace(type="text", text="a canned llm reply")
        return SimpleNamespace(content=[block], stop_reason="end_turn", container=None)


class ScriptedMessages:
    """Returns pre-built responses in sequence, one per .create() call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        # Snapshot messages — it's the same list object as orchestrator's
        # self.history, which gets mutated further after this call returns.
        self.last_kwargs = {**kwargs, "messages": list(kwargs["messages"])}
        response = self._responses[self.call_count]
        self.call_count += 1
        return response


class FakeClient:
    def __init__(self, messages=None):
        self.messages = messages or FakeMessages()


def make_orchestrator(tmp_path, messages=None, confirm=None):
    store = MemoryStore(db_path=tmp_path / "memory.db")
    orchestrator = Orchestrator(make_settings(), store, confirm=confirm or (lambda _: False))
    orchestrator.client = FakeClient(messages)
    return orchestrator, store


def test_command_turn_does_not_call_the_llm(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)

    reply = orchestrator.handle_turn("remember that my favorite language is Python")

    assert orchestrator.client.messages.call_count == 0
    assert "Python" in reply
    assert store.list_facts()[0].text == "my favorite language is Python"


def test_normal_turn_calls_the_llm_and_logs_episodic(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)

    reply = orchestrator.handle_turn("hello there")

    assert orchestrator.client.messages.call_count == 1
    assert reply == "a canned llm reply"
    row = store.conn.execute(
        "SELECT user_text, assistant_text FROM episodic_log"
    ).fetchone()
    assert row == ("hello there", "a canned llm reply")


def test_system_prompt_includes_previously_stored_facts(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)
    store.add_fact("allergic to peanuts")

    orchestrator.handle_turn("what should I eat?")

    system_prompt = orchestrator.client.messages.last_kwargs["system"]
    assert "allergic to peanuts" in system_prompt


def test_system_prompt_includes_current_datetime(tmp_path):
    # Regression test for a real gap found live: asked "what's the date
    # and time now?", JARVIS could answer the date (guessed from training
    # data) but admitted it had no access to the actual time of day.
    orchestrator, _ = make_orchestrator(tmp_path)

    orchestrator.handle_turn("what time is it?")

    system_prompt = orchestrator.client.messages.last_kwargs["system"]
    assert "Current date and time:" in system_prompt


def test_system_prompt_includes_datetime_even_with_no_stored_facts(tmp_path):
    orchestrator, _ = make_orchestrator(tmp_path)

    orchestrator.handle_turn("hello")

    system_prompt = orchestrator.client.messages.last_kwargs["system"]
    assert "Current date and time:" in system_prompt


def test_system_prompt_nudges_toward_searching_named_entities(tmp_path):
    # Regression test for a real bug found live: asked "what do you know
    # about <a real restaurant>?" (or just the bare name), the model
    # answered from its own memory, found nothing, and asked the user for
    # more context (location, cuisine) instead of trying web_search first
    # — even though the same restaurant, asked about with phrasing like
    # "search about ..." or "tell me about ...", was found immediately by
    # a live web_search call with no location needed at all.
    orchestrator, _ = make_orchestrator(tmp_path)

    orchestrator.handle_turn("what do you know about some restaurant?")

    system_prompt = orchestrator.client.messages.last_kwargs["system"]
    assert "use web_search before asking them for more identifying details" in system_prompt


def test_forget_everything_bubbles_up_sentinel_without_deleting(tmp_path):
    orchestrator, store = make_orchestrator(tmp_path)
    store.add_fact("allergic to peanuts")

    reply = orchestrator.handle_turn("forget everything")

    assert reply == commands.FORGET_EVERYTHING
    assert orchestrator.client.messages.call_count == 0
    assert store.list_facts() != []


# -- Tool calling (Phase 3) ------------------------------------------------


def _tool_use_response(tool_name: str, tool_input: dict, tool_use_id: str = "toolu_1"):
    block = SimpleNamespace(type="tool_use", name=tool_name, input=tool_input, id=tool_use_id)
    return SimpleNamespace(content=[block], stop_reason="tool_use", container=None)


def _text_response(text: str):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block], stop_reason="end_turn", container=None)


def test_low_risk_tool_runs_without_confirmation(tmp_path):
    messages = ScriptedMessages(
        [
            _tool_use_response("calculator", {"expression": "2 + 2"}),
            _text_response("It's 4."),
        ]
    )
    orchestrator, store = make_orchestrator(tmp_path, messages=messages, confirm=lambda _: False)

    reply = orchestrator.handle_turn("what's 2 + 2?")

    assert reply == "It's 4."
    assert messages.call_count == 2
    # second call must carry the tool_result for the first tool_use
    second_call_messages = messages.last_kwargs["messages"]
    tool_result_turn = second_call_messages[-1]
    assert tool_result_turn["role"] == "user"
    assert tool_result_turn["content"][0]["type"] == "tool_result"
    assert tool_result_turn["content"][0]["content"] == "4"

    row = store.conn.execute(
        "SELECT tool_name, approved, result_summary FROM tool_audit_log"
    ).fetchone()
    assert row == ("calculator", 1, "4")


def test_high_risk_tool_blocked_when_confirm_denies(tmp_path, monkeypatch):
    messages = ScriptedMessages(
        [
            _tool_use_response("fake_high_risk", {}),
            _text_response("Okay, I won't do that."),
        ]
    )
    ran = []
    fake_tool = ToolSpec(
        name="fake_high_risk",
        description="test only",
        input_schema={"type": "object", "properties": {}},
        risk="high",
        handler=lambda _: ran.append(True) or "should not run",
    )
    monkeypatch.setattr(
        "jarvis.core.orchestrator.registry.find_tool",
        lambda name: fake_tool if name == "fake_high_risk" else None,
    )
    orchestrator, store = make_orchestrator(tmp_path, messages=messages, confirm=lambda _: False)

    orchestrator.handle_turn("do the risky thing")

    assert ran == []
    row = store.conn.execute(
        "SELECT tool_name, approved, result_summary FROM tool_audit_log"
    ).fetchone()
    assert row == ("fake_high_risk", 0, "declined by user")


def test_high_risk_tool_runs_when_confirm_approves(tmp_path, monkeypatch):
    ran = []
    fake_tool = ToolSpec(
        name="fake_high_risk",
        description="test only",
        input_schema={"type": "object", "properties": {}},
        risk="high",
        handler=lambda _: ran.append(True) or "ran successfully",
    )
    monkeypatch.setattr(
        "jarvis.core.orchestrator.registry.find_tool",
        lambda name: fake_tool if name == "fake_high_risk" else None,
    )
    messages = ScriptedMessages(
        [
            _tool_use_response("fake_high_risk", {}),
            _text_response("Done."),
        ]
    )
    orchestrator, store = make_orchestrator(tmp_path, messages=messages, confirm=lambda _: True)

    orchestrator.handle_turn("do the risky thing")

    assert ran == [True]
    row = store.conn.execute(
        "SELECT tool_name, approved, result_summary FROM tool_audit_log"
    ).fetchone()
    assert row == ("fake_high_risk", 1, "ran successfully")


def test_tools_includes_all_client_and_server_tools(tmp_path):
    orchestrator, _ = make_orchestrator(tmp_path)

    names = {t.get("name") for t in orchestrator._tools()}

    assert names == {
        "calculator",
        "filesystem_read",
        "filesystem_write",
        "shell_execute",
        "knowledge_search",
        "web_search",
        "web_fetch",
    }


# -- Real HIGH-risk gating with the shipped filesystem_write tool (Phase 5) --


def test_filesystem_write_declined_leaves_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    messages = ScriptedMessages(
        [
            _tool_use_response(
                "filesystem_write", {"path": "new.txt", "content": "hello"}
            ),
            _text_response("Okay, I won't write that."),
        ]
    )
    orchestrator, store = make_orchestrator(tmp_path, messages=messages, confirm=lambda _: False)

    orchestrator.handle_turn("write a file called new.txt")

    assert not (tmp_path / "new.txt").exists()
    row = store.conn.execute(
        "SELECT tool_name, risk, approved, result_summary FROM tool_audit_log"
    ).fetchone()
    assert row == ("filesystem_write", "high", 0, "declined by user")


def test_filesystem_write_approved_creates_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    messages = ScriptedMessages(
        [
            _tool_use_response(
                "filesystem_write", {"path": "new.txt", "content": "hello"}
            ),
            _text_response("Done."),
        ]
    )
    orchestrator, store = make_orchestrator(tmp_path, messages=messages, confirm=lambda _: True)

    orchestrator.handle_turn("write a file called new.txt")

    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello"
    row = store.conn.execute(
        "SELECT tool_name, risk, approved FROM tool_audit_log"
    ).fetchone()
    assert row == ("filesystem_write", "high", 1)


def test_shell_execute_disallowed_command_rejected_before_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    confirm_calls = []

    def confirm(prompt: str) -> bool:
        confirm_calls.append(prompt)
        return True  # would approve if asked — proving it was never asked

    messages = ScriptedMessages(
        [
            _tool_use_response("shell_execute", {"command": "del somefile.txt"}),
            _text_response("Can't do that."),
        ]
    )
    orchestrator, store = make_orchestrator(tmp_path, messages=messages, confirm=confirm)

    orchestrator.handle_turn("delete a file via shell")

    assert confirm_calls == []
    row = store.conn.execute(
        "SELECT tool_name, approved, result_summary FROM tool_audit_log"
    ).fetchone()
    assert row[0] == "shell_execute"
    assert row[1] == 0
    assert row[2].startswith("rejected:")


def test_confirmation_prompt_truncates_long_tool_input(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    long_content = "x" * 5000
    messages = ScriptedMessages(
        [
            _tool_use_response("filesystem_write", {"path": "big.txt", "content": long_content}),
            _text_response("Done."),
        ]
    )
    seen_prompts = []

    def confirm(prompt: str) -> bool:
        seen_prompts.append(prompt)
        return True

    orchestrator, _ = make_orchestrator(tmp_path, messages=messages, confirm=confirm)

    orchestrator.handle_turn("write a big file")

    assert len(seen_prompts) == 1
    assert len(seen_prompts[0]) < len(long_content)
    assert "chars total" in seen_prompts[0]


def test_tool_loop_stops_at_max_iterations(tmp_path):
    always_tool_use = [_tool_use_response("calculator", {"expression": "1 + 1"}) for _ in range(10)]
    messages = ScriptedMessages(always_tool_use)
    orchestrator, _ = make_orchestrator(tmp_path, messages=messages)

    reply = orchestrator.handle_turn("keep going forever")

    assert messages.call_count == 5  # MAX_TOOL_ITERATIONS
    assert "narrower request" in reply


# -- Research agent dispatch (Phase 7) --------------------------------------


def test_research_command_dispatches_to_agent_and_saves_report(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    orchestrator, store = make_orchestrator(tmp_path)

    captured = {}

    def fake_run(topic, client, settings, store_arg, confirm):
        captured["topic"] = topic
        return "# Report\n\n## Summary\nDone."

    monkeypatch.setattr("jarvis.core.orchestrator.research.run", fake_run)

    reply = orchestrator.handle_turn("research small on-device language models")

    assert captured["topic"] == "small on-device language models"
    assert orchestrator.client.messages.call_count == 0  # agent path, not the main loop
    assert "# Report" in reply
    assert "Saved to research/small-on-device-language-models.md" in reply

    saved_path = tmp_path / "research" / "small-on-device-language-models.md"
    assert saved_path.read_text(encoding="utf-8") == "# Report\n\n## Summary\nDone."

    row = store.conn.execute(
        "SELECT tool_name, risk, approved FROM tool_audit_log"
    ).fetchone()
    assert row == ("filesystem_write", "high", 1)


def test_research_command_does_not_ask_for_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    confirm_calls = []
    orchestrator, _ = make_orchestrator(
        tmp_path, confirm=lambda p: confirm_calls.append(p) or False
    )
    monkeypatch.setattr(
        "jarvis.core.orchestrator.research.run", lambda *a, **k: "a report"
    )

    orchestrator.handle_turn("research quantum computing")

    assert confirm_calls == []


# -- Shopping-compare agent dispatch -----------------------------------------


def test_find_command_dispatches_to_shopping_agent(tmp_path, monkeypatch):
    orchestrator, store = make_orchestrator(tmp_path)

    captured = {}

    def fake_run(item, client, settings, store_arg, confirm):
        captured["item"] = item
        return "# 1kg Atta\n\n## Options found\n- **Amazon** — ₹300"

    monkeypatch.setattr("jarvis.core.orchestrator.shopping.run", fake_run)

    reply = orchestrator.handle_turn("find 1kg atta")

    assert captured["item"] == "1kg atta"
    assert orchestrator.client.messages.call_count == 0  # agent path, not the main loop
    assert reply == "# 1kg Atta\n\n## Options found\n- **Amazon** — ₹300"

    row = store.conn.execute(
        "SELECT user_text, assistant_text FROM episodic_log"
    ).fetchone()
    assert row == ("find 1kg atta", reply)


def test_find_command_does_not_save_anything(tmp_path, monkeypatch):
    # Unlike research, a price comparison is never written to disk — see
    # jarvis/agents/shopping.py's module docstring.
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    orchestrator, store = make_orchestrator(tmp_path)
    monkeypatch.setattr(
        "jarvis.core.orchestrator.shopping.run", lambda *a, **k: "a comparison"
    )

    orchestrator.handle_turn("find 1kg atta")

    assert store.conn.execute("SELECT COUNT(*) FROM tool_audit_log").fetchone()[0] == 0
    assert list((tmp_path).glob("**/*.md")) == []


def test_find_command_does_not_ask_for_confirmation(tmp_path, monkeypatch):
    confirm_calls = []
    orchestrator, _ = make_orchestrator(
        tmp_path, confirm=lambda p: confirm_calls.append(p) or False
    )
    monkeypatch.setattr(
        "jarvis.core.orchestrator.shopping.run", lambda *a, **k: "a comparison"
    )

    orchestrator.handle_turn("find 1kg atta")

    assert confirm_calls == []
