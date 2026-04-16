from __future__ import annotations

from pathlib import Path
from time import time

from audio_recording_scribe.config import load_config
from audio_recording_scribe.domain import ArtifactType, JobStatus
from audio_recording_scribe.ingestion.scanner import InboxScanner, StableFileDetector
from audio_recording_scribe.ingestion.source_lifecycle import SourceLifecycleManager
from audio_recording_scribe.paths import AppPaths
from audio_recording_scribe.pipeline.orchestrator import PipelineOrchestrator
from audio_recording_scribe.state.store import SQLiteJobStore


def test_managed_source_file_moves_through_processing_failed_retry_and_archive(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text("{}", encoding="utf-8")
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
    paths.ensure_runtime_directories()

    source = paths.inbox / "retry.m4a"
    source.write_text("recording", encoding="utf-8")

    detector = StableFileDetector(stable_after_seconds=0, clock=time)
    scanner = InboxScanner(
        inbox_dir=paths.inbox,
        supported_extensions=config.ingestion.supported_extensions,
        stable_detector=detector,
    )
    store = SQLiteJobStore(paths.state_db)
    orchestrator = PipelineOrchestrator(config=config, state_store=store, scanner=scanner)
    orchestrator.initialize()

    job = orchestrator.scan_once().registered_jobs[0]
    lifecycle = SourceLifecycleManager(paths=paths, state_store=store)

    staged_path = lifecycle.stage_source_for_processing(job)
    failed_path = lifecycle.move_source_to_failed(job)
    store.mark_failed(job.id, "downstream unavailable")
    retried_job = orchestrator.retry_failed_job(job.id)
    restaged_path = lifecycle.stage_source_for_processing(retried_job)
    archived_path = lifecycle.archive_source(retried_job)

    assert job.status == JobStatus.READY
    assert retried_job.status == JobStatus.READY
    assert job.source_path == source.resolve()

    assert staged_path == paths.processing / f"{job.id}-retry.m4a"
    assert failed_path == paths.failed / f"{job.id}-retry.m4a"
    assert restaged_path == staged_path
    assert archived_path == paths.archive / f"{job.id}-retry.m4a"

    assert not job.source_path.exists()
    assert not paths.processing.joinpath(f"{job.id}-retry.m4a").exists()
    assert not failed_path.exists()
    assert archived_path.read_text(encoding="utf-8") == "recording"

    assert lifecycle.resolve_active_source_path(retried_job) == archived_path
    assert store.get_latest_artifact(job.id, ArtifactType.SOURCE_AUDIO).path == archived_path
    assert [
        artifact.path for artifact in store.list_artifacts(job.id, artifact_type=ArtifactType.SOURCE_AUDIO)
    ] == [
        failed_path,
        staged_path,
        archived_path,
    ]
