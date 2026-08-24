"""Loads JARVIS settings from a .env file (or the process environment)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    jarvis_name: str
    anthropic_api_key: str
    llm_model_default: str
    llm_model_complex: str
    stt_model: str
    tts_voice: str
    max_notifications_per_day: int = 10
    api_auth_token: str = ""
    vapid_private_key: str = ""
    vapid_public_key: str = ""


def load_settings(env_path: Path | None = None) -> Settings:
    """Load settings from .env (defaults to the project root) and validate.

    Raises RuntimeError if a required value (the API key) is missing, so
    failures happen at startup rather than on the first LLM call.
    """
    load_dotenv(dotenv_path=env_path or PROJECT_ROOT / ".env")

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy config/settings.example.env "
            "to .env in the project root and fill in your key."
        )

    return Settings(
        jarvis_name=os.getenv("JARVIS_NAME", "JARVIS"),
        anthropic_api_key=api_key,
        llm_model_default=os.getenv("LLM_MODEL_DEFAULT", "claude-haiku-4-5-20251001"),
        llm_model_complex=os.getenv("LLM_MODEL_COMPLEX", "claude-sonnet-5"),
        stt_model=os.getenv("STT_MODEL", "base"),
        tts_voice=os.getenv("TTS_VOICE", "en-US-GuyNeural"),
        max_notifications_per_day=int(os.getenv("MAX_NOTIFICATIONS_PER_DAY", "10")),
        api_auth_token=os.getenv("API_AUTH_TOKEN", "").strip(),
        vapid_private_key=os.getenv("VAPID_PRIVATE_KEY", "").strip(),
        vapid_public_key=os.getenv("VAPID_PUBLIC_KEY", "").strip(),
    )
