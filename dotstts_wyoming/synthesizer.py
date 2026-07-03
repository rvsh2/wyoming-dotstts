"""Shared dots.tts synthesis runtime."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np

from .speaker_store import SpeakerStore


LOGGER = logging.getLogger("dotstts-wyoming.synthesizer")

DEFAULT_MODEL = "rednote-hilab/dots.tts-mf"
DEFAULT_SAMPLE_RATE = 48000

# Silence trimming: samples are "silent" below 2% of the observed peak (with an
# absolute floor for all-quiet audio); 150 ms of padding is kept on each side
# so speech does not start or stop abruptly.
_SILENCE_RELATIVE_THRESHOLD = 0.02
_SILENCE_ABSOLUTE_FLOOR = 1e-4
_SILENCE_PADDING_SECONDS = 0.15


@dataclass
class SynthesisOptions:
    num_steps: Optional[int] = None
    guidance_scale: Optional[float] = None
    seed: Optional[int] = None
    language: Optional[str] = None


@dataclass
class SynthesisResult:
    audio: np.ndarray
    sample_rate: int
    voice: str
    language: str | None
    processing_time: float

    def asdict(self) -> dict:
        return {
            "sample_rate": self.sample_rate,
            "voice": self.voice,
            "language": self.language,
            "processing_time": self.processing_time,
            "audio_samples": int(len(self.audio)),
        }


class DotsTtsSynthesizer:
    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL,
        default_voice: str | None = None,
        speaker_dir: str = "/data/speakers",
        model_dir: str | None = None,
        device: str | None = None,
        precision: str = "bfloat16",
        num_steps: int = 4,
        guidance_scale: float = 1.2,
        seed: int | None = None,
        language: str | None = None,
        normalize_text: bool = False,
        optimize: bool = False,
        gain_db: float = 0.0,
        trim_silence: bool = True,
    ) -> None:
        self.model_name = model_name
        self.default_voice = default_voice
        self.speaker_store = SpeakerStore(speaker_dir)
        self.model_dir = model_dir
        self.device = device
        self.precision = precision
        self.num_steps = num_steps
        self.guidance_scale = guidance_scale
        self.seed = seed
        self.language = language
        self.normalize_text = normalize_text
        self.optimize = optimize
        self.gain_db = gain_db
        self.trim_silence = trim_silence
        self.backend = "dots.tts"
        self._runtime = None
        self._async_lock: asyncio.Lock | None = None

    def get_async_lock(self) -> asyncio.Lock:
        """Shared lock serializing GPU access across all client connections.

        Created lazily so it binds to the running event loop (the synthesizer is
        constructed at import time in the HTTP server, before any loop exists).
        """
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    def is_loaded(self) -> bool:
        return self._runtime is not None

    def load(self) -> None:
        if self._runtime is not None:
            return

        start_time = time.time()
        LOGGER.info("Loading dots.tts model '%s'", self.model_name)
        self._configure_visible_device()
        from dots_tts.runtime import DotsTtsRuntime

        kwargs = {
            "precision": self.precision,
            "optimize": self.optimize,
        }
        if self.model_dir:
            kwargs["cache_dir"] = self.model_dir

        self._runtime = DotsTtsRuntime.from_pretrained(self.model_name, **kwargs)
        LOGGER.info("dots.tts model loaded in %.1fs", time.time() - start_time)

    def _configure_visible_device(self) -> None:
        if not self.device:
            return

        requested = self.device.strip().lower()
        if requested == "cpu":
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            return

        if requested.startswith("cuda:"):
            _, device_index = requested.split(":", 1)
            if device_index.isdigit():
                os.environ["CUDA_VISIBLE_DEVICES"] = device_index

    def available_voices(self) -> list[str]:
        return self.speaker_store.profile_names()

    def runtime_settings(self) -> dict:
        """Settings adjustable at runtime (via the HTTP management API)."""
        return {"seed": self.seed, "gain_db": self.gain_db}

    def apply_runtime_settings(self, settings: dict) -> None:
        if "seed" in settings:
            seed = settings["seed"]
            self.seed = int(seed) if seed is not None else None
        if "gain_db" in settings:
            self.gain_db = float(settings["gain_db"])

    def _apply_gain(self, audio: np.ndarray) -> np.ndarray:
        if not self.gain_db:
            return audio
        return audio * np.float32(10.0 ** (self.gain_db / 20.0))

    def _trim_silence(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """Cut leading/trailing silence, keeping a short natural padding.

        The model pads generations with long silent tails (seconds of dead air
        for a short sentence), which directly delays Assist responses.
        """
        if not self.trim_silence or audio.size == 0:
            return audio
        threshold = max(float(np.abs(audio).max()) * _SILENCE_RELATIVE_THRESHOLD, _SILENCE_ABSOLUTE_FLOOR)
        loud = np.flatnonzero(np.abs(audio) > threshold)
        if loud.size == 0:
            return audio[:0]
        padding = int(_SILENCE_PADDING_SECONDS * sample_rate)
        start = max(0, int(loud[0]) - padding)
        end = min(len(audio), int(loud[-1]) + 1 + padding)
        return audio[start:end]

    def _trim_silence_stream(
        self, chunks: Iterable[np.ndarray], sample_rate: int
    ) -> Iterable[np.ndarray]:
        """Streaming variant of _trim_silence.

        Leading silent chunks are withheld until speech starts; silent runs are
        buffered and only flushed when more speech follows, so the trailing
        silent tail is dropped (except for a short padding). Chunk boundaries
        are coarse (~0.2 s), which is accurate enough here.
        """
        padding = int(_SILENCE_PADDING_SECONDS * sample_rate)
        peak = 0.0
        started = False
        pending: list[np.ndarray] = []

        for chunk in chunks:
            if chunk.size == 0:
                continue
            peak = max(peak, float(np.abs(chunk).max()))
            threshold = max(peak * _SILENCE_RELATIVE_THRESHOLD, _SILENCE_ABSOLUTE_FLOOR)
            silent = bool((np.abs(chunk) <= threshold).all())
            if silent:
                pending.append(chunk)
                continue
            if not started:
                # First speech: trim the buffered leading silence to padding.
                lead = np.concatenate(pending + [chunk]) if pending else chunk
                loud = np.flatnonzero(np.abs(lead) > threshold)
                started = True
                pending = []
                yield lead[max(0, int(loud[0]) - padding) :]
                continue
            for buffered in pending:
                yield buffered
            pending = []
            yield chunk

        if started and pending:
            tail = np.concatenate(pending)
            yield tail[:padding]

    def health_payload(self) -> dict:
        return {
            "status": "ok" if self.is_loaded() else "loading",
            "ready": self.is_loaded(),
            "model": self.model_name,
            "device": self.device,
            "precision": self.precision,
            "default_voice": self.default_voice,
            "num_steps": self.num_steps,
            "guidance_scale": self.guidance_scale,
            "seed": self.seed,
            "language": self.language,
            "gain_db": self.gain_db,
            "trim_silence": self.trim_silence,
            "normalize_text": self.normalize_text,
            "optimize": self.optimize,
            "backend": self.backend,
            "speaker_profiles": self.speaker_store.health_payload(),
        }

    @staticmethod
    def _tensor_to_float_array(audio) -> np.ndarray:
        """Flatten runtime output (torch tensor, ndarray, or nested list) to a
        1-D float32 numpy array without going through Python float objects."""
        if hasattr(audio, "detach"):
            audio = audio.detach()
        if hasattr(audio, "float"):
            audio = audio.float()
        if hasattr(audio, "cpu"):
            audio = audio.cpu()
        if hasattr(audio, "numpy"):
            audio = audio.numpy()
        return np.asarray(audio, dtype=np.float32).reshape(-1)

    def _runtime_kwargs(self, profile, options: SynthesisOptions | None) -> dict:
        options = options or SynthesisOptions()
        num_steps = options.num_steps if options.num_steps is not None else self.num_steps
        guidance_scale = (
            options.guidance_scale if options.guidance_scale is not None else self.guidance_scale
        )
        language = options.language if options.language is not None else self.language

        kwargs = {
            "prompt_audio_path": str(profile.prompt_audio_path),
            "prompt_text": profile.prompt_text,
            "num_steps": num_steps,
            "guidance_scale": guidance_scale,
        }
        if language:
            kwargs["language"] = language
        if self.normalize_text:
            kwargs["normalize_text"] = True
        return kwargs

    def _seed_for_options(self, options: SynthesisOptions | None) -> int | None:
        if options is not None and options.seed is not None:
            return options.seed
        return self.seed

    @staticmethod
    def _apply_seed(seed: int | None) -> None:
        if seed is None:
            return
        try:
            from dots_tts.utils.util import seed_everything
        except ImportError:  # pragma: no cover
            LOGGER.warning("dots_tts seed helper is unavailable; continuing without deterministic seed.")
            return
        seed_everything(seed)

    def synthesize(
        self,
        text: str,
        *,
        voice_name: str | None = None,
        options: SynthesisOptions | None = None,
    ) -> SynthesisResult:
        profile = self.speaker_store.get_profile(voice_name, self.default_voice)
        if not text.strip():
            return SynthesisResult(
                np.zeros(0, dtype=np.float32), DEFAULT_SAMPLE_RATE, profile.name, None, 0.0
            )

        self.load()
        assert self._runtime is not None

        runtime_kwargs = self._runtime_kwargs(profile, options)
        self._apply_seed(self._seed_for_options(options))
        start_time = time.time()
        result = self._runtime.generate(text=text, **runtime_kwargs)

        sample_rate = int(result.get("sample_rate", getattr(self._runtime, "sample_rate", DEFAULT_SAMPLE_RATE)))
        audio = self._apply_gain(
            self._trim_silence(self._tensor_to_float_array(result["audio"]), sample_rate)
        )

        return SynthesisResult(
            audio=audio,
            sample_rate=sample_rate,
            voice=profile.name,
            language=runtime_kwargs.get("language"),
            processing_time=round(time.time() - start_time, 2),
        )

    def synthesize_stream(
        self,
        text: str,
        *,
        voice_name: str | None = None,
        options: SynthesisOptions | None = None,
    ) -> Iterable[tuple[np.ndarray, int]]:
        profile = self.speaker_store.get_profile(voice_name, self.default_voice)
        if not text.strip():
            return

        self.load()
        assert self._runtime is not None

        runtime_kwargs = self._runtime_kwargs(profile, options)
        self._apply_seed(self._seed_for_options(options))
        sample_rate = int(getattr(self._runtime, "sample_rate", DEFAULT_SAMPLE_RATE))
        raw_chunks = (
            self._tensor_to_float_array(chunk)
            for chunk in self._runtime.generate_stream(text=text, **runtime_kwargs)
        )
        chunks = self._trim_silence_stream(raw_chunks, sample_rate) if self.trim_silence else raw_chunks
        for chunk in chunks:
            yield self._apply_gain(chunk), sample_rate
