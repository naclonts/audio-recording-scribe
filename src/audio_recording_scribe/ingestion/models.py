"""Ingestion model helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    path: Path
    size: int
    mtime_ns: int
