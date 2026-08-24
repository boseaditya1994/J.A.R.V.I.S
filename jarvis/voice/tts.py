"""Text-to-speech: edge-tts synthesis, ffmpeg conversion, stdlib playback.

edge-tts outputs mp3; winsound (Windows stdlib) only plays wav, so we
convert with ffmpeg — already a hard dependency for STT audio decoding, so
this adds no new runtime dependency.
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import winsound
from pathlib import Path

import edge_tts


async def _synthesize(text: str, voice: str, mp3_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(mp3_path))


def speak(text: str, voice: str) -> None:
    if not text.strip():
        return

    with tempfile.TemporaryDirectory(prefix="jarvis_tts_") as tmp_dir:
        mp3_path = Path(tmp_dir) / "speech.mp3"
        wav_path = Path(tmp_dir) / "speech.wav"

        asyncio.run(_synthesize(text, voice, mp3_path))

        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3_path), str(wav_path)],
            check=True,
        )

        winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)
