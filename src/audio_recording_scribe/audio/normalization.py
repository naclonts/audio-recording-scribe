"""FFmpeg-based audio normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AudioProbe:
    """Basic metadata extracted from an audio file."""

    path: Path
    duration_seconds: float | None
    sample_rate_hz: int | None
    channels: int | None
    codec_name: str | None


@dataclass(frozen=True, slots=True)
class NormalizedAudio:
    """Deterministic normalized audio artifact."""

    source_path: Path
    output_path: Path
    duration_seconds: float | None
    sample_rate_hz: int
    channels: int
    codec: str


class BinaryNotFoundError(RuntimeError):
    """Raised when the required FFmpeg binary cannot be found."""


def deterministic_normalized_path(source_path: Path, output_dir: Path, *, suffix: str = "wav") -> Path:
    """Return a stable output path for a source file."""

    resolved_source = source_path.resolve()
    digest = sha256(str(resolved_source).encode("utf-8")).hexdigest()[:16]
    return output_dir / f"{resolved_source.stem}-{digest}.{suffix.lstrip('.')}"


def probe_audio(source_path: Path, *, ffprobe_binary: str = "ffprobe") -> AudioProbe:
    """Inspect an input audio file with ffprobe.

    The function is intentionally small and import-safe; callers can ignore it if
    ffprobe is not installed.
    """

    ffprobe = _resolve_binary(ffprobe_binary, label="ffprobe")
    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(source_path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed for {source_path}: {completed.stderr.strip() or completed.stdout.strip()}"
        )

    payload = json.loads(completed.stdout or "{}")
    streams = payload.get("streams") or []
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    format_info = payload.get("format") or {}
    duration = _as_float(format_info.get("duration"))
    return AudioProbe(
        path=source_path,
        duration_seconds=duration,
        sample_rate_hz=_as_int(audio_stream.get("sample_rate")),
        channels=_as_int(audio_stream.get("channels")),
        codec_name=audio_stream.get("codec_name"),
    )


def normalize_audio(
    source_path: Path,
    output_dir: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    sample_rate_hz: int = 16000,
    channels: int = 1,
    codec: str = "pcm_s16le",
) -> NormalizedAudio:
    """Normalize an audio file to deterministic mono PCM WAV output."""

    ffmpeg = _resolve_binary(ffmpeg_binary, label="ffmpeg")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = deterministic_normalized_path(source_path, output_dir)

    with tempfile.NamedTemporaryFile(
        dir=output_dir,
        prefix=f".{output_path.stem}-",
        suffix=".tmp.wav",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_path),
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate_hz),
        "-c:a",
        codec,
        str(temp_path),
    ]

    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed for {source_path}: {completed.stderr.strip() or completed.stdout.strip()}"
            )
        temp_path.replace(output_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    probe: AudioProbe | None
    try:
        probe = probe_audio(output_path)
    except BinaryNotFoundError:
        probe = None
    return NormalizedAudio(
        source_path=source_path,
        output_path=output_path,
        duration_seconds=probe.duration_seconds if probe is not None else None,
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        codec=codec,
    )


def _resolve_binary(binary: str, *, label: str) -> str:
    candidate = Path(binary)
    if candidate.is_file() and candidate.exists():
        return str(candidate)
    resolved = shutil.which(binary)
    if resolved is None:
        raise BinaryNotFoundError(f"Required {label} binary not found: {binary}")
    return resolved


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
