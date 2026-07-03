"""HTTP debug server for Wyoming dots.tts."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .audio import pcm16_wav_bytes
from .runtime_settings import load_settings, save_settings
from .synthesizer import DEFAULT_MODEL, DotsTtsSynthesizer, SynthesisOptions


INDEX_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "index.html"
service = DotsTtsSynthesizer(
    model_name=DEFAULT_MODEL,
    default_voice=None,
    speaker_dir="/data/speakers",
    model_dir="/data/models",
)
settings_path = Path(os.getenv("DOTSTTS_SETTINGS_FILE", "/data/settings.json"))
# CLI/env-configured values captured at startup, before persisted overrides are
# applied — "reset to default" restores these, not hardcoded built-ins.
# __main__.serve() overwrites this together with `service`.
startup_defaults = service.runtime_settings()


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


def _wav_duration_seconds(path: Path) -> Optional[float]:
    try:
        with wave.open(str(path)) as wav_file:
            return round(wav_file.getnframes() / wav_file.getframerate(), 2)
    except Exception:  # non-PCM or unreadable reference — duration is cosmetic
        return None


def _convert_reference_audio(source: Path, target: Path, *, normalize: bool) -> None:
    """Convert an uploaded recording to mono 24 kHz WAV via ffmpeg.

    Loudness normalization is on by default: the model clones the reference's
    level, so a quiet upload would produce a quiet voice.
    """
    command = ["ffmpeg", "-y", "-i", str(source), "-ac", "1", "-ar", "24000"]
    if normalize:
        command += ["-af", "loudnorm=I=-18"]
    command.append(str(target))
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise ValueError(f"ffmpeg could not convert the audio: {result.stderr.strip()[-400:]}")


@app.get("/voices")
async def voices() -> JSONResponse:
    valid, invalid = service.speaker_store._scan()
    return JSONResponse(
        {
            "voices": [profile.name for profile in valid],
            "valid": [
                {
                    "name": profile.name,
                    "prompt_text": profile.prompt_text,
                    "duration_seconds": _wav_duration_seconds(profile.prompt_audio_path),
                }
                for profile in valid
            ],
            "invalid": [
                {"name": profile.name, "reason": profile.reason} for profile in invalid
            ],
            "default_voice": service.default_voice,
        }
    )


@app.get("/voices/{name}/audio")
async def voice_audio(name: str, x_api_token: Optional[str] = Header(default=None)) -> FileResponse:
    _require_token(x_api_token)
    try:
        profile = service.speaker_store.get_profile(name)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return FileResponse(profile.prompt_audio_path, media_type="audio/wav")


@app.post("/voices")
async def create_voice(
    name: str = Form(...),
    prompt: str = Form(...),
    normalize: bool = Form(True),
    audio: UploadFile = File(...),
    x_api_token: Optional[str] = Header(default=None),
) -> JSONResponse:
    _require_token(x_api_token)
    name = name.strip()
    prompt = prompt.strip()
    if not service.speaker_store.is_safe_name(name):
        raise HTTPException(status_code=400, detail="Voice name must be a plain directory name without '|'")
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt transcript is required")

    profile_dir = service.speaker_store.speaker_dir / name
    loop = asyncio.get_running_loop()
    with tempfile.TemporaryDirectory() as temp:
        upload_path = Path(temp) / (Path(audio.filename or "upload").name or "upload")
        upload_path.write_bytes(await audio.read())
        converted_path = Path(temp) / "reference.wav"
        try:
            await loop.run_in_executor(
                None,
                lambda: _convert_reference_audio(upload_path, converted_path, normalize=normalize),
            )
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

        profile_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(converted_path), profile_dir / "reference.wav")
    (profile_dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")

    return JSONResponse(
        {
            "name": name,
            "duration_seconds": _wav_duration_seconds(profile_dir / "reference.wav"),
            "voices": service.available_voices(),
        }
    )


@app.delete("/voices/{name}")
async def delete_voice(name: str, x_api_token: Optional[str] = Header(default=None)) -> JSONResponse:
    _require_token(x_api_token)
    if not service.speaker_store.is_safe_name(name):
        raise HTTPException(status_code=400, detail="Invalid voice name")
    profile_dir = service.speaker_store.speaker_dir / name
    if not profile_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Voice profile '{name}' does not exist")
    shutil.rmtree(profile_dir)
    return JSONResponse({"deleted": name, "voices": service.available_voices()})


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
    voice = updates.get("default_voice")
    if voice and voice not in service.available_voices():
        raise HTTPException(status_code=400, detail=f"Unknown voice profile '{voice}'")
    if updates:
        # Persist only user-changed keys (deltas) so untouched settings keep
        # following CLI/env config across restarts. For seed/voice/language
        # null is a meaningful value (random / auto); for the rest null means
        # "back to the operator-configured default", which un-persists the key.
        persisted = load_settings(settings_path)
        applied = {}
        for key, value in updates.items():
            if value is None and key not in ("seed", "default_voice", "language"):
                applied[key] = startup_defaults[key]
                persisted.pop(key, None)
            else:
                applied[key] = value
                persisted[key] = value
        service.apply_runtime_settings(applied)
        save_settings(settings_path, persisted)
    return JSONResponse(service.runtime_settings())


@app.post("/synthesize")
async def synthesize(
    request: SynthesisRequest,
    format: Optional[str] = None,
    x_api_token: Optional[str] = Header(default=None),
) -> Response:
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
    if format == "wav":
        return Response(content=wav_bytes, media_type="audio/wav")
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
