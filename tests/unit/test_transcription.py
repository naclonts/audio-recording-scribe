from __future__ import annotations

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

    transcriber = FasterWhisperTranscriber()

    with pytest.raises(TranscriptionDependencyUnavailable, match="faster-whisper"):
        transcriber.transcribe(Path("sample.wav"))


def test_transcriber_normalizes_backend_segments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeModel:
        def __init__(self, model_size: str, device: str, compute_type: str) -> None:
            self.model_size = model_size
            self.device = device
            self.compute_type = compute_type

        def transcribe(self, source: str, language=None, vad_filter=None):
            return (
                [
                    SimpleNamespace(start=0.0, end=1.2, text="hello world", probability=0.91),
                    SimpleNamespace(start=1.2, end=2.3, text="turn right", probability=None),
                ],
                SimpleNamespace(language="en", model_name="tiny"),
            )

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeModel))

    transcriber = FasterWhisperTranscriber(model_size="tiny", device="cpu", compute_type="int8")
    result = transcriber.transcribe(tmp_path / "source.wav")

    assert result.provider == "faster-whisper"
    assert result.model_name == "tiny"
    assert result.language == "en"
    assert [segment.text for segment in result.segments] == ["hello world", "turn right"]
    assert result.segments[0].probability == 0.91
