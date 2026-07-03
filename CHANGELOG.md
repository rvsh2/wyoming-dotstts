# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] - 2026-07-03

### Added

- **Sub-realtime synthesis with `DOTSTTS_OPTIMIZE=1`**: the image now ships a
  C compiler (torch.compile/Triton needs one — previously the flag crashed at
  warmup with "Failed to find C compiler") and persists compile caches to
  `/data/cache/{torchinductor,triton}`, so only the first start pays the
  multi-minute compilation (warm start: ~5 s warmup). Measured on an
  RTX 3090: RTF 1.20 → 0.59 (batch) / 0.72 (streamed), first audio chunk
  after ~0.3 s — streaming synthesis no longer stutters behind playback and
  is enabled in compose again.

- **Voice management panel in the HA sidebar** (integration v0.4.0): list,
  play, upload (any audio format — converted to mono 24 kHz WAV with optional
  loudness normalization), delete and test-synthesize voice profiles. The
  panel talks to the server through an authenticated proxy view, so the API
  token never reaches the browser. New server endpoints: `POST /voices`,
  `DELETE /voices/{name}`, `GET /voices/{name}/audio`, richer `GET /voices`,
  and `POST /synthesize?format=wav`.
- **Compose healthcheck with self-restart**: probes the Wyoming port and the
  HTTP API every 30 s; after 3 consecutive failures it SIGINTs PID 1 so the
  restart policy revives a wedged (not just crashed) container. The kill only
  arms after the first healthy probe, so model loading is never aborted.
- **Assist pipeline language reaches synthesis end-to-end**: voices are
  advertised once per language with the language encoded in the voice id
  (`profile|lang`), because HA's Wyoming integration transmits only the picked
  voice id. The handler decodes it (and honors explicit `voice.language` from
  non-HA clients). Priority: `context` > voice > *Language* setting > auto.

### Changed

- Integration renamed to **dots.TTS**; logo added (`brands/`, shown in HACS).

## [Unreleased] - 2026-07-03

QA pass: 10 verified findings fixed.

### Fixed

- **GPU lock race on client disconnect**: the streaming producer is now asked
  to stop between inference steps instead of being cancelled, so the GPU lock
  is only released once the executor thread is idle — no more concurrent CUDA
  calls after an aborted stream.
- **Settings persistence redesigned to deltas**: settings.json stores only the
  keys explicitly changed via the API, so untouched settings keep following
  CLI/env config across restarts (previously one HA slider change froze the
  entire env snapshot forever). `null` now restores the operator-configured
  default (env/CLI), not a hardcoded built-in, and un-persists the key.
- **Persisted values are validated on load** (types/ranges; a deleted voice
  profile is dropped with a warning) — a hand-edited or stale settings.json
  can no longer crash startup or break all synthesis.
- **settings.json is written atomically** (temp file + rename), so a crash
  mid-write cannot truncate it.
- **Debug web UI works with token auth**: the page has an API-token field
  (stored in localStorage) and sends X-API-Token with /synthesize.
- **All-quiet generations keep a valid stream**: trimming now leaves a 150 ms
  silent stub instead of zero samples / a stream with no audio events.
- **Wyoming Describe advertises the effective language** (runtime changes
  included), not the stale env value, so HA pipeline pairing follows the
  actual synthesis language; warmup also follows the effective settings.
- HA integration v0.3.1: **401 triggers a reauth flow** (enter the new token
  in the UI instead of re-adding the integration) and the *Default voice*
  select falls back to `auto` when the persisted voice no longer exists.

## [a081d22] - 2026-07-03

Full runtime settings set in the HA integration.

### Added

- `/settings` now also accepts `num_steps` (1–64), `trim_silence`,
  `default_voice` (validated against existing profiles), `language`, and
  `normalize_text` — all persisted and applied without a restart.
- HA integration v0.3.0: *Diffusion steps* number, *Default voice* and
  *Language* selects (`auto` = server default), *Trim silence* and
  *Normalize text* switches.

## [e7b39d6] - 2026-07-03

Silence trimming + status entities.

### Added

- **Silence trimming (on by default)**: leading/trailing dead air is cut to
  150 ms of padding in both the full and streaming synthesis paths — the model
  pads generations with seconds of silence, which delayed Assist responses.
  Disable with `--no-trim-silence` / `DOTSTTS_NO_TRIM_SILENCE=1`.
- HA integration v0.2.0: `binary_sensor` *Ready* (model loaded) and `sensor`
  *Voices* (profile count; names and invalid-profile reasons in attributes).

## [71882be] - 2026-07-03

Runtime settings (seed, gain) + Home Assistant integration.

### Added

- **`GET`/`POST /settings`** on the HTTP management API: runtime-adjustable
  `seed` (null = random) and `gain_db` (output gain, ±60 dB max), applied to
  all synthesis (Wyoming + HTTP) and persisted to `/data/settings.json`
  across restarts. New env/CLI: `DOTSTTS_GAIN_DB`, `DOTSTTS_SETTINGS_FILE`.
- **Token auth** (`DOTSTTS_API_TOKEN`, `X-API-Token` header) for `/settings`
  and `/synthesize`; `/health` and `/voices` stay open. Compose publishes
  port 8180 on the LAN again now that it is authenticated.
- **HACS custom integration `wyoming_dotstts`** (bundled in
  `custom_components/`): config flow (host/port/token) and `number` entities
  for seed (−1 = random) and gain (dB slider) that drive `/settings`.
- Tests for gain scaling, settings persistence, and endpoint auth (35 total).

## [c097f9d] - 2026-07-03

Code-review pass: reproducibility, performance, and hygiene fixes.

### Fixed

- **`.env` is excluded from the Docker image** (`.dockerignore`) — `COPY . .`
  previously baked it into an image layer.
- **Reproducible builds**: the `dots.tts` git dependency is pinned to a commit
  and the upstream `recommended.txt` constraints are vendored into
  `constraints.txt`, so image builds no longer depend on GitHub being reachable
  or on upstream edits.
- **A slow client no longer stalls other connections' synthesis**: streamed
  audio is written to the client outside the shared GPU lock
  (producer/consumer split in the event handler).

### Changed

- **Audio stays a numpy array end-to-end** instead of a Python `list[float]`
  (~480k float objects per 10 s of 48 kHz audio), cutting per-request memory
  and conversion overhead.
- Warmup text follows the configured `DOTSTTS_LANGUAGE` instead of always
  being Polish.
- Compose publishes the auth-less HTTP debug port `8180` on `127.0.0.1` only;
  the Wyoming port is unchanged.
- Audio chunking loop simplified (no `math.ceil` bookkeeping); duplicated
  stream-close/reset logic factored into `_close_stream()`; unused FastAPI
  `lifespan` removed.

### Added

- `dev` extra (`pip install -e .[dev]`) with pytest so the test suite is
  runnable out of the box.

## [5614832] - 2026-07-02

QA pass: 10 verified findings fixed.

### Fixed

- **HTTP `/synthesize` no longer blocks the shared event loop** and now takes the
  GPU lock, so a debug-endpoint request can't freeze or corrupt concurrent
  Home Assistant TTS requests.
- **Streaming errors close the stream properly** (`audio-stop` +
  `synthesize-stopped`) and reset handler state — previously one failed request
  silently swallowed all later TTS on the same (persistent) connection.
- **HTTP debug server failures are non-fatal**: a busy port 8180 (uvicorn
  `SystemExit`) no longer crash-loops the whole container and the Wyoming
  service keeps serving.
- **Requests without a voice work out of the box**: fall back to
  `DOTSTTS_DEFAULT_VOICE`, then to the first valid speaker profile, instead of
  always erroring.
- **Voice list is rebuilt on every `describe`**, so profiles added to the
  live-mounted speaker dir appear in Home Assistant without a restart.
- **Language-only voice requests** (`{"voice": {"language": "pl"}}`) are no
  longer misresolved as profile names and correctly use the default voice.
- **Sentence chunker no longer splits abbreviations** (Polish and English:
  `np.`, `itd.`, `godz.`, `Dr.`, `prof.`, …) or single-letter initials
  mid-sentence during streaming.

### Changed

- When `DOTSTTS_LANGUAGE` is unset, a broad multilingual list is advertised
  instead of hard-coding `pl` (dots.tts auto-detects the input language), so
  non-Polish Assist pipelines can pair with the entity.
- `wyoming_protocol.py` is now a plain re-export of the real `wyoming` library;
  the divergent 157-line test fallback shim was removed and tests exercise real
  event semantics.
- `float32_to_pcm16` is vectorized with numpy (byte-identical output, ~100×
  faster), removing hundreds of milliseconds of event-loop stall per response.

### Added

- Tests: sentence-chunker suite (`tests/test_text.py`), streaming error
  recovery, language-only voice handling, dynamic `describe`, and
  default-profile fallback (24 tests total).
- `.env.example`: documented `DOTSTTS_DEFAULT_VOICE` and `DOTSTTS_LANGUAGE`.

## [ad5ebda] - 2026-06-23

### Added

- Startup warmup synthesis so the first real request doesn't pay ~30 s of CUDA
  kernel/graph compilation (disable with `DOTSTTS_NO_WARMUP=1`).

### Fixed

- Announce a language in the Wyoming info so Home Assistant registers the TTS
  entity.

## [1441ea8] - 2026-06-22

### Added

- Initial release: Wyoming TTS server backed by `rednote-hilab/dots.tts` with
  voice-cloning profiles from `data/speakers`, streaming synthesis via
  `generate_stream`, HTTP debug server (`/health`, `/voices`, `/synthesize`),
  and Docker/compose deployment.
