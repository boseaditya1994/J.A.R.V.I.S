import pytest

from jarvis.core.config import load_settings

ENV_KEYS = [
    "JARVIS_NAME",
    "ANTHROPIC_API_KEY",
    "LLM_MODEL_DEFAULT",
    "LLM_MODEL_COMPLEX",
    "STT_MODEL",
    "TTS_VOICE",
    "MAX_NOTIFICATIONS_PER_DAY",
    "API_AUTH_TOKEN",
    "VAPID_PRIVATE_KEY",
    "VAPID_PUBLIC_KEY",
    "MORNING_BRIEF_HOUR",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_missing_api_key_raises(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("JARVIS_NAME=Friday\n")

    with pytest.raises(RuntimeError):
        load_settings(env_path=env_file)


def test_loads_values_and_applies_defaults(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "JARVIS_NAME=Friday\n"
        "ANTHROPIC_API_KEY=sk-test-123\n"
    )

    settings = load_settings(env_path=env_file)

    assert settings.jarvis_name == "Friday"
    assert settings.anthropic_api_key == "sk-test-123"
    assert settings.llm_model_default == "claude-haiku-4-5-20251001"
    assert settings.llm_model_complex == "claude-sonnet-5"
    assert settings.stt_model == "base"
    assert settings.tts_voice == "en-US-GuyNeural"
    assert settings.max_notifications_per_day == 10
    assert settings.morning_brief_hour == 7


def test_max_notifications_per_day_override(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ANTHROPIC_API_KEY=sk-test-123\n"
        "MAX_NOTIFICATIONS_PER_DAY=3\n"
    )

    settings = load_settings(env_path=env_file)

    assert settings.max_notifications_per_day == 3


def test_morning_brief_hour_override(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ANTHROPIC_API_KEY=sk-test-123\n"
        "MORNING_BRIEF_HOUR=9\n"
    )

    settings = load_settings(env_path=env_file)

    assert settings.morning_brief_hour == 9
