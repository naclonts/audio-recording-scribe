"""Heuristic GPS/system speech filtering."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Sequence

import yaml

from audio_recording_scribe.domain import SegmentLabel
from audio_recording_scribe.transcription.faster_whisper import TranscriptSegment

DEFAULT_GPS_PHRASES: tuple[str, ...] = (
    "turn left",
    "turn right",
    "continue straight",
    "in 500 feet",
    "in 1000 feet",
    "your destination is on the",
    "take the exit",
    "merge onto",
    "recalculating route",
    "rerouting",
    "make a u-turn",
    "keep left",
    "keep right",
    "at the roundabout",
    "head north",
    "head south",
    "head east",
    "head west",
    "use the left lane",
    "use the right lane",
)

NAV_TOKENS: frozenset[str] = frozenset(
    {
        "turn",
        "left",
        "right",
        "straight",
        "destination",
        "route",
        "exit",
        "merge",
        "lane",
        "recalculating",
        "rerouting",
        "arriving",
        "roundabout",
        "feet",
        "meters",
        "meter",
        "mile",
        "miles",
        "u-turn",
    }
)


@dataclass(frozen=True, slots=True)
class GpsPatternSet:
    phrases: tuple[str, ...]
    regexes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HeuristicLabel:
    segment: TranscriptSegment
    label: SegmentLabel
    keep: bool
    matched_pattern: str | None = None


def load_gps_patterns(pattern_path: Path | None) -> GpsPatternSet:
    if pattern_path is None or not pattern_path.exists():
        return GpsPatternSet(phrases=DEFAULT_GPS_PHRASES)

    raw = yaml.safe_load(pattern_path.read_text(encoding="utf-8")) or {}
    if isinstance(raw, list):
        return GpsPatternSet(phrases=tuple(str(item) for item in raw))

    phrases = tuple(str(item) for item in raw.get("phrases", DEFAULT_GPS_PHRASES))
    regexes = tuple(str(item) for item in raw.get("regexes", ()))
    return GpsPatternSet(phrases=phrases, regexes=regexes)


def classify_segment(
    segment: TranscriptSegment,
    patterns: GpsPatternSet | None = None,
    *,
    uncertain_max_words: int = 12,
) -> HeuristicLabel:
    patterns = patterns or GpsPatternSet(phrases=DEFAULT_GPS_PHRASES)
    normalized = _normalize_text(segment.text)

    match = _match_pattern(normalized, patterns)
    if match is not None:
        return HeuristicLabel(segment=segment, label=SegmentLabel.GPS_HIGH_CONFIDENCE, keep=False, matched_pattern=match)

    if _looks_nav_like(normalized, uncertain_max_words=uncertain_max_words):
        return HeuristicLabel(segment=segment, label=SegmentLabel.UNCERTAIN, keep=True)

    return HeuristicLabel(segment=segment, label=SegmentLabel.NOT_GPS, keep=True)


def classify_segments(
    segments: Sequence[TranscriptSegment],
    patterns: GpsPatternSet | None = None,
    *,
    uncertain_max_words: int = 12,
) -> tuple[HeuristicLabel, ...]:
    return tuple(
        classify_segment(segment, patterns, uncertain_max_words=uncertain_max_words)
        for segment in segments
    )


def filter_kept_segments(labels: Sequence[HeuristicLabel]) -> tuple[TranscriptSegment, ...]:
    return tuple(label.segment for label in labels if label.keep)


def _match_pattern(normalized_text: str, patterns: GpsPatternSet) -> str | None:
    for phrase in patterns.phrases:
        normalized_phrase = _normalize_text(phrase)
        if normalized_phrase and normalized_phrase in normalized_text:
            return phrase
    for pattern in patterns.regexes:
        if re.search(pattern, normalized_text, flags=re.IGNORECASE):
            return pattern
    return None


def _looks_nav_like(normalized_text: str, *, uncertain_max_words: int) -> bool:
    words = normalized_text.split()
    if not words or len(words) > uncertain_max_words:
        return False
    return any(token in normalized_text for token in NAV_TOKENS)


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s'-]+", " ", lowered)).strip()
