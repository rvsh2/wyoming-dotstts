"""Wyoming event handler for dots.tts."""

from __future__ import annotations

import argparse
import asyncio
import math
from typing import Any, Optional

from .audio import float32_to_pcm16
from .synthesizer import DotsTtsSynthesizer, SynthesisOptions
from .text import SentenceChunker
from .wyoming_protocol import (
    AsyncEventHandler,
    AudioChunk,
    AudioStart,
    AudioStop,
    Describe,
    Error,
    Event,
    Synthesize,
    SynthesizeChunk,
    SynthesizeStart,
    SynthesizeStop,
    SynthesizeStopped,
)


_STREAM_DONE = object()


def _next_chunk(iterator):
    """Pull one item from a sync generator, returning a sentinel when exhausted.

    Used with run_in_executor so each step runs off the event loop.
    """
    return next(iterator, _STREAM_DONE)


class DotsTtsEventHandler(AsyncEventHandler):
    def __init__(
        self,
        wyoming_info,
        cli_args: argparse.Namespace,
        synthesizer: DotsTtsSynthesizer,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.cli_args = cli_args
        self.synthesizer = synthesizer
        # Info instance or a zero-arg factory. A factory is rebuilt on every
        # Describe so voice profiles added at runtime show up without a restart.
        self._wyoming_info = wyoming_info
        self._streaming = False
        self._voice_name: Optional[str] = None
        self._options = SynthesisOptions()
        self._chunker = SentenceChunker()
        # Whether the current streaming session has already emitted AudioStart.
        # One audio-start/audio-stop pair brackets the whole stream, not each
        # sentence.
        self._stream_started = False

    async def handle_event(self, event: Event) -> bool:
        try:
            if Describe.is_type(event.type):
                info = self._wyoming_info() if callable(self._wyoming_info) else self._wyoming_info
                await self.write_event(info.event())
                return True

            if Synthesize.is_type(event.type):
                synthesize = Synthesize.from_event(event)
                if self._streaming:
                    return True
                return await self._handle_full_synthesize(
                    synthesize, voice_name=self._voice_name_from_event(event)
                )

            if self.cli_args.no_streaming:
                return True

            if SynthesizeStart.is_type(event.type):
                stream_start = SynthesizeStart.from_event(event)
                self._streaming = True
                self._stream_started = False
                self._chunker = SentenceChunker()
                self._voice_name = self._voice_name_from_event(event)
                self._options = self._options_from_context(getattr(stream_start, "context", None))
                return True

            if SynthesizeChunk.is_type(event.type):
                stream_chunk = SynthesizeChunk.from_event(event)
                for sentence in self._chunker.add_chunk(stream_chunk.text):
                    await self._emit_sentence_stream(sentence, voice_name=self._voice_name, options=self._options)
                return True

            if SynthesizeStop.is_type(event.type):
                remainder = self._chunker.finish()
                if remainder:
                    await self._emit_sentence_stream(remainder, voice_name=self._voice_name, options=self._options)
                if self._stream_started:
                    await self.write_event(AudioStop().event())
                    self._stream_started = False
                await self.write_event(SynthesizeStopped().event())
                self._streaming = False
                self._voice_name = None
                self._options = SynthesisOptions()
                return True

            return True
        except Exception as err:
            await self.write_event(Error(text=str(err), code=err.__class__.__name__).event())
            # If the error happened mid-stream, close the stream properly and
            # reset state: the connection is persistent, and a stuck
            # _streaming=True would silently swallow every later synthesize
            # while Home Assistant waits forever for synthesize-stopped.
            if self._streaming:
                if self._stream_started:
                    await self.write_event(AudioStop().event())
                    self._stream_started = False
                await self.write_event(SynthesizeStopped().event())
                self._streaming = False
                self._voice_name = None
                self._options = SynthesisOptions()
                self._chunker = SentenceChunker()
            return True

    @staticmethod
    def _voice_name_from_event(event: Event) -> Optional[str]:
        """Voice profile name from the raw event, or None.

        Reads event.data directly because wyoming's SynthesizeVoice.from_dict
        turns a language-only voice ({"language": "pl"}) into name="pl", which
        would then be looked up as a (nonexistent) profile directory instead of
        falling back to the default voice.
        """
        voice = (event.data or {}).get("voice")
        if isinstance(voice, dict):
            return voice.get("name")
        return getattr(voice, "name", None)

    async def _handle_full_synthesize(self, synthesize: Synthesize, *, voice_name: Optional[str]) -> bool:
        options = self._options_from_context(getattr(synthesize, "context", None))
        loop = asyncio.get_running_loop()
        async with self.synthesizer.get_async_lock():
            result = await loop.run_in_executor(
                None,
                lambda: self.synthesizer.synthesize(synthesize.text, voice_name=voice_name, options=options),
            )
        await self._emit_audio(result.audio, sample_rate=result.sample_rate)
        return True

    async def _emit_sentence_stream(
        self,
        sentence: str,
        *,
        voice_name: Optional[str],
        options: SynthesisOptions,
    ) -> None:
        loop = asyncio.get_running_loop()
        async with self.synthesizer.get_async_lock():
            iterator = iter(
                self.synthesizer.synthesize_stream(sentence, voice_name=voice_name, options=options)
            )
            # Drive the synchronous generator off the event loop so GPU inference
            # does not block other connections.
            while True:
                item = await loop.run_in_executor(None, _next_chunk, iterator)
                if item is _STREAM_DONE:
                    break
                audio, sample_rate = item
                if not self._stream_started:
                    await self.write_event(AudioStart(rate=sample_rate, width=2, channels=1).event())
                    self._stream_started = True
                await self._emit_audio_chunks(audio, sample_rate=sample_rate)

    async def _emit_audio(self, audio: list[float], *, sample_rate: int) -> None:
        await self.write_event(AudioStart(rate=sample_rate, width=2, channels=1).event())
        await self._emit_audio_chunks(audio, sample_rate=sample_rate)
        await self.write_event(AudioStop().event())

    async def _emit_audio_chunks(self, audio: list[float], *, sample_rate: int) -> None:
        audio_bytes = float32_to_pcm16(audio)
        width = 2
        channels = 1
        bytes_per_sample = width * channels
        bytes_per_chunk = bytes_per_sample * self.cli_args.samples_per_chunk
        num_chunks = max(1, int(math.ceil(len(audio_bytes) / max(1, bytes_per_chunk))))

        for index in range(num_chunks):
            offset = index * bytes_per_chunk
            chunk = audio_bytes[offset : offset + bytes_per_chunk]
            if not chunk:
                continue
            await self.write_event(
                AudioChunk(audio=chunk, rate=sample_rate, width=width, channels=channels).event()
            )

    @staticmethod
    def _options_from_context(context: Optional[dict[str, Any]]) -> SynthesisOptions:
        if not isinstance(context, dict):
            return SynthesisOptions()

        dotstts_context = context.get("dots.tts")
        if not isinstance(dotstts_context, dict):
            dotstts_context = context.get("dotstts")
        if not isinstance(dotstts_context, dict):
            dotstts_context = {}

        merged = {**context, **dotstts_context}
        return SynthesisOptions(
            num_steps=DotsTtsEventHandler._positive_int(merged.get("num_steps")),
            guidance_scale=DotsTtsEventHandler._positive_float(merged.get("guidance_scale")),
            seed=DotsTtsEventHandler._optional_int(merged.get("seed")),
            language=DotsTtsEventHandler._optional_str(merged.get("language")),
        )

    @staticmethod
    def _positive_int(value: Any) -> Optional[int]:
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            return None
        return resolved if resolved > 0 else None

    @staticmethod
    def _optional_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _positive_float(value: Any) -> Optional[float]:
        try:
            resolved = float(value)
        except (TypeError, ValueError):
            return None
        return resolved if resolved > 0 else None

    @staticmethod
    def _optional_str(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None
