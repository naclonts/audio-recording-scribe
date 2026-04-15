from __future__ import annotations

from pathlib import Path
from time import time

from audio_recording_scribe.config import load_config
from audio_recording_scribe.domain import JobStatus
from audio_recording_scribe.ingestion.scanner import InboxScanner, StableFileDetector
from audio_recording_scribe.pipeline.orchestrator import PipelineOrchestrator
from audio_recording_scribe.state.store import SQLiteJobStore


def test_scan_once_registers_ready_jobs_without_duplicates(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text("{}", encoding="utf-8")
    config = load_config(settings_path, base_dir=tmp_path)

    inbox = config.directories.inbox
    inbox.mkdir(parents=True)
    source = inbox / "diary.m4a"
    source.write_text("recording", encoding="utf-8")

    detector = StableFileDetector(stable_after_seconds=0, clock=time)
    scanner = InboxScanner(
        inbox_dir=inbox,
        supported_extensions=config.ingestion.supported_extensions,
        stable_detector=detector,
    )
    store = SQLiteJobStore(config.directories.state_db)
    orchestrator = PipelineOrchestrator(config=config, state_store=store, scanner=scanner)
    orchestrator.initialize()

    result = orchestrator.scan_once()
    repeat = orchestrator.scan_once()

    assert result.discovered_paths == (source.resolve(),)
    assert result.registered_jobs[0].status == JobStatus.READY
    assert result.ready_jobs[0].status == JobStatus.READY
    assert repeat.registered_jobs[0].id == result.registered_jobs[0].id
    assert orchestrator.ready_jobs() == [result.registered_jobs[0]]
    assert store.list_jobs() == [result.registered_jobs[0]]
