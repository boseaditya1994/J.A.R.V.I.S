"""Speech-to-text: push-to-talk mic capture + local faster-whisper transcription."""

from __future__ import annotations

import queue

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000

_model_cache: dict[str, WhisperModel] = {}


def record_until_enter() -> np.ndarray:
    """Record mono float32 audio from the default mic until Enter is pressed."""
    print("Recording... press Enter to stop.")
    chunks: queue.Queue[np.ndarray] = queue.Queue()

    def callback(indata, frame_count, time_info, status):  # noqa: ANN001
        chunks.put(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback):
        input()

    if chunks.empty():
        return np.zeros((0,), dtype="float32")

    frames = []
    while not chunks.empty():
        frames.append(chunks.get())
    return np.concatenate(frames, axis=0).flatten()


def _get_model(model_size: str) -> WhisperModel:
    if model_size not in _model_cache:
        _model_cache[model_size] = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _model_cache[model_size]


def transcribe(audio: np.ndarray, model_size: str = "base") -> str:
    if audio.size == 0:
        return ""
    model = _get_model(model_size)
    segments, _ = model.transcribe(audio, language="en")
    return " ".join(segment.text.strip() for segment in segments).strip()
