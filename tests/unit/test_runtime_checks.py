from __future__ import annotations

import types

import pytest

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

    report = probe_transcription_runtime()

    assert report.ready is True
    assert report.ffmpeg.available is True
    assert report.ffmpeg.resolved_path == "/usr/local/bin/ffmpeg"
    assert report.ffprobe.available is True
    assert report.faster_whisper.available is True
    assert report.hints == ()


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

    report = probe_transcription_runtime()

    assert report.ready is False
    assert report.ffmpeg.available is False
    assert report.ffprobe.available is False
    assert report.faster_whisper.available is False
    assert report.faster_whisper.detail == "faster_whisper is not installed in the active Python environment."
    assert report.hints == (
        "Install ffmpeg and make sure the `ffmpeg` binary is available on PATH.",
        "Install ffmpeg and make sure the `ffprobe` binary is available on PATH.",
        "Install the ASR runtime in this environment, for example with `uv sync --extra asr`.",
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

    report = probe_transcription_runtime()

    assert report.ready is False
    assert report.ffmpeg.available is True
    assert report.ffprobe.available is True
    assert report.faster_whisper.available is False
    assert report.faster_whisper.detail == (
        "faster_whisper could not be imported because dependency 'ctranslate2' is missing."
    )
    assert report.hints == (
        "Resolve the `faster_whisper` import failure before running local transcription.",
    )
