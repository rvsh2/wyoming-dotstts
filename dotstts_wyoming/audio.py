"""Audio conversion helpers."""

from __future__ import annotations

import io
import wave
from typing import Iterable

import numpy as np


def float32_to_pcm16(audio: Iterable[float]) -> bytes:
    samples = np.asarray(audio, dtype=np.float32)
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def pcm16_wav_bytes(audio: Iterable[float], sample_rate: int = 48000, channels: int = 1) -> bytes:
    pcm = float32_to_pcm16(audio)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buffer.getvalue()
