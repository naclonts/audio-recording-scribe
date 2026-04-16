from __future__ import annotations

from pathlib import Path

from audio_recording_scribe.cli import main
from audio_recording_scribe.config import load_config
from audio_recording_scribe.domain import JobStatus
from audio_recording_scribe.paths import AppPaths
from audio_recording_scribe.state import SQLiteJobStore
from audio_recording_scribe.transcription import TranscriptSegment, TranscriptionResult


def test_process_gdrive_downloads_and_processes_once(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text(
        "\n".join(
            [
                "classification:",
                "  gps_patterns_path: tests/fixtures/gps_patterns.yaml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    source_url = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStuVwXyZ/view?usp=sharing"
    download_calls: list[Path] = []

    def fake_download_google_drive_file(download_request, destination, *, timeout=30.0, opener=None):
        del download_request, timeout, opener
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("downloaded audio", encoding="utf-8")
        download_calls.append(destination)
        return type(
            "GoogleDriveDownloadResultStub",
            (),
            {
                "destination": destination,
                "bytes_written": len("downloaded audio"),
                "content_type": "audio/mp4",
                "source_url": source_url,
            },
        )()

    def fake_normalize_audio(*args, **kwargs):
        del kwargs
        output_dir = args[1]
        output_path = output_dir / "drive.wav"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("normalized", encoding="utf-8")
        return type(
            "NormalizedAudioStub",
            (),
            {
                "source_path": args[0],
                "output_path": output_path,
                "duration_seconds": 12.0,
                "sample_rate_hz": 16000,
                "channels": 1,
                "codec": "pcm_s16le",
            },
        )()

    class FakeTranscriber:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def transcribe(self, normalized_path: Path) -> TranscriptionResult:
            return TranscriptionResult(
                source_path=normalized_path,
                provider="faster-whisper",
                model_name="small",
                language="en",
                segments=(
                    TranscriptSegment(start=0.0, end=1.0, text="Turn right in 500 feet."),
                    TranscriptSegment(start=1.0, end=4.0, text="I made coffee at home."),
                ),
            )

    monkeypatch.setattr(
        "audio_recording_scribe.cli.download_google_drive_file",
        fake_download_google_drive_file,
    )
    monkeypatch.setattr("audio_recording_scribe.pipeline.service.normalize_audio", fake_normalize_audio)
    monkeypatch.setattr(
        "audio_recording_scribe.pipeline.service.FasterWhisperTranscriber",
        FakeTranscriber,
    )

    first_exit_code = main(["--config", str(settings_path), "process-gdrive", source_url])
    second_exit_code = main(["--config", str(settings_path), "process-gdrive", source_url])

    assert first_exit_code == 0
    assert second_exit_code == 0
    assert len(download_calls) == 1

    config = load_config(settings_path, base_dir=tmp_path)
    paths = AppPaths(
        root=tmp_path,
        inbox=config.directories.inbox,
        processing=config.directories.processing,
        archive=config.directories.archive,
        failed=config.directories.failed,
        normalized=config.directories.normalized,
        outputs=config.directories.outputs,
        metadata=config.directories.metadata,
        logs=config.directories.logs,
        state_db=config.directories.state_db,
        gps_patterns=config.classification.gps_patterns_path,
    )
    store = SQLiteJobStore(paths.state_db)
    jobs = store.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.COMPLETED
    assert list(paths.processing.glob("gdrive/*")) == []
    assert any(path.is_file() for path in paths.archive.iterdir())
