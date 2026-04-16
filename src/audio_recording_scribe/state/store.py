"""SQLite-backed job state store."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Sequence

from audio_recording_scribe.domain import ArtifactType, JobStatus
from audio_recording_scribe.state.models import ArtifactRecord, JobRecord


_JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.DISCOVERED: {JobStatus.READY, JobStatus.FAILED},
    JobStatus.READY: {
        JobStatus.NORMALIZING,
        JobStatus.FAILED,
    },
    JobStatus.NORMALIZING: {JobStatus.NORMALIZED, JobStatus.FAILED},
    JobStatus.NORMALIZED: {JobStatus.TRANSCRIBING, JobStatus.FAILED},
    JobStatus.TRANSCRIBING: {JobStatus.CLASSIFYING, JobStatus.FAILED},
    JobStatus.CLASSIFYING: {JobStatus.ASSEMBLING, JobStatus.FAILED},
    JobStatus.ASSEMBLING: {JobStatus.WRITING_OUTPUT, JobStatus.FAILED},
    JobStatus.WRITING_OUTPUT: {JobStatus.COMPLETED, JobStatus.FAILED},
    JobStatus.FAILED: {JobStatus.DISCOVERED, JobStatus.READY},
    JobStatus.COMPLETED: set(),
}


@dataclass(slots=True)
class SQLiteJobStore:
    db_path: Path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL UNIQUE,
                    file_hash TEXT UNIQUE,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    artifact_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(job_id, artifact_type, path)
                );

                CREATE TABLE IF NOT EXISTS segments (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    segment_index INTEGER NOT NULL,
                    start_sec REAL NOT NULL,
                    end_sec REAL NOT NULL,
                    speaker_label TEXT,
                    raw_text TEXT NOT NULL,
                    heuristic_label TEXT,
                    speaker_label_inference TEXT,
                    llm_label TEXT,
                    final_label TEXT,
                    confidence REAL,
                    UNIQUE(job_id, segment_index)
                );
                """
            )

    def register_job(
        self,
        source_path: Path,
        *,
        file_hash: str | None = None,
        status: JobStatus = JobStatus.DISCOVERED,
        error_message: str | None = None,
    ) -> JobRecord:
        source_path = source_path.expanduser().resolve()
        file_hash = file_hash or compute_file_hash(source_path)
        now = _utc_now()

        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            existing = self._fetch_job_by_source_path(connection, source_path)
            if existing is None and file_hash:
                existing = self._fetch_job_by_hash(connection, file_hash)

            if existing is not None:
                if existing.file_hash != file_hash and existing.status in {JobStatus.DISCOVERED, JobStatus.FAILED}:
                    connection.execute(
                        "UPDATE jobs SET file_hash = ?, updated_at = ? WHERE id = ?",
                        (file_hash, now.isoformat(), existing.id),
                    )
                    existing = self.get_job(existing.id, connection=connection)
                if existing.status == status and error_message == existing.error_message:
                    return existing
                return existing

            job_id = uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO jobs (id, source_path, file_hash, status, created_at, updated_at, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    str(source_path),
                    file_hash,
                    status.value,
                    now.isoformat(),
                    now.isoformat(),
                    error_message,
                ),
            )
            return self.get_job(job_id, connection=connection)

    def get_job(self, job_id: str, *, connection: sqlite3.Connection | None = None) -> JobRecord:
        if connection is None:
            with self._connect() as local_connection:
                return self.get_job(job_id, connection=local_connection)
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return _job_from_row(row)

    def get_job_by_source_path(self, source_path: Path) -> JobRecord | None:
        source_path = source_path.expanduser().resolve()
        with self._connect() as connection:
            return self._fetch_job_by_source_path(connection, source_path)

    def list_jobs(self, *, status: JobStatus | None = None) -> list[JobRecord]:
        query = "SELECT * FROM jobs"
        params: Sequence[object] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status.value,)
        query += " ORDER BY created_at ASC, source_path ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_job_from_row(row) for row in rows]

    def list_ready_jobs(self) -> list[JobRecord]:
        return self.list_jobs(status=JobStatus.READY)

    def transition_job(
        self,
        job_id: str,
        new_status: JobStatus,
        *,
        error_message: str | None = None,
    ) -> JobRecord:
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            current = self.get_job(job_id, connection=connection)
            if current.status == new_status and error_message == current.error_message:
                return current
            allowed_targets = _JOB_TRANSITIONS.get(current.status, set())
            if new_status not in allowed_targets:
                raise ValueError(f"invalid transition from {current.status} to {new_status}")
            now = _utc_now().isoformat()
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error_message = ?
                WHERE id = ?
                """,
                (new_status.value, now, error_message, job_id),
            )
            return self.get_job(job_id, connection=connection)

    def mark_failed(self, job_id: str, error_message: str) -> JobRecord:
        return self.transition_job(job_id, JobStatus.FAILED, error_message=error_message)

    def record_artifact(
        self,
        job_id: str,
        artifact_type: ArtifactType,
        path: Path,
    ) -> ArtifactRecord:
        path = path.expanduser().resolve()
        artifact_id = uuid.uuid4().hex
        created_at = _utc_now().isoformat()
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT OR REPLACE INTO artifacts (id, job_id, artifact_type, path, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (artifact_id, job_id, artifact_type.value, str(path), created_at),
            )
            row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise RuntimeError("artifact insert unexpectedly missing")
        return _artifact_from_row(row)

    def list_artifacts(
        self,
        job_id: str,
        *,
        artifact_type: ArtifactType | None = None,
    ) -> list[ArtifactRecord]:
        query = "SELECT * FROM artifacts WHERE job_id = ?"
        params: list[object] = [job_id]
        if artifact_type is not None:
            query += " AND artifact_type = ?"
            params.append(artifact_type.value)
        query += " ORDER BY rowid ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_artifact_from_row(row) for row in rows]

    def get_latest_artifact(
        self,
        job_id: str,
        artifact_type: ArtifactType,
    ) -> ArtifactRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM artifacts
                WHERE job_id = ? AND artifact_type = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (job_id, artifact_type.value),
            ).fetchone()
        return None if row is None else _artifact_from_row(row)

    def close(self) -> None:
        """Kept for API symmetry with future long-lived implementations."""

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _fetch_job_by_source_path(
        self,
        connection: sqlite3.Connection,
        source_path: Path,
    ) -> JobRecord | None:
        row = connection.execute("SELECT * FROM jobs WHERE source_path = ?", (str(source_path),)).fetchone()
        return None if row is None else _job_from_row(row)

    def _fetch_job_by_hash(self, connection: sqlite3.Connection, file_hash: str) -> JobRecord | None:
        row = connection.execute("SELECT * FROM jobs WHERE file_hash = ?", (file_hash,)).fetchone()
        return None if row is None else _job_from_row(row)


def compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _job_from_row(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        source_path=Path(row["source_path"]),
        file_hash=row["file_hash"],
        status=JobStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        error_message=row["error_message"],
    )


def _artifact_from_row(row: sqlite3.Row) -> ArtifactRecord:
    return ArtifactRecord(
        id=row["id"],
        job_id=row["job_id"],
        artifact_type=ArtifactType(row["artifact_type"]),
        path=Path(row["path"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)
