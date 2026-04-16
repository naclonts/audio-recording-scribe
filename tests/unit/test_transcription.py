from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from audio_recording_scribe.transcription.faster_whisper import (
    FasterWhisperTranscriber,
    TranscriptionDependencyUnavailable,
)


def test_transcriber_is_import_safe_without_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "faster_whisper", raising=False)
    original_import_module = importlib.import_module

    def fake_import_module(name: str):
        if name == "faster_whisper":
            exc = ModuleNotFoundError("No module named 'faster_whisper'")
            exc.name = name
            raise exc
        return original_import_module(name)

    monkeypatch.setattr(
        "audio_recording_scribe.transcription.faster_whisper.importlib.import_module",
        fake_import_module,
    )

    transcriber = FasterWhisperTranscriber()

    with pytest.raises(TranscriptionDependencyUnavailable, match="faster-whisper"):
        transcriber.transcribe(Path("sample.wav"))


def test_transcriber_normalizes_backend_segments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    model_init: dict[str, object] = {}

    class FakeModel:
        def __init__(
            self,
            model_size: str,
            device: str,
            compute_type: str,
            download_root: str | None = None,
        ) -> None:
            model_init.update(
                {
                    "model_size": model_size,
                    "device": device,
                    "compute_type": compute_type,
                    "download_root": download_root,
                }
            )

        def transcribe(self, source: str, language=None, vad_filter=None):
            return (
                [
                    SimpleNamespace(start=0.0, end=1.2, text="hello world", probability=0.91),
                    SimpleNamespace(start=1.2, end=2.3, text="turn right", probability=None),
                ],
                SimpleNamespace(language="en", model_name="tiny"),
            )

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeModel))

    cache_dir = tmp_path / "cache"
    transcriber = FasterWhisperTranscriber(
        model_size="tiny",
        model_cache_dir=cache_dir,
        device="cpu",
        compute_type="int8",
    )
    result = transcriber.transcribe(tmp_path / "source.wav")

    assert result.provider == "faster-whisper"
    assert result.model_name == "tiny"
    assert result.language == "en"
    assert [segment.text for segment in result.segments] == ["hello world", "turn right"]
    assert result.segments[0].probability == 0.91
    assert model_init == {
        "model_size": "tiny",
        "device": "cpu",
        "compute_type": "int8",
        "download_root": str(cache_dir),
    }
    assert cache_dir.is_dir()


def test_transcriber_rejects_missing_local_model_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=object))

    transcriber = FasterWhisperTranscriber(model_size="./missing-model")

    with pytest.raises(TranscriptionDependencyUnavailable, match="does not exist"):
        transcriber.transcribe(Path("sample.wav"))
