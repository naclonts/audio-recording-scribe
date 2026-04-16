# audio-recording-scribe

Local-first audio diary cleanup pipeline for synced voice recordings.

Current MVP capabilities:

- polling inbox discovery with stable-file detection
- SQLite-backed job state and idempotent registration
- ffmpeg normalization to mono 16 kHz PCM WAV
- import-safe `faster-whisper` transcription wrapper with first-run model download
- public Google Drive file and folder processing via `process-gdrive`
- heuristic GPS filtering
- deterministic text, markdown, and JSON provenance outputs
- CLI commands for `scan-once`, `watch`, `process`, `process-gdrive`, `check-runtime`, and `retry`

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
UV_CACHE_DIR=.uv-cache uv sync --frozen --extra asr --extra dev
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
uv run python -m audio_recording_scribe.cli check-runtime
uv run python -m audio_recording_scribe.cli --help
```

The CLI runs the current MVP pipeline:

- `scan-once`
- `watch`
- `process`
- `process-gdrive`
- `check-runtime`
- `retry`

## Process A Google Drive Folder

Run a public Google Drive folder through the pipeline and write the cleaned notes to a specific output directory:

```bash
AUDIO_RECORDING_SCRIBE_DIRECTORIES__OUTPUTS=/absolute/path/to/notes \
AUDIO_RECORDING_SCRIBE_TRANSCRIPTION__MODEL_CACHE_DIR=/absolute/path/to/model-cache \
uv run python -m audio_recording_scribe.cli process-gdrive \
  'https://drive.google.com/drive/folders/<folder-id>?resourcekey=<optional-resource-key>'
```

Notes:

- `AUDIO_RECORDING_SCRIBE_DIRECTORIES__OUTPUTS` controls where the cleaned `.txt`, `.md`, and provenance `.json` files are written.
- `AUDIO_RECORDING_SCRIBE_TRANSCRIPTION__MODEL_CACHE_DIR` controls where named Whisper models such as `small` are cached. If you keep the default model name, the first real transcription run will download it automatically.
- `AUDIO_RECORDING_SCRIBE_TRANSCRIPTION__MODEL_SIZE` can be a named model like `small` or a local filesystem path to a pre-downloaded Faster Whisper model directory.
- If the shared Drive folder needs a resource key, keep the `resourcekey=...` query parameter in the folder URL.
- `uv run python -m audio_recording_scribe.cli check-runtime` will confirm the local binaries, Python runtime, and configured model/cache behavior before you process the folder.
