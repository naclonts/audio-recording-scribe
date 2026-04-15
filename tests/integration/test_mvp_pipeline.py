from __future__ import annotations

import json
from pathlib import Path

from audio_recording_scribe.cli import main
from audio_recording_scribe.config import load_config
from audio_recording_scribe.domain import JobStatus
from audio_recording_scribe.paths import AppPaths
from audio_recording_scribe.state import SQLiteJobStore
from audio_recording_scribe.transcription import TranscriptSegment, TranscriptionResult


def test_scan_once_processes_ready_jobs_end_to_end(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text(
        "\n".join(
            [
                "ingestion:",
                "  stable_file_seconds: 0",
                "classification:",
                "  gps_patterns_path: tests/fixtures/gps_patterns.yaml",
            ]
        ),
        encoding="utf-8",
    )

    source = tmp_path / "data" / "inbox" / "drive.m4a"
    source.parent.mkdir(parents=True)
    source.write_text("fake audio", encoding="utf-8")

    def fake_normalize_audio(*args, **kwargs):
        output_dir = args[1]
        output_path = output_dir / "drive.wav"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("normalized", encoding="utf-8")
        return type(
            "NormalizedAudioStub",
            (),
            {
                "source_path": source,
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
                    TranscriptSegment(
                        start=1.0,
                        end=4.0,
                        text="I picked up coffee and read for a while.",
                    ),
                ),
            )

    monkeypatch.setattr("audio_recording_scribe.pipeline.service.normalize_audio", fake_normalize_audio)
    monkeypatch.setattr(
        "audio_recording_scribe.pipeline.service.FasterWhisperTranscriber",
        FakeTranscriber,
    )

    first_exit_code = main(["--config", str(settings_path), "scan-once"])
    exit_code = main(["--config", str(settings_path), "scan-once"])

    assert first_exit_code == 0
    assert exit_code == 0

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

    output_files = sorted(paths.outputs.glob("*.txt"))
    assert len(output_files) == 1
    text = output_files[0].read_text(encoding="utf-8")
    assert "Turn right" not in text
    assert "I picked up coffee and read for a while." in text

    transcript_files = sorted(paths.metadata.glob("*-transcript.json"))
    labels_files = sorted(paths.metadata.glob("*-labels.json"))
    assert len(transcript_files) == 1
    assert len(labels_files) == 1
    payload = json.loads(transcript_files[0].read_text(encoding="utf-8"))
    assert payload["segments"][1]["text"] == "I picked up coffee and read for a while."
