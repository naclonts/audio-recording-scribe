from __future__ import annotations

import json
from pathlib import Path

from audio_recording_scribe.classification.heuristics import classify_segments
from audio_recording_scribe.output.clean import (
    assemble_clean_transcript,
    deterministic_output_stem,
    write_clean_transcript,
)
from audio_recording_scribe.transcription.faster_whisper import TranscriptSegment


def test_deterministic_output_stem_is_stable(tmp_path: Path) -> None:
    source = tmp_path / "recordings" / "diary.m4a"
    source.parent.mkdir(parents=True)
    source.write_text("audio", encoding="utf-8")

    stem_one = deterministic_output_stem(source)
    stem_two = deterministic_output_stem(source)

    assert stem_one == stem_two


def test_assemble_clean_transcript_creates_text_markdown_and_provenance(tmp_path: Path) -> None:
    segments = classify_segments(
        [
            TranscriptSegment(start=0.0, end=1.0, text="I made pancakes today."),
            TranscriptSegment(start=1.0, end=2.0, text="Turn right in 500 feet."),
            TranscriptSegment(start=2.0, end=3.0, text="Then I called mom."),
        ]
    )

    document = assemble_clean_transcript(
        segments,
        source_path=tmp_path / "diary.m4a",
        normalized_audio_path=tmp_path / "normalized.wav",
        transcript_model="small",
    )

    assert "I made pancakes today." in document.text
    assert "Turn right" not in document.text
    assert document.markdown.startswith("# Clean Transcript")
    assert document.provenance["kept_count"] == 2
    assert document.provenance["removed_count"] == 1


def test_write_clean_transcript_writes_deterministic_files(tmp_path: Path) -> None:
    labels = classify_segments(
        [
            TranscriptSegment(start=0.0, end=1.0, text="I worked late."),
            TranscriptSegment(start=1.0, end=2.0, text="Turn left."),
        ]
    )

    written = write_clean_transcript(
        tmp_path / "outputs",
        labels,
        source_path=tmp_path / "recordings" / "diary.m4a",
        normalized_audio_path=tmp_path / "normalized.wav",
        transcript_model="small",
    )

    assert written.text_path.exists()
    assert written.markdown_path.exists()
    assert written.provenance_path.exists()
    assert written.text_path.suffix == ".txt"
    provenance = json.loads(written.provenance_path.read_text(encoding="utf-8"))
    assert provenance["kept_count"] == 1
