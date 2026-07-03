<img src="brands/logo.png" alt="dots.TTS" height="96">

# wyoming-dotstts

Wyoming TTS server for Home Assistant backed by [`rednote-hilab/dots.tts`](https://github.com/rednote-hilab/dots.tts),
with the **dots.TTS** HACS integration for controlling speech settings from the HA UI.

## Features

- Wyoming TTS on port `10201` (streaming via native `generate_stream`), HTTP management API on port `8180`
- Voice cloning from local reference recordings (`data/speakers/`)
- Runtime settings without a restart — seed, output gain, diffusion steps, default voice,
  language, silence trimming, text normalization — via `POST /settings`, persisted across restarts
- Assist pipeline language reaches synthesis: voices are advertised per language
  (`profile|lang` voice ids), so the voice picked in a pipeline carries its language
- Leading/trailing silence is trimmed to 150 ms (the model pads generations with dead air)
- Sentence-aware streaming chunker that does not split abbreviations or initials
- Token-protected API (`DOTSTTS_API_TOKEN`), warmup synthesis at startup

## Quick start (Docker)

```bash
cp .env.example .env   # set DOTSTTS_API_TOKEN, defaults
docker compose up --build -d
```

Persisted under `./data/`: model cache (`models/`), voice profiles (`speakers/`),
runtime settings (`settings.json`).

## Home Assistant

1. **TTS entity**: add the core *Wyoming Protocol* integration pointing at `tcp://<host>:10201`,
   then select the voice in your Assist pipeline. Each voice appears once per language;
   the picked voice's language conditions the model.
2. **Settings entities**: in HACS add this repo as a custom repository (*Integration*),
   install **dots.TTS**, restart HA, then configure it with the server host, port `8180`
   and the API token. It creates:
   - `number`: *Seed* (−1 = random), *Gain* (dB), *Diffusion steps* (quality ↔ speed)
   - `select`: *Default voice*, *Language* (`auto` = first profile / auto-detect)
   - `switch`: *Trim silence*, *Normalize text*
   - `binary_sensor` *Ready*, `sensor` *Voices*
   - a **dots.TTS sidebar panel** for voice management: upload a reference recording
     (any format; converted and loudness-normalized automatically), play, delete and
     test-synthesize profiles — no filesystem access needed

Model, device and precision require a container restart and stay in `.env`.

## Voice profiles

Each voice is a directory with reference audio and its exact transcript:

```text
data/speakers/mira/reference.wav
data/speakers/mira/prompt.txt
```

Without `reference.wav`, the first sorted `.wav` is used. Profiles missing `prompt.txt`
are listed under `invalid` in `/health`. The list is re-scanned on every Wyoming
`describe`, so new profiles appear in HA without a restart.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DOTSTTS_MODEL` | `rednote-hilab/dots.tts-mf` | model checkpoint |
| `DOTSTTS_DEVICE` / `DOTSTTS_PRECISION` | `cuda` / `bfloat16` | inference device and dtype |
| `DOTSTTS_NUM_STEPS` | `4` | diffusion steps |
| `DOTSTTS_SEED` | unset (random) | deterministic generation |
| `DOTSTTS_GAIN_DB` | `0` | output gain in dB, clipped to [-1, 1] before PCM |
| `DOTSTTS_LANGUAGE` | unset (multilingual) | advertised/forced language; per-request priority: `context` > voice id > this setting > auto-detect |
| `DOTSTTS_DEFAULT_VOICE` | first profile | voice used when a request names none |
| `DOTSTTS_API_TOKEN` | unset (open) | required as `X-API-Token` by `/settings` and `/synthesize`; `/health` and `/voices` stay open |
| `DOTSTTS_SETTINGS_FILE` | `/data/settings.json` | persistence for runtime settings |
| `DOTSTTS_NO_TRIM_SILENCE` | `0` | set `1` to keep the model's leading/trailing silence |
| `DOTSTTS_NORMALIZE_TEXT` / `DOTSTTS_OPTIMIZE` / `DOTSTTS_NO_WARMUP` | `0` | text normalization / torch compile / skip startup warmup |

## HTTP API

```bash
curl -H "X-API-Token: $TOKEN" http://<host>:8180/settings          # current runtime settings
curl -X POST -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  http://<host>:8180/settings -d '{"seed": 42, "gain_db": 6}'      # null = back to default
```

Only explicitly changed keys are persisted; untouched settings keep following `.env`.
Also: `/health`, `/voices`, `POST /synthesize`, and a debug web page at `/`.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -c constraints.txt
pip install -e .[dev]
python -m pytest tests/
python -m dotstts_wyoming --speaker-dir ./data/speakers --model-dir ./data/models
```

## License

MIT. dots.tts and its checkpoints are released separately by rednote-hilab under Apache-2.0.
