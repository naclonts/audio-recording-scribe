"""Runtime readiness checks for local transcription dependencies."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import shutil


@dataclass(frozen=True, slots=True)
class BinaryRuntimeCheck:
    """Availability details for a required system binary."""

    name: str
    available: bool
    resolved_path: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleRuntimeCheck:
    """Availability details for a required Python module."""

    module_name: str
    available: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class TranscriptionRuntimeReadiness:
    """Structured readiness report for real local transcription."""

    ready: bool
    ffmpeg: BinaryRuntimeCheck
    ffprobe: BinaryRuntimeCheck
    faster_whisper: ModuleRuntimeCheck
    hints: tuple[str, ...]


def probe_transcription_runtime() -> TranscriptionRuntimeReadiness:
    """Inspect whether the local environment can run real transcription."""

    ffmpeg = _probe_binary("ffmpeg")
    ffprobe = _probe_binary("ffprobe")
    faster_whisper = _probe_module("faster_whisper")
    hints = _build_hints(ffmpeg=ffmpeg, ffprobe=ffprobe, faster_whisper=faster_whisper)
    ready = ffmpeg.available and ffprobe.available and faster_whisper.available
    return TranscriptionRuntimeReadiness(
        ready=ready,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        faster_whisper=faster_whisper,
        hints=hints,
    )


def _probe_binary(name: str) -> BinaryRuntimeCheck:
    resolved_path = shutil.which(name)
    if resolved_path:
        return BinaryRuntimeCheck(
            name=name,
            available=True,
            resolved_path=resolved_path,
            detail=f"{name} found on PATH.",
        )
    return BinaryRuntimeCheck(
        name=name,
        available=False,
        detail=f"{name} was not found on PATH.",
    )


def _probe_module(module_name: str) -> ModuleRuntimeCheck:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing_name = getattr(exc, "name", None) or module_name
        if missing_name == module_name:
            detail = f"{module_name} is not installed in the active Python environment."
        else:
            detail = (
                f"{module_name} could not be imported because dependency "
                f"{missing_name!r} is missing."
            )
        return ModuleRuntimeCheck(module_name=module_name, available=False, detail=detail)
    except Exception as exc:  # pragma: no cover - depends on local environment
        detail = f"{module_name} import failed with {exc.__class__.__name__}: {exc}"
        return ModuleRuntimeCheck(module_name=module_name, available=False, detail=detail)

    location = getattr(module, "__file__", None)
    if location:
        detail = f"{module_name} imported successfully from {location}."
    else:
        detail = f"{module_name} imported successfully."
    return ModuleRuntimeCheck(module_name=module_name, available=True, detail=detail)


def _build_hints(
    *,
    ffmpeg: BinaryRuntimeCheck,
    ffprobe: BinaryRuntimeCheck,
    faster_whisper: ModuleRuntimeCheck,
) -> tuple[str, ...]:
    hints: list[str] = []
    if not ffmpeg.available:
        hints.append("Install ffmpeg and make sure the `ffmpeg` binary is available on PATH.")
    if not ffprobe.available:
        hints.append("Install ffmpeg and make sure the `ffprobe` binary is available on PATH.")
    if not faster_whisper.available:
        detail = faster_whisper.detail or ""
        if "is not installed" in detail:
            hints.append("Install the ASR runtime in this environment, for example with `uv sync --extra asr`.")
        else:
            hints.append("Resolve the `faster_whisper` import failure before running local transcription.")
    return tuple(hints)
