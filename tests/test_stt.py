"""Smoke test for local transcription — no mic, no network, just the model."""

from pathlib import Path

import soundfile as sf

from jarvis.voice import stt

FIXTURE = Path(__file__).parent / "fixtures" / "sample_speech.wav"


def test_transcribe_returns_expected_words():
    audio, sample_rate = sf.read(FIXTURE, dtype="float32")
    assert sample_rate == stt.SAMPLE_RATE

    text = stt.transcribe(audio, model_size="base").lower()

    assert "fox" in text
    assert "dog" in text


def test_transcribe_empty_audio_returns_empty_string():
    import numpy as np

    assert stt.transcribe(np.zeros((0,), dtype="float32")) == ""
