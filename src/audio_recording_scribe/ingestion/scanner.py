"""Polling inbox scanner and stable-file detector."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Callable

from audio_recording_scribe.ingestion.models import FileSnapshot

Clock = Callable[[], float]


@dataclass(slots=True)
class StableFileDetector:
    stable_after_seconds: int
    clock: Clock = time
    _observations: dict[Path, tuple[FileSnapshot, float]] = field(default_factory=dict, init=False, repr=False)

    def snapshot(self, path: Path) -> FileSnapshot:
        stat = path.stat()
        return FileSnapshot(path=path.resolve(), size=stat.st_size, mtime_ns=stat.st_mtime_ns)

    def is_stable(self, path: Path) -> bool:
        resolved = path.resolve()
        current = self.snapshot(resolved)
        observed = self._observations.get(resolved)
        now = self.clock()
        if observed is None or observed[0].size != current.size or observed[0].mtime_ns != current.mtime_ns:
            self._observations[resolved] = (current, now)
            age_seconds = now - (current.mtime_ns / 1_000_000_000)
            return age_seconds >= self.stable_after_seconds
        return now - observed[1] >= self.stable_after_seconds


@dataclass(slots=True)
class InboxScanner:
    inbox_dir: Path
    supported_extensions: tuple[str, ...]
    stable_detector: StableFileDetector
    recursive: bool = False

    def discover_supported_files(self) -> list[Path]:
        if not self.inbox_dir.exists():
            return []
        iterator = self.inbox_dir.rglob("*") if self.recursive else self.inbox_dir.iterdir()
        supported = [
            path.resolve()
            for path in iterator
            if path.is_file() and path.suffix.lower() in self.supported_extensions
        ]
        return sorted(supported, key=lambda path: str(path))

    def discover_stable_files(self) -> list[Path]:
        stable_files: list[Path] = []
        for path in self.discover_supported_files():
            if self.stable_detector.is_stable(path):
                stable_files.append(path)
        return stable_files
