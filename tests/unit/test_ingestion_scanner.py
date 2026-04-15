from __future__ import annotations

from pathlib import Path
from time import time

from audio_recording_scribe.ingestion.scanner import InboxScanner, StableFileDetector


def test_stable_file_detector_uses_size_and_mtime_snapshots(tmp_path: Path) -> None:
    clock_value = [0.0]

    def clock() -> float:
        return clock_value[0]

    detector = StableFileDetector(stable_after_seconds=10, clock=clock)
    source = tmp_path / "clip.m4a"
    source.write_text("a", encoding="utf-8")

    assert detector.is_stable(source) is False

    clock_value[0] = 11.0
    assert detector.is_stable(source) is True

    source.write_text("aa", encoding="utf-8")
    clock_value[0] = 12.0
    assert detector.is_stable(source) is False


def test_inbox_scanner_filters_supported_extensions_and_sorts_deterministically(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "b.txt").write_text("ignore", encoding="utf-8")
    (inbox / "b.M4A").write_text("two", encoding="utf-8")
    (inbox / "a.wav").write_text("one", encoding="utf-8")

    detector = StableFileDetector(stable_after_seconds=0, clock=lambda: time())
    scanner = InboxScanner(
        inbox_dir=inbox,
        supported_extensions=(".m4a", ".wav"),
        stable_detector=detector,
    )

    assert scanner.discover_supported_files() == [inbox / "a.wav", inbox / "b.M4A"]
    assert scanner.discover_stable_files() == [inbox / "a.wav", inbox / "b.M4A"]
