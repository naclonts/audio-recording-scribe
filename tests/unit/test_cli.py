from __future__ import annotations

from pathlib import Path

import pytest

from audio_recording_scribe.cli import main
from audio_recording_scribe.transcription.runtime_checks import (
    BinaryRuntimeCheck,
    ModuleRuntimeCheck,
    TranscriptionRuntimeReadiness,
)


def test_cli_help_lists_mvp_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    stdout = capsys.readouterr().out
    assert "scan-once" in stdout
    assert "watch" in stdout
    assert "process" in stdout
    assert "process-gdrive" in stdout
    assert "check-runtime" in stdout
    assert "retry" in stdout


def test_scan_once_creates_runtime_directories(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text("{}", encoding="utf-8")

    exit_code = main(["--config", str(settings_path), "scan-once"])

    assert exit_code == 0
    assert (tmp_path / "data" / "inbox").is_dir()
    assert (tmp_path / "data" / "logs").is_dir()
    assert (tmp_path / "data" / "state").is_dir()


def test_check_runtime_reports_non_ready_environment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "audio_recording_scribe.cli.probe_transcription_runtime",
        lambda: TranscriptionRuntimeReadiness(
            ready=False,
            ffmpeg=BinaryRuntimeCheck(name="ffmpeg", available=True, resolved_path="/usr/bin/ffmpeg"),
            ffprobe=BinaryRuntimeCheck(name="ffprobe", available=True, resolved_path="/usr/bin/ffprobe"),
            faster_whisper=ModuleRuntimeCheck(
                module_name="faster_whisper",
                available=False,
                detail="faster_whisper is not installed in the active Python environment.",
            ),
            hints=("Install the ASR runtime in this environment.",),
        ),
    )

    exit_code = main(["check-runtime"])

    assert exit_code == 1
    stdout = capsys.readouterr().out
    assert '"ready": false' in stdout
    assert "faster_whisper" in stdout
