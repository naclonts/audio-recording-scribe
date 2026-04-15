"""audio_recording_scribe package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("audio-recording-scribe")
except PackageNotFoundError:  # pragma: no cover - local source tree fallback
    __version__ = "0.1.0"

