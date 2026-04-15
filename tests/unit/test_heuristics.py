from __future__ import annotations

from pathlib import Path

from audio_recording_scribe.classification.heuristics import (
    GpsPatternSet,
    classify_segment,
    classify_segments,
    filter_kept_segments,
    load_gps_patterns,
)
from audio_recording_scribe.domain import SegmentLabel
from audio_recording_scribe.transcription.faster_whisper import TranscriptSegment


def test_load_gps_patterns_uses_yaml_fixture() -> None:
    patterns = load_gps_patterns(Path("tests/fixtures/gps_patterns.yaml"))

    assert "turn left" in patterns.phrases
    assert patterns.regexes


def test_classify_segment_labels_obvious_navigation_as_gps() -> None:
    segment = TranscriptSegment(start=0.0, end=2.0, text="Turn right in 500 feet.")

    label = classify_segment(segment, GpsPatternSet(phrases=("turn right",)))

    assert label.label == SegmentLabel.GPS_HIGH_CONFIDENCE
    assert label.keep is False


def test_classify_segment_keeps_diary_and_marks_short_route_like_text_uncertain() -> None:
    diary = TranscriptSegment(start=0.0, end=2.0, text="I had coffee and wrote notes.")
    short_route = TranscriptSegment(start=2.0, end=3.0, text="turn now")

    labels = classify_segments([diary, short_route])

    assert labels[0].label == SegmentLabel.NOT_GPS
    assert labels[0].keep is True
    assert labels[1].label == SegmentLabel.UNCERTAIN
    assert labels[1].keep is True


def test_filter_kept_segments_removes_only_high_confidence_gps() -> None:
    segments = [
        TranscriptSegment(start=0.0, end=1.0, text="I went home."),
        TranscriptSegment(start=1.0, end=2.0, text="Turn left."),
    ]
    labels = classify_segments(segments)

    kept = filter_kept_segments(labels)

    assert [segment.text for segment in kept] == ["I went home."]
