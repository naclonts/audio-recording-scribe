"""Runtime path helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppPaths:
    root: Path
    inbox: Path
    processing: Path
    archive: Path
    failed: Path
    normalized: Path
    outputs: Path
    metadata: Path
    logs: Path
    state_db: Path
    gps_patterns: Path

    @property
    def app_log_file(self) -> Path:
        return self.logs / "audio-recording-scribe.log"

    def ensure_runtime_directories(self) -> None:
        for directory in (
            self.inbox,
            self.processing,
            self.archive,
            self.failed,
            self.normalized,
            self.outputs,
            self.metadata,
            self.logs,
            self.state_db.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)

