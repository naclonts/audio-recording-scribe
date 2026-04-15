"""Shared domain enums owned by the parent agent."""

from enum import StrEnum


class JobStatus(StrEnum):
    DISCOVERED = "discovered"
    READY = "ready"
    NORMALIZING = "normalizing"
    NORMALIZED = "normalized"
    TRANSCRIBING = "transcribing"
    CLASSIFYING = "classifying"
    ASSEMBLING = "assembling"
    WRITING_OUTPUT = "writing_output"
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactType(StrEnum):
    SOURCE_AUDIO = "source_audio"
    NORMALIZED_AUDIO = "normalized_audio"
    TRANSCRIPT_SEGMENTS_JSON = "transcript_segments_json"
    FILTERED_SEGMENTS_JSON = "filtered_segments_json"
    CLEAN_TEXT = "clean_text"
    CLEAN_MARKDOWN = "clean_markdown"
    METADATA_JSON = "metadata_json"


class SegmentLabel(StrEnum):
    GPS_HIGH_CONFIDENCE = "gps_high_confidence"
    NOT_GPS = "not_gps"
    UNCERTAIN = "uncertain"

