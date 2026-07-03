<img src="brands/logo.png" alt="dots.TTS" height="96">

# wyoming-dotstts

Wyoming TTS server for Home Assistant backed by `rednote-hilab/dots.tts`. Ships the
**dots.TTS** HACS integration for runtime speech settings.

## What It Does

- exposes Wyoming TTS on port `10201`
- exposes an HTTP management/debug API on port `8180` (its failure never takes the Wyoming service down); `/settings` and `/synthesize` are protected by `DOTSTTS_API_TOKEN` (`X-API-Token` header)
- runtime-adjustable **seed** (deterministic output) and **output gain** via `POST /settings`, persisted across restarts in `/data/settings.json`
- ships a HACS custom integration (`custom_components/wyoming_dotstts`) that exposes the seed and gain as `number` entities in Home Assistant
- uses `rednote-hilab/dots.tts-mf` by default
- publishes local voice-cloning profiles from `data/speakers`
- uses native `generate_stream` for streaming Wyoming requests
- requests without a voice fall back to `DOTSTTS_DEFAULT_VOICE`, then to the first profile
- streamed text is split into sentences without breaking abbreviations (`np.`, `Dr.`, initials)

## Voice Profiles

Each Wyoming voice is a directory with reference audio and the exact transcript:

```text
data/speakers/mira/reference.wav
data/speakers/mira/prompt.txt
```

If `reference.wav` is missing but other `.wav` files exist, the first sorted `.wav` file is used. Profiles without `prompt.txt` are not published and appear under `invalid` in `/health`.

The voice list is re-scanned on every Wyoming `describe`, so profiles dropped into the
(live-mounted) speaker dir show up in Home Assistant without a container restart — just
reload the Wyoming integration or wait for the next describe.

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
pip install -r requirements.txt -c constraints.txt
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
- `DOTSTTS_LANGUAGE` — language advertised to clients. When unset, a broad multilingual
  list is advertised (dots.tts auto-detects the input language). Home Assistant's TTS
  entity needs at least one announced language to register, so the server always advertises
  at least one language (and at least one voice) even before a profile exists.
  Voices are advertised once per language with the language encoded in the voice id
  (`profile|lang`): HA's Wyoming integration transmits only the picked voice id, so this
  is how the Assist pipeline's language reaches synthesis — pick the voice in a pipeline
  and its language conditions the model. Per-request language priority:
  `context` > voice id / `voice.language` > the *Language* runtime setting > auto-detect.
- `DOTSTTS_DEFAULT_VOICE` — voice profile used when a request names none; falls back to
  the first profile in the speaker dir when unset
- `DOTSTTS_GAIN_DB`, default `0` — output gain in dB (audio is clipped to [-1, 1] before PCM)
- `DOTSTTS_API_TOKEN` — when set, `/settings` and `/synthesize` on the HTTP API require the
  `X-API-Token` header; `/health` and `/voices` stay open
- `DOTSTTS_SETTINGS_FILE`, default `/data/settings.json` — persistence for runtime settings
- `DOTSTTS_NO_TRIM_SILENCE` — set to `1` to keep the model's leading/trailing silence
  (by default it is trimmed to 150 ms of padding; the model pads generations with
  seconds of dead air, which delays Assist responses)
- `DOTSTTS_NORMALIZE_TEXT`
- `DOTSTTS_OPTIMIZE`
- `DOTSTTS_NO_WARMUP` — set to `1` to skip the startup warmup (see below)

## Runtime settings & Home Assistant integration

The Wyoming protocol cannot carry seed/volume options from Home Assistant, so they are
server-side runtime settings instead:

```bash
curl -X POST http://<host>:8180/settings \
  -H "X-API-Token: $DOTSTTS_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"seed": 42, "gain_db": 6}'    # seed null = random again
```

Changes apply to every following synthesis (Wyoming and HTTP) and survive restarts.

To control them from Home Assistant, install the bundled custom integration via HACS:
HACS → custom repositories → add this repo as *Integration* → install *dots.TTS* →
restart HA → add the integration with the server host, port `8180`, and the API token.
It creates entities for every runtime setting: `number` *Seed* (−1 = random), *Gain* (dB),
*Diffusion steps* (quality ↔ speed); `select` *Default voice* and *Language* (`auto` =
first profile / auto-detect); `switch` *Trim silence* and *Normalize text*; plus
`binary_sensor` *Ready* (model loaded) and `sensor` *Voices* (profile count, names in
attributes) for dashboards and automations. Model/device/precision still require a
container restart and stay in `.env`.

## Startup warmup

On startup, after loading the model, the server runs one short **warmup synthesis** (using the
default/first voice profile) so the *first* real request isn't slow — a cold synthesis pays
~30 s of CUDA kernel/graph compilation, which the warmup moves to startup. Disable with
`--no-warmup` / `DOTSTTS_NO_WARMUP=1`. Warmup is skipped if no voice profile exists.

## Tests

```bash
pip install -e .[dev]
python -m pytest tests/
```

## License

This repository is MIT licensed. dots.tts and its checkpoints are released separately by rednote-hilab under Apache-2.0.
