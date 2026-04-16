"""Managed source-file lifecycle helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from audio_recording_scribe.domain import ArtifactType
from audio_recording_scribe.paths import AppPaths
from audio_recording_scribe.state.models import JobRecord
from audio_recording_scribe.state.store import SQLiteJobStore


@dataclass(slots=True)
class SourceLifecycleManager:
    paths: AppPaths
    state_store: SQLiteJobStore

    def resolve_active_source_path(self, job: JobRecord) -> Path:
        artifact = self.state_store.get_latest_artifact(job.id, ArtifactType.SOURCE_AUDIO)
        if artifact is None:
            return job.source_path
        return artifact.path

    def stage_source_for_processing(self, job: JobRecord) -> Path:
        current_path = self.resolve_active_source_path(job)
        if not self._should_manage_source(job, current_path):
            return current_path
        target_path = self._managed_path(job, self.paths.processing)
        return self._move_and_record(job, current_path, target_path)

    def archive_source(self, job: JobRecord) -> Path:
        return self._relocate_managed_source(job, self.paths.archive)

    def move_source_to_failed(self, job: JobRecord) -> Path:
        return self._relocate_managed_source(job, self.paths.failed)

    def is_managed_source_path(self, path: Path) -> bool:
        resolved = path.expanduser().resolve()
        managed_directories = (
            self.paths.processing,
            self.paths.archive,
            self.paths.failed,
        )
        return any(resolved.is_relative_to(directory) for directory in managed_directories)

    def _relocate_managed_source(self, job: JobRecord, destination_dir: Path) -> Path:
        current_path = self.resolve_active_source_path(job)
        if not self.is_managed_source_path(current_path):
            return current_path
        target_path = self._managed_path(job, destination_dir)
        return self._move_and_record(job, current_path, target_path)

    def _should_manage_source(self, job: JobRecord, current_path: Path) -> bool:
        if self.is_managed_source_path(current_path):
            return True
        resolved_current_path = current_path.expanduser().resolve()
        resolved_original_path = job.source_path.expanduser().resolve()
        return (
            resolved_current_path == resolved_original_path
            and resolved_current_path.is_relative_to(self.paths.inbox)
        )

    def _move_and_record(
        self,
        job: JobRecord,
        current_path: Path,
        target_path: Path,
    ) -> Path:
        resolved_current_path = current_path.expanduser().resolve()
        if not resolved_current_path.exists():
            raise FileNotFoundError(resolved_current_path)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        if resolved_current_path != target_path:
            resolved_current_path.replace(target_path)

        artifact = self.state_store.record_artifact(job.id, ArtifactType.SOURCE_AUDIO, target_path)
        return artifact.path

    def _managed_path(self, job: JobRecord, destination_dir: Path) -> Path:
        return destination_dir / f"{job.id}-{job.source_path.name}"
