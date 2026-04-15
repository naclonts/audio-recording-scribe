from __future__ import annotations

import json
from pathlib import Path

from audio_recording_scribe.classification.heuristics import classify_segments, load_gps_patterns
from audio_recording_scribe.output.clean import write_clean_transcript
from audio_recording_scribe.transcription.faster_whisper import TranscriptSegment


def test_clean_output_pipeline_preserves_diary_text_and_drops_navigation(tmp_path: Path) -> None:
    fixture_dir = Path("tests/fixtures")
    patterns = load_gps_patterns(fixture_dir / "gps_patterns.yaml")
    payload = json.loads((fixture_dir / "sample_segments.json").read_text(encoding="utf-8"))
    segments = [
        TranscriptSegment(start=item["start"], end=item["end"], text=item["text"])
        for item in payload
    ]

    labels = classify_segments(segments, patterns)
    written = write_clean_transcript(
        tmp_path / "outputs",
        labels,
        source_path=tmp_path / "recordings" / "drive-session.m4a",
        normalized_audio_path=tmp_path / "normalized" / "drive-session.wav",
        transcript_model="small",
    )

    text = written.text_path.read_text(encoding="utf-8")
    provenance = json.loads(written.provenance_path.read_text(encoding="utf-8"))

    assert "Turn right" not in text
    assert "I picked up coffee and read for a while." in text
    assert "I am heading to the park later." in text
    assert provenance["kept_count"] == 2
    assert provenance["removed_count"] == 1
