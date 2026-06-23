# wyoming-dotstts

Wyoming TTS server for Home Assistant backed by `rednote-hilab/dots.tts`.

## What It Does

- exposes Wyoming TTS on port `10201`
- exposes optional HTTP debug on port `8180`
- uses `rednote-hilab/dots.tts-mf` by default
- publishes local voice-cloning profiles from `data/speakers`
- uses native `generate_stream` for streaming Wyoming requests

## Voice Profiles

Each Wyoming voice is a directory with reference audio and the exact transcript:

```text
data/speakers/mira/reference.wav
data/speakers/mira/prompt.txt
```

If `reference.wav` is missing but other `.wav` files exist, the first sorted `.wav` file is used. Profiles without `prompt.txt` are not published and appear under `invalid` in `/health`.

## Docker

```bash
cp .env.example .env
docker compose up --build -d
```

Persisted data:

- `./data/models` - Hugging Face/model cache
- `./data/speakers` - local reference voices

## Local Run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -c https://raw.githubusercontent.com/rednote-hilab/dots.tts/main/constraints/recommended.txt
pip install .
python -m dotstts_wyoming \
  --uri tcp://0.0.0.0:10201 \
  --speaker-dir ./data/speakers \
  --model-dir ./data/models \
  --http-host 0.0.0.0 \
  --http-port 8180
```

## Configuration

Important environment variables:

- `DOTSTTS_MODEL`, default `rednote-hilab/dots.tts-mf`
- `DOTSTTS_SPEAKER_DIR`, default `/data/speakers`
- `DOTSTTS_MODEL_DIR`, default `/data/models`
- `DOTSTTS_PRECISION`, default `bfloat16`
- `DOTSTTS_NUM_STEPS`, default `4`
- `DOTSTTS_GUIDANCE_SCALE`, default `1.2`; accepted but ignored by `dots.tts-mf`
- `DOTSTTS_SEED`
- `DOTSTTS_LANGUAGE` — language advertised to clients (default `pl`). Home Assistant's TTS
  entity needs at least one announced language to register, so the server always advertises
  this (and at least one voice) even before a profile exists.
- `DOTSTTS_DEFAULT_VOICE` — voice profile used by default / for warmup
- `DOTSTTS_NORMALIZE_TEXT`
- `DOTSTTS_OPTIMIZE`
- `DOTSTTS_NO_WARMUP` — set to `1` to skip the startup warmup (see below)

## Startup warmup

On startup, after loading the model, the server runs one short **warmup synthesis** (using the
default/first voice profile) so the *first* real request isn't slow — a cold synthesis pays
~30 s of CUDA kernel/graph compilation, which the warmup moves to startup. Disable with
`--no-warmup` / `DOTSTTS_NO_WARMUP=1`. Warmup is skipped if no voice profile exists.

## Tests

```bash
python -m unittest discover -s tests
```

## License

This repository is MIT licensed. dots.tts and its checkpoints are released separately by rednote-hilab under Apache-2.0.
