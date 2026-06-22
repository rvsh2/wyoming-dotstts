"""HTTP debug server for Wyoming dots.tts."""

from __future__ import annotations

import argparse
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .audio import pcm16_wav_bytes
from .synthesizer import DEFAULT_MODEL, DotsTtsSynthesizer, SynthesisOptions


INDEX_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "index.html"
service = DotsTtsSynthesizer(
    model_name=DEFAULT_MODEL,
    default_voice=None,
    speaker_dir="/data/speakers",
    model_dir="/data/models",
)


class SynthesisRequest(BaseModel):
    text: str
    voice: str | None = None
    language: str | None = None
    num_steps: int | None = None
    guidance_scale: float | None = None
    seed: int | None = None


def render_index() -> str:
    template = INDEX_TEMPLATE_PATH.read_text(encoding="utf-8")
    template = template.replace("__MODEL__", service.model_name)
    template = template.replace("__VOICE__", service.default_voice or "none")
    return template


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="wyoming-dotstts debug server", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return render_index()


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(service.health_payload())


@app.get("/voices")
async def voices() -> JSONResponse:
    return JSONResponse({"voices": service.available_voices()})


@app.post("/synthesize")
async def synthesize(request: SynthesisRequest) -> JSONResponse:
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    try:
        result = service.synthesize(
            request.text,
            voice_name=request.voice,
            options=SynthesisOptions(
                num_steps=request.num_steps,
                guidance_scale=request.guidance_scale,
                seed=request.seed,
                language=request.language,
            ),
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
