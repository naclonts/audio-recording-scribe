"""Pipeline orchestration primitives for discovery and state registration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from audio_recording_scribe.config import AppConfig
from audio_recording_scribe.domain import JobStatus
from audio_recording_scribe.ingestion.scanner import InboxScanner
from audio_recording_scribe.state.models import JobRecord
from audio_recording_scribe.state.store import SQLiteJobStore


@dataclass(slots=True)
class ScanResult:
    discovered_paths: tuple[Path, ...]
    registered_jobs: tuple[JobRecord, ...]
    ready_jobs: tuple[JobRecord, ...]


@dataclass(slots=True)
class PipelineOrchestrator:
    config: AppConfig
    state_store: SQLiteJobStore
    scanner: InboxScanner

    def initialize(self) -> None:
        self.state_store.initialize()

    def scan_once(self) -> ScanResult:
        discovered_paths = tuple(self.scanner.discover_stable_files())
        registered_jobs = tuple(self.register_discovered_file(path) for path in discovered_paths)
        ready_jobs = tuple(self.state_store.list_ready_jobs())
        return ScanResult(
            discovered_paths=discovered_paths,
            registered_jobs=registered_jobs,
            ready_jobs=ready_jobs,
        )

    def register_discovered_file(self, source_path: Path) -> JobRecord:
        job = self.state_store.register_job(source_path, status=JobStatus.DISCOVERED)
        if job.status in {
            JobStatus.COMPLETED,
            JobStatus.NORMALIZING,
            JobStatus.NORMALIZED,
            JobStatus.TRANSCRIBING,
            JobStatus.CLASSIFYING,
            JobStatus.ASSEMBLING,
            JobStatus.WRITING_OUTPUT,
        }:
            return job
        if job.status == JobStatus.READY:
            return job
        return self.state_store.transition_job(job.id, JobStatus.READY)

    def ready_jobs(self) -> list[JobRecord]:
        return self.state_store.list_ready_jobs()

    def retry_failed_job(self, job_id: str) -> JobRecord:
        return self.state_store.transition_job(job_id, JobStatus.READY)
