"""Wyoming protocol imports with test-friendly fallbacks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


try:
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

    WYOMING_AVAILABLE = True
except ImportError:  # pragma: no cover
    WYOMING_AVAILABLE = False

    @dataclass
    class Event:
        type: str
        data: dict[str, Any] = field(default_factory=dict)

    class AsyncEventHandler:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def write_event(self, event: Event) -> None:
            raise NotImplementedError

    class AsyncServer:
        @classmethod
        def from_uri(cls, uri: str):
            raise RuntimeError("The 'wyoming' package is not installed.")

        async def run(self, factory) -> None:
            raise RuntimeError("The 'wyoming' package is not installed.")

    @dataclass
    class Attribution:
        name: Optional[str] = None
        url: Optional[str] = None

    @dataclass
    class TtsVoice:
        name: str
        description: str = ""
        attribution: Optional[Attribution] = None
        installed: bool = True
        version: Optional[str] = None
        languages: list[str] = field(default_factory=list)

    @dataclass
    class TtsProgram:
        name: str
        description: str = ""
        attribution: Optional[Attribution] = None
        installed: bool = True
        version: Optional[str] = None
        voices: list[TtsVoice] = field(default_factory=list)
        supports_synthesize_streaming: bool = False

    @dataclass
    class Info:
        tts: list[TtsProgram] = field(default_factory=list)

        def event(self) -> Event:
            return Event("describe", {"tts": self.tts})

    class Describe:
        @staticmethod
        def is_type(event_type: str) -> bool:
            return event_type == "describe"

    @dataclass
    class _VoiceRef:
        name: Optional[str] = None
        speaker: Optional[str] = None

    @dataclass
    class Synthesize:
        text: str
        voice: Optional[_VoiceRef] = None
        context: Optional[dict[str, Any]] = None

        @staticmethod
        def is_type(event_type: str) -> bool:
            return event_type == "synthesize"

        @classmethod
        def from_event(cls, event: Event) -> "Synthesize":
            voice = event.data.get("voice")
            return cls(
                text=event.data.get("text", ""),
                voice=_VoiceRef(**voice) if isinstance(voice, dict) else voice,
                context=event.data.get("context"),
            )

    @dataclass
    class SynthesizeStart:
        voice: Optional[_VoiceRef] = None
        context: Optional[dict[str, Any]] = None

        @staticmethod
        def is_type(event_type: str) -> bool:
            return event_type == "synthesize-start"

        @classmethod
        def from_event(cls, event: Event) -> "SynthesizeStart":
            voice = event.data.get("voice")
            return cls(
                voice=_VoiceRef(**voice) if isinstance(voice, dict) else voice,
                context=event.data.get("context"),
            )

    @dataclass
    class SynthesizeChunk:
        text: str

        @staticmethod
        def is_type(event_type: str) -> bool:
            return event_type == "synthesize-chunk"

        @classmethod
        def from_event(cls, event: Event) -> "SynthesizeChunk":
            return cls(text=event.data.get("text", ""))

    @dataclass
    class SynthesizeStop:
        @staticmethod
        def is_type(event_type: str) -> bool:
            return event_type == "synthesize-stop"

    @dataclass
    class SynthesizeStopped:
        def event(self) -> Event:
            return Event("synthesize-stopped", {})

    @dataclass
    class AudioStart:
        rate: int = 48000
        width: int = 2
        channels: int = 1

        def event(self) -> Event:
            return Event("audio-start", {"rate": self.rate, "width": self.width, "channels": self.channels})

    @dataclass
    class AudioChunk:
        audio: bytes
        rate: int = 48000
        width: int = 2
        channels: int = 1

        def event(self) -> Event:
            return Event(
                "audio-chunk",
                {"audio": self.audio, "rate": self.rate, "width": self.width, "channels": self.channels},
            )

    @dataclass
    class AudioStop:
        def event(self) -> Event:
            return Event("audio-stop", {})

    @dataclass
    class Error:
        text: str
        code: str

        def event(self) -> Event:
            return Event("error", {"text": self.text, "code": self.code})
