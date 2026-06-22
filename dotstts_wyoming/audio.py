"""Audio conversion helpers."""

from __future__ import annotations

import io
import wave
from array import array
from typing import Iterable


def float32_to_pcm16(audio: Iterable[float]) -> bytes:
    pcm = array("h")
    for sample in audio:
        clipped = max(-1.0, min(1.0, float(sample)))
        pcm.append(int(clipped * 32767.0))
    return pcm.tobytes()


def pcm16_wav_bytes(audio: Iterable[float], sample_rate: int = 48000, channels: int = 1) -> bytes:
    pcm = float32_to_pcm16(audio)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buffer.getvalue()
