"""HTTP debug server for Wyoming dots.tts."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .audio import pcm16_wav_bytes
from .runtime_settings import save_settings
from .synthesizer import DEFAULT_MODEL, DotsTtsSynthesizer, SynthesisOptions


INDEX_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "index.html"
service = DotsTtsSynthesizer(
    model_name=DEFAULT_MODEL,
    default_voice=None,
    speaker_dir="/data/speakers",
    model_dir="/data/models",
)
settings_path = Path(os.getenv("DOTSTTS_SETTINGS_FILE", "/data/settings.json"))


def _require_token(x_api_token: Optional[str]) -> None:
    """Reject the request when DOTSTTS_API_TOKEN is configured and not matched.

    Read at request time (not import time) so tests and runtime reconfiguration
    work without reloading the module. No token configured = open access, which
    keeps the plain localhost debug setup working.
    """
    expected = os.getenv("DOTSTTS_API_TOKEN", "").strip()
    if expected and x_api_token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Token header")


class SynthesisRequest(BaseModel):
    text: str
    voice: str | None = None
    language: str | None = None
    num_steps: int | None = None
    guidance_scale: float | None = None
    seed: int | None = None


class SettingsRequest(BaseModel):
    # seed=null explicitly restores random generation (and language/voice=null
    # restore auto/first-profile), so "field present" (model_fields_set)
    # rather than "field not None" decides what changes.
    seed: int | None = Field(default=None, ge=0)
    gain_db: float | None = Field(default=None, ge=-60, le=60)
    num_steps: int | None = Field(default=None, ge=1, le=64)
    trim_silence: bool | None = None
    default_voice: str | None = None
    language: str | None = None
    normalize_text: bool | None = None


_SETTINGS_KEYS = tuple(SettingsRequest.model_fields)


def render_index() -> str:
    template = INDEX_TEMPLATE_PATH.read_text(encoding="utf-8")
    template = template.replace("__MODEL__", service.model_name)
    template = template.replace("__VOICE__", service.default_voice or "none")
    return template


app = FastAPI(title="wyoming-dotstts debug server")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return render_index()


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(service.health_payload())


@app.get("/voices")
async def voices() -> JSONResponse:
    return JSONResponse({"voices": service.available_voices()})


@app.get("/settings")
async def get_settings(x_api_token: Optional[str] = Header(default=None)) -> JSONResponse:
    _require_token(x_api_token)
    return JSONResponse(service.runtime_settings())


@app.post("/settings")
async def update_settings(
    request: SettingsRequest, x_api_token: Optional[str] = Header(default=None)
) -> JSONResponse:
    _require_token(x_api_token)
    updates = {key: getattr(request, key) for key in _SETTINGS_KEYS if key in request.model_fields_set}
    # Nullable-but-not-optional fields: null means "back to default".
    for key, default in (("gain_db", 0.0), ("num_steps", 4), ("trim_silence", True), ("normalize_text", False)):
        if key in updates and updates[key] is None:
            updates[key] = default
    voice = updates.get("default_voice")
    if voice and voice not in service.available_voices():
        raise HTTPException(status_code=400, detail=f"Unknown voice profile '{voice}'")
    if updates:
        service.apply_runtime_settings(updates)
        save_settings(settings_path, service.runtime_settings())
    return JSONResponse(service.runtime_settings())


@app.post("/synthesize")
async def synthesize(
    request: SynthesisRequest, x_api_token: Optional[str] = Header(default=None)
) -> JSONResponse:
    _require_token(x_api_token)
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    options = SynthesisOptions(
        num_steps=request.num_steps,
        guidance_scale=request.guidance_scale,
        seed=request.seed,
        language=request.language,
    )
    # Run inference in the executor under the shared GPU lock: synthesis takes
    # seconds and would otherwise freeze the event loop shared with the Wyoming
    # server, and unlocked access could run CUDA concurrently with a Wyoming
    # request.
    loop = asyncio.get_running_loop()
    try:
        async with service.get_async_lock():
            result = await loop.run_in_executor(
                None,
                lambda: service.synthesize(request.text, voice_name=request.voice, options=options),
            )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    wav_bytes = pcm16_wav_bytes(result.audio, sample_rate=result.sample_rate)
    return JSONResponse({**result.asdict(), "wav_bytes": len(wav_bytes)})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="dots.tts HTTP debug server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8180)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    uvicorn.run(app, host=args.host, port=args.port)
