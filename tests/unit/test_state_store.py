from __future__ import annotations

from pathlib import Path

import pytest

from audio_recording_scribe.domain import JobStatus
from audio_recording_scribe.state.store import SQLiteJobStore


def test_register_job_is_idempotent_by_path_and_hash(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "jobs.sqlite3"
    store = SQLiteJobStore(db_path)
    store.initialize()

    first_source = tmp_path / "inbox" / "diary.m4a"
    first_source.parent.mkdir(parents=True)
    first_source.write_text("hello world", encoding="utf-8")

    first = store.register_job(first_source)
    second = store.register_job(first_source)

    duplicate_source = tmp_path / "inbox" / "duplicate.m4a"
    duplicate_source.write_text("hello world", encoding="utf-8")
    third = store.register_job(duplicate_source)

    assert first.id == second.id == third.id
    assert store.list_jobs() == [first]
    assert first.status == JobStatus.DISCOVERED


def test_transition_job_enforces_allowed_status_changes(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "jobs.sqlite3"
    store = SQLiteJobStore(db_path)
    store.initialize()

    source = tmp_path / "inbox" / "drive.m4a"
    source.parent.mkdir(parents=True)
    source.write_text("drive", encoding="utf-8")

    job = store.register_job(source)
    ready = store.transition_job(job.id, JobStatus.READY)
    normalizing = store.transition_job(job.id, JobStatus.NORMALIZING)
    failed = store.mark_failed(job.id, "ffmpeg unavailable")

    assert ready.status == JobStatus.READY
    assert normalizing.status == JobStatus.NORMALIZING
    assert failed.status == JobStatus.FAILED
    assert failed.error_message == "ffmpeg unavailable"

    with pytest.raises(ValueError):
        store.transition_job(job.id, JobStatus.COMPLETED)
