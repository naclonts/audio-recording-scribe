from __future__ import annotations

import types
from pathlib import Path

import pytest

from audio_recording_scribe.config import TranscriptionConfig
from audio_recording_scribe.transcription.runtime_checks import probe_transcription_runtime


def test_probe_transcription_runtime_reports_ready_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "audio_recording_scribe.transcription.runtime_checks.shutil.which",
        lambda name: f"/usr/local/bin/{name}",
    )
    monkeypatch.setattr(
        "audio_recording_scribe.transcription.runtime_checks.importlib.import_module",
        lambda name: types.SimpleNamespace(__file__="/venv/lib/python/site-packages/faster_whisper/__init__.py"),
    )

    report = probe_transcription_runtime(
        TranscriptionConfig(model_size="small", model_cache_dir=Path("/tmp/model-cache"))
    )

    assert report.ready is True
    assert report.ffmpeg.available is True
    assert report.ffmpeg.resolved_path == "/usr/local/bin/ffmpeg"
    assert report.ffprobe.available is True
    assert report.faster_whisper.available is True
    assert report.model.available is True
    assert report.model.source == "downloadable-model"
    assert report.model.cache_dir == "/tmp/model-cache"
    assert report.model.will_download is True
    assert report.hints == (
        "The configured Whisper model will download on first transcription run into /tmp/model-cache.",
    )


def test_probe_transcription_runtime_reports_missing_binaries_and_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "audio_recording_scribe.transcription.runtime_checks.shutil.which",
        lambda _: None,
    )

    def raise_missing_module(name: str) -> types.SimpleNamespace:
        exc = ModuleNotFoundError("No module named 'faster_whisper'")
        exc.name = name
        raise exc

    monkeypatch.setattr(
        "audio_recording_scribe.transcription.runtime_checks.importlib.import_module",
        raise_missing_module,
    )

    report = probe_transcription_runtime(
        TranscriptionConfig(model_size="small", model_cache_dir=Path("/tmp/model-cache"))
    )

    assert report.ready is False
    assert report.ffmpeg.available is False
    assert report.ffprobe.available is False
    assert report.faster_whisper.available is False
    assert report.faster_whisper.detail == "faster_whisper is not installed in the active Python environment."
    assert report.model.available is True
    assert report.hints == (
        "Install ffmpeg and make sure the `ffmpeg` binary is available on PATH.",
        "Install ffmpeg and make sure the `ffprobe` binary is available on PATH.",
        "Install the ASR runtime in this environment, for example with `uv sync --extra asr`.",
        "The configured Whisper model will download on first transcription run into /tmp/model-cache.",
    )


def test_probe_transcription_runtime_reports_missing_python_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "audio_recording_scribe.transcription.runtime_checks.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )

    def raise_missing_dependency(name: str) -> types.SimpleNamespace:
        exc = ModuleNotFoundError("No module named 'ctranslate2'")
        exc.name = "ctranslate2"
        raise exc

    monkeypatch.setattr(
        "audio_recording_scribe.transcription.runtime_checks.importlib.import_module",
        raise_missing_dependency,
    )

    report = probe_transcription_runtime(
        TranscriptionConfig(model_size="small", model_cache_dir=Path("/tmp/model-cache"))
    )

    assert report.ready is False
    assert report.ffmpeg.available is True
    assert report.ffprobe.available is True
    assert report.faster_whisper.available is False
    assert report.faster_whisper.detail == (
        "faster_whisper could not be imported because dependency 'ctranslate2' is missing."
    )
    assert report.hints == (
        "Resolve the `faster_whisper` import failure before running local transcription.",
        "The configured Whisper model will download on first transcription run into /tmp/model-cache.",
    )


def test_probe_transcription_runtime_reports_missing_requests_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "audio_recording_scribe.transcription.runtime_checks.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )

    def raise_missing_dependency(name: str) -> types.SimpleNamespace:
        exc = ModuleNotFoundError("No module named 'requests'")
        exc.name = "requests"
        raise exc

    monkeypatch.setattr(
        "audio_recording_scribe.transcription.runtime_checks.importlib.import_module",
        raise_missing_dependency,
    )

    report = probe_transcription_runtime(
        TranscriptionConfig(model_size="small", model_cache_dir=Path("/tmp/model-cache"))
    )

    assert report.ready is False
    assert report.faster_whisper.available is False
    assert report.faster_whisper.detail == (
        "faster_whisper could not be imported because dependency 'requests' is missing."
    )
    assert report.hints == (
        "Resolve the `faster_whisper` import failure before running local transcription.",
        "The configured Whisper model will download on first transcription run into /tmp/model-cache.",
    )


def test_probe_transcription_runtime_reports_missing_local_model_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "audio_recording_scribe.transcription.runtime_checks.shutil.which",
        lambda name: f"/usr/local/bin/{name}",
    )
    monkeypatch.setattr(
        "audio_recording_scribe.transcription.runtime_checks.importlib.import_module",
        lambda name: types.SimpleNamespace(__file__="/venv/lib/python/site-packages/faster_whisper/__init__.py"),
    )

    missing_model = tmp_path / "missing-model"
    report = probe_transcription_runtime(
        TranscriptionConfig(model_size=str(missing_model), model_cache_dir=tmp_path / "cache")
    )

    assert report.ready is False
    assert report.model.available is False
    assert report.model.source == "local-path"
    assert report.model.resolved_model_path == str(missing_model)
    assert report.hints == (f"Configured Whisper model path does not exist: {missing_model}",)
