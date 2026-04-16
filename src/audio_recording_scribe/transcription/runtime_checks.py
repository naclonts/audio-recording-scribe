"""Runtime readiness checks for local transcription dependencies."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import shutil

from audio_recording_scribe.config import TranscriptionConfig


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
class ModelRuntimeCheck:
    """Availability details for the configured Whisper model bootstrap path."""

    configured_model: str
    available: bool
    source: str
    resolved_model_path: str | None = None
    cache_dir: str | None = None
    will_download: bool = False
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class TranscriptionRuntimeReadiness:
    """Structured readiness report for real local transcription."""

    ready: bool
    ffmpeg: BinaryRuntimeCheck
    ffprobe: BinaryRuntimeCheck
    faster_whisper: ModuleRuntimeCheck
    model: ModelRuntimeCheck
    hints: tuple[str, ...]


def probe_transcription_runtime(
    transcription: TranscriptionConfig | None = None,
) -> TranscriptionRuntimeReadiness:
    """Inspect whether the local environment can run real transcription."""

    transcription_config = transcription or TranscriptionConfig()
    ffmpeg = _probe_binary("ffmpeg")
    ffprobe = _probe_binary("ffprobe")
    faster_whisper = _probe_module("faster_whisper")
    model = _probe_model(transcription_config)
    hints = _build_hints(ffmpeg=ffmpeg, ffprobe=ffprobe, faster_whisper=faster_whisper, model=model)
    ready = ffmpeg.available and ffprobe.available and faster_whisper.available and model.available
    return TranscriptionRuntimeReadiness(
        ready=ready,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        faster_whisper=faster_whisper,
        model=model,
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
    model: ModelRuntimeCheck,
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
    if not model.available:
        hints.append(model.detail or "Resolve the configured Whisper model location before running local transcription.")
    elif model.will_download and model.cache_dir:
        hints.append(f"The configured Whisper model will download on first transcription run into {model.cache_dir}.")
    return tuple(hints)


def _probe_model(transcription: TranscriptionConfig) -> ModelRuntimeCheck:
    configured_model = transcription.model_size
    cache_dir = transcription.model_cache_dir
    if _looks_like_path_reference(configured_model):
        model_path = Path(configured_model).expanduser()
        if model_path.exists():
            return ModelRuntimeCheck(
                configured_model=configured_model,
                available=True,
                source="local-path",
                resolved_model_path=str(model_path),
                detail=f"Configured Whisper model path exists: {model_path}",
            )
        return ModelRuntimeCheck(
            configured_model=configured_model,
            available=False,
            source="local-path",
            resolved_model_path=str(model_path),
            detail=f"Configured Whisper model path does not exist: {model_path}",
        )

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ModelRuntimeCheck(
            configured_model=configured_model,
            available=False,
            source="downloadable-model",
            cache_dir=str(cache_dir),
            will_download=True,
            detail=f"Configured Whisper model cache directory is not usable: {cache_dir} ({exc})",
        )

    return ModelRuntimeCheck(
        configured_model=configured_model,
        available=True,
        source="downloadable-model",
        cache_dir=str(cache_dir),
        will_download=True,
        detail=(
            f"Configured Whisper model {configured_model!r} is not a local path; "
            f"it will be downloaded on first transcription run."
        ),
    )


def _looks_like_path_reference(value: str) -> bool:
    return value.startswith(("~", ".", "/")) or os.sep in value or (os.altsep is not None and os.altsep in value)
