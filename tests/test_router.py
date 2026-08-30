from types import SimpleNamespace

from jarvis.core import router
from jarvis.core.config import Settings


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
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        block = SimpleNamespace(type="text", text="hello there")
        return SimpleNamespace(content=[block], stop_reason="end_turn")


class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()


def test_generate_returns_response_and_uses_default_model_for_normal_complexity():
    client = FakeClient()
    settings = make_settings()

    response = router.generate(
        client, settings, system="sys", messages=[{"role": "user", "content": "hi"}]
    )

    assert router.extract_text(response) == "hello there"
    assert client.messages.last_kwargs["model"] == "haiku-model"


def test_generate_uses_complex_model_for_high_complexity():
    client = FakeClient()
    settings = make_settings()

    router.generate(
        client,
        settings,
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        complexity="high",
    )

    assert client.messages.last_kwargs["model"] == "sonnet-model"


def test_generate_passes_tools_through_when_provided():
    client = FakeClient()
    settings = make_settings()
    tools = [{"name": "calculator"}]

    router.generate(
        client, settings, system="sys", messages=[{"role": "user", "content": "hi"}], tools=tools
    )

    assert client.messages.last_kwargs["tools"] == tools


def test_generate_omits_tools_kwarg_when_not_provided():
    client = FakeClient()
    settings = make_settings()

    router.generate(client, settings, system="sys", messages=[{"role": "user", "content": "hi"}])

    assert "tools" not in client.messages.last_kwargs


def test_generate_uses_a_high_enough_max_tokens_budget():
    # Regression test for a real bug found live via the shopping agent: a
    # turn with several server-side web_search calls piles up thinking +
    # tool_use + tool_result content against this same budget before any
    # final text gets written — the old value (1024) was routinely
    # exhausted, cutting the response off with stop_reason "max_tokens"
    # and zero text produced. Pinning a floor here, not the exact number,
    # so raising it further later doesn't require touching this test.
    client = FakeClient()
    settings = make_settings()

    router.generate(client, settings, system="sys", messages=[{"role": "user", "content": "hi"}])

    assert client.messages.last_kwargs["max_tokens"] >= 4096


def test_extract_text_concatenates_only_text_blocks():
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", name="x"),
            SimpleNamespace(type="text", text="a"),
            SimpleNamespace(type="text", text="b"),
        ]
    )

    assert router.extract_text(response) == "ab"
