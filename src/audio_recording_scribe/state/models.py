"""Persistence models for job state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from audio_recording_scribe.domain import ArtifactType, JobStatus


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: str
    source_path: Path
    file_hash: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    id: str
    job_id: str
    artifact_type: ArtifactType
    path: Path
    created_at: datetime
