"""CLI entrypoint for Wyoming dots.tts."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from functools import partial
from typing import Optional

from . import __version__
from .handler import DotsTtsEventHandler
from .speaker_store import SpeakerStore
from .synthesizer import DEFAULT_MODEL, DotsTtsSynthesizer, SynthesisOptions
from .wyoming_protocol import (
    AsyncServer,
    Attribution,
    Info,
    TtsProgram,
    TtsVoice,
)


LOGGER = logging.getLogger("dotstts-wyoming")

# dots.tts is multilingual and auto-detects the input language, so when no
# language is configured, advertise a broad set instead of pinning one — Home
# Assistant refuses to pair a pipeline whose language the entity doesn't list.
DEFAULT_LANGUAGES = [
    "en", "pl", "de", "fr", "es", "it", "pt", "nl", "cs", "sk",
    "uk", "ru", "zh", "ja", "ko",
]


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return int(value)


def _voice_entry(name: str, languages: list[str]) -> TtsVoice:
    return TtsVoice(
        name=name,
        description=name,
        attribution=Attribution(
            name="Local reference prompt",
            url="https://github.com/rednote-hilab/dots.tts",
        ),
        installed=True,
        version=None,
        languages=languages,
    )


def build_info(args: argparse.Namespace, synthesizer: DotsTtsSynthesizer) -> Info:
    # Home Assistant's TTS entity requires at least one announced language to set
    # _attr_default_language; without it the entity fails to register.
    languages = [args.language] if args.language else DEFAULT_LANGUAGES
    # Always advertise at least one voice, even when no reference prompts exist on
    # disk, so HA can create the entity.
    names = synthesizer.available_voices() or [args.voice or "default"]
    voices = [_voice_entry(name, languages) for name in names]
    return Info(
        tts=[
            TtsProgram(
                name="dots.tts",
                description="Wyoming protocol server backed by rednote-hilab dots.tts",
                attribution=Attribution(
                    name="rednote-hilab",
                    url="https://github.com/rednote-hilab/dots.tts",
                ),
                installed=True,
                version=__version__,
                voices=voices,
                supports_synthesize_streaming=(not args.no_streaming),
            )
        ]
    )


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wyoming dots.tts server for Home Assistant",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--uri", default=os.getenv("WYOMING_URI", "tcp://0.0.0.0:10201"))
    parser.add_argument("--model", default=os.getenv("DOTSTTS_MODEL", DEFAULT_MODEL))
    parser.add_argument("--voice", default=os.getenv("DOTSTTS_DEFAULT_VOICE"))
    parser.add_argument("--speaker-dir", default=os.getenv("DOTSTTS_SPEAKER_DIR", "/data/speakers"))
    parser.add_argument("--model-dir", default=os.getenv("DOTSTTS_MODEL_DIR", "/data/models"))
    parser.add_argument("--device", default=os.getenv("DOTSTTS_DEVICE", "cuda"))
    parser.add_argument("--precision", default=os.getenv("DOTSTTS_PRECISION", "bfloat16"))
    parser.add_argument("--num-steps", type=int, default=int(os.getenv("DOTSTTS_NUM_STEPS", "4")))
    parser.add_argument(
        "--guidance-scale",
        type=float,
        default=float(os.getenv("DOTSTTS_GUIDANCE_SCALE", "1.2")),
        help="CFG scale. For dots.tts-mf this is accepted but ignored by the model.",
    )
    parser.add_argument("--seed", type=int, default=_env_optional_int("DOTSTTS_SEED"))
    parser.add_argument("--language", default=os.getenv("DOTSTTS_LANGUAGE"))
    parser.add_argument(
        "--normalize-text",
        action="store_true",
        default=_env_bool("DOTSTTS_NORMALIZE_TEXT", False),
    )
    parser.add_argument("--optimize", action="store_true", default=_env_bool("DOTSTTS_OPTIMIZE", False))
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        default=_env_bool("DOTSTTS_NO_WARMUP", False),
        help="Skip the startup warmup synthesis (warmup avoids a slow first request).",
    )
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--samples-per-chunk", type=int, default=1024)
    parser.add_argument("--no-streaming", action="store_true")
    parser.add_argument("--http-host", default=os.getenv("HTTP_HOST"))
    parser.add_argument("--http-port", type=int, default=int(os.getenv("HTTP_PORT", "8180")))
    return parser.parse_args(argv)


async def _serve_http_debug(
    synthesizer: DotsTtsSynthesizer,
    *,
    host: str,
    port: int,
) -> None:
    import uvicorn

    from . import server as http_server

    http_server.service = synthesizer
    config = uvicorn.Config(http_server.app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    # A debug-only endpoint must never take the Wyoming TTS service down with
    # it — e.g. a busy port would otherwise crash-loop the whole container.
    # uvicorn raises SystemExit on bind failure, so catch that too (but let
    # CancelledError through for clean shutdown).
    try:
        await server.serve()
    except asyncio.CancelledError:
        raise
    except (Exception, SystemExit):
        LOGGER.exception("HTTP debug server failed; continuing without it")


async def serve(args: argparse.Namespace) -> None:
    synthesizer = DotsTtsSynthesizer(
        model_name=args.model,
        default_voice=args.voice,
        speaker_dir=args.speaker_dir,
        model_dir=args.model_dir,
        device=args.device,
        precision=args.precision,
        num_steps=args.num_steps,
        guidance_scale=args.guidance_scale,
        seed=args.seed,
        language=args.language,
        normalize_text=args.normalize_text,
        optimize=args.optimize,
    )
    SpeakerStore(args.speaker_dir).ensure_default_profile_hint(args.voice)
    synthesizer.load()
    # Passed as a factory so the voice list is re-scanned on every Describe:
    # profiles dropped into the (live-mounted) speaker dir appear in Home
    # Assistant without a container restart.
    info_factory = partial(build_info, args, synthesizer)

    # Warm up the model so the FIRST real request isn't slow (cold synthesis can
    # take ~30s while CUDA kernels/graphs compile). Blocks startup until done.
    if not args.no_warmup:
        warm_voices = synthesizer.available_voices()
        if warm_voices:
            try:
                _t = time.perf_counter()
                synthesizer.synthesize(
                    "Rozgrzewka.",
                    voice_name=warm_voices[0],
                    options=SynthesisOptions(
                        num_steps=args.num_steps,
                        guidance_scale=args.guidance_scale,
                        seed=args.seed,
                        language=args.language,
                    ),
                )
                LOGGER.info("Warmup synthesis done in %.1fs (voice=%s)", time.perf_counter() - _t, warm_voices[0])
            except Exception as exc:  # noqa: BLE001 - warmup must never block serving
                LOGGER.warning("Warmup synthesis failed (continuing): %s", exc)
        else:
            LOGGER.info("Warmup skipped: no voice profiles available")

    server = AsyncServer.from_uri(args.uri)

    LOGGER.info("Model: %s", args.model)
    LOGGER.info("URI: %s", args.uri)
    LOGGER.info("Speaker dir: %s", args.speaker_dir)
    LOGGER.info("Streaming: %s", not args.no_streaming)

    tasks = [asyncio.create_task(server.run(partial(DotsTtsEventHandler, info_factory, args, synthesizer)))]

    if args.http_host:
        LOGGER.info("HTTP debug: http://%s:%s", args.http_host, args.http_port)
        tasks.append(asyncio.create_task(_serve_http_debug(synthesizer, host=args.http_host, port=args.http_port)))

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for task in pending:
        task.cancel()
    for task in done:
        task.result()


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        LOGGER.info("Stopped")


if __name__ == "__main__":
    main()
