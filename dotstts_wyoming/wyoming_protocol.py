"""Central re-exports of the wyoming protocol types used by this package.

The `wyoming` package is a hard dependency (see requirements.txt); importing
this module without it installed fails loudly instead of silently switching to
a divergent re-implementation.
"""

from __future__ import annotations

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event
from wyoming.info import Attribution, Describe, Info, TtsProgram, TtsVoice
from wyoming.server import AsyncEventHandler, AsyncServer
from wyoming.tts import (
    Synthesize,
    SynthesizeChunk,
    SynthesizeStart,
    SynthesizeStop,
    SynthesizeStopped,
)

__all__ = [
    "AsyncEventHandler",
    "AsyncServer",
    "Attribution",
    "AudioChunk",
    "AudioStart",
    "AudioStop",
    "Describe",
    "Error",
    "Event",
    "Info",
    "Synthesize",
    "SynthesizeChunk",
    "SynthesizeStart",
    "SynthesizeStop",
    "SynthesizeStopped",
    "TtsProgram",
    "TtsVoice",
]
