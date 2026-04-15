from __future__ import annotations

from pathlib import Path
from time import time

from audio_recording_scribe.config import load_config
from audio_recording_scribe.domain import JobStatus
from audio_recording_scribe.ingestion.scanner import InboxScanner, StableFileDetector
from audio_recording_scribe.pipeline.orchestrator import PipelineOrchestrator
from audio_recording_scribe.state.store import SQLiteJobStore


def test_scan_retry_requeues_failed_jobs_without_creating_duplicates(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text("{}", encoding="utf-8")
    config = load_config(settings_path, base_dir=tmp_path)

    inbox = config.directories.inbox
    inbox.mkdir(parents=True)
    source = inbox / "retry.m4a"
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

    first = orchestrator.scan_once().registered_jobs[0]
    failed = store.mark_failed(first.id, "downstream unavailable")
    retried = orchestrator.scan_once().registered_jobs[0]

    assert failed.status == JobStatus.FAILED
    assert retried.id == first.id
    assert retried.status == JobStatus.READY
    assert store.list_jobs() == [retried]
