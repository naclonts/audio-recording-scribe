"""Import-safe wrapper around the optional faster-whisper dependency."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """Timestamped segment from ASR."""

    start: float
    end: float
    text: str
    probability: float | None = None


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Normalized transcription payload returned by the wrapper."""

    source_path: Path
    model_name: str
    provider: str
    segments: tuple[TranscriptSegment, ...]
    language: str | None = None


class TranscriptionDependencyUnavailable(RuntimeError):
    """Raised when faster-whisper is unavailable at runtime."""


class FasterWhisperTranscriber:
    """Lazy loader for faster-whisper."""

    def __init__(
        self,
        *,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "auto",
        language: str | None = None,
        vad_filter: bool = True,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.vad_filter = vad_filter
        self._model: Any | None = None
        self._backend_checked = False
        self._backend_error: Exception | None = None

    @property
    def backend_available(self) -> bool:
        return self._backend_checked and self._backend_error is None

    def transcribe(self, source_path: Path) -> TranscriptionResult:
        model = self._ensure_model()
        segments_iterable, info = model.transcribe(
            str(source_path),
            language=self.language,
            vad_filter=self.vad_filter,
        )
        segments = tuple(_coerce_segment(segment) for segment in segments_iterable)
        language = getattr(info, "language", None)
        model_name = getattr(info, "model_name", self.model_size)
        return TranscriptionResult(
            source_path=source_path,
            model_name=str(model_name),
            provider="faster-whisper",
            segments=segments,
            language=language,
        )

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            module = importlib.import_module("faster_whisper")
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
            self._backend_error = exc
            self._backend_checked = True
            raise TranscriptionDependencyUnavailable(
                "faster-whisper is not installed; install the 'asr' extra to enable transcription."
            ) from exc
        model_cls = getattr(module, "WhisperModel")
        self._model = model_cls(self.model_size, device=self.device, compute_type=self.compute_type)
        self._backend_checked = True
        return self._model


def _coerce_segment(segment: Any) -> TranscriptSegment:
    return TranscriptSegment(
        start=float(getattr(segment, "start")),
        end=float(getattr(segment, "end")),
        text=str(getattr(segment, "text", "")).strip(),
        probability=_optional_float(getattr(segment, "probability", None)),
    )


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
