# audio-recording-scribe

Local-first audio diary cleanup pipeline for synced voice recordings.

Current MVP capabilities:

- polling inbox discovery with stable-file detection
- SQLite-backed job state and idempotent registration
- ffmpeg normalization to mono 16 kHz PCM WAV
- import-safe `faster-whisper` transcription wrapper
- heuristic GPS filtering
- deterministic text, markdown, and JSON provenance outputs
- CLI commands for `scan-once`, `watch`, `process`, and `retry`

Still planned, not implemented:

- diarization and speaker inference
- Git publishing
- deployment shell and updater logic
- local LLM adjudication and UI

## Layout

- `config/settings.yaml`: default runtime configuration
- `config/gps_patterns.yaml`: heuristic navigation phrases
- `src/audio_recording_scribe/`: application package
- `tests/`: unit and integration coverage

## Development

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
uv run python -m audio_recording_scribe.cli --help
```

The CLI runs the current MVP pipeline:

- `scan-once`
- `watch`
- `process`
- `retry`
