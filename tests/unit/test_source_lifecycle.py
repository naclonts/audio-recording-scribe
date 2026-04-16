from __future__ import annotations

from pathlib import Path

from audio_recording_scribe.domain import ArtifactType
from audio_recording_scribe.ingestion.source_lifecycle import SourceLifecycleManager
from audio_recording_scribe.paths import AppPaths
from audio_recording_scribe.state.store import SQLiteJobStore


def test_store_returns_latest_source_audio_artifact(tmp_path: Path) -> None:
    paths = build_paths(tmp_path)
    store = SQLiteJobStore(paths.state_db)
    store.initialize()

    source = paths.inbox / "diary.m4a"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("hello", encoding="utf-8")
    job = store.register_job(source)

    processing_artifact = store.record_artifact(
        job.id,
        ArtifactType.SOURCE_AUDIO,
        paths.processing / f"{job.id}-diary.m4a",
    )
    store.record_artifact(
        job.id,
        ArtifactType.NORMALIZED_AUDIO,
        paths.normalized / "diary.wav",
    )
    failed_artifact = store.record_artifact(
        job.id,
        ArtifactType.SOURCE_AUDIO,
        paths.failed / f"{job.id}-diary.m4a",
    )

    assert store.list_artifacts(job.id, artifact_type=ArtifactType.SOURCE_AUDIO) == [
        processing_artifact,
        failed_artifact,
    ]
    assert store.get_latest_artifact(job.id, ArtifactType.SOURCE_AUDIO) == failed_artifact


def test_stage_source_for_processing_moves_inbox_source_and_keeps_job_source_path(tmp_path: Path) -> None:
    paths = build_paths(tmp_path)
    store = SQLiteJobStore(paths.state_db)
    store.initialize()

    source = paths.inbox / "drive.m4a"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("recording", encoding="utf-8")
    job = store.register_job(source)

    lifecycle = SourceLifecycleManager(paths=paths, state_store=store)
    staged_path = lifecycle.stage_source_for_processing(job)

    assert staged_path == paths.processing / f"{job.id}-drive.m4a"
    assert job.source_path == source.resolve()
    assert not source.exists()
    assert staged_path.read_text(encoding="utf-8") == "recording"
    assert store.get_latest_artifact(job.id, ArtifactType.SOURCE_AUDIO).path == staged_path
    assert lifecycle.resolve_active_source_path(job) == staged_path


def test_stage_source_for_processing_leaves_unmanaged_paths_in_place(tmp_path: Path) -> None:
    paths = build_paths(tmp_path)
    store = SQLiteJobStore(paths.state_db)
    store.initialize()

    source = tmp_path / "imports" / "voice-note.m4a"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("external recording", encoding="utf-8")
    job = store.register_job(source)

    lifecycle = SourceLifecycleManager(paths=paths, state_store=store)
    staged_path = lifecycle.stage_source_for_processing(job)

    assert staged_path == source.resolve()
    assert source.exists()
    assert store.get_latest_artifact(job.id, ArtifactType.SOURCE_AUDIO) is None


def build_paths(root: Path) -> AppPaths:
    paths = AppPaths(
        root=root,
        inbox=root / "data" / "inbox",
        processing=root / "data" / "processing",
        archive=root / "data" / "archive",
        failed=root / "data" / "failed",
        normalized=root / "data" / "normalized",
        outputs=root / "data" / "outputs",
        metadata=root / "data" / "metadata",
        logs=root / "data" / "logs",
        state_db=root / "data" / "state" / "jobs.sqlite3",
        gps_patterns=root / "config" / "gps_patterns.yaml",
    )
    paths.ensure_runtime_directories()
    return paths
