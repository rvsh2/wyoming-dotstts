# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] - 2026-07-02

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
