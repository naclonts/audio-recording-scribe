"""Transcription package."""

from audio_recording_scribe.transcription.faster_whisper import (
    FasterWhisperTranscriber,
    TranscriptSegment,
    TranscriptionDependencyUnavailable,
    TranscriptionResult,
)

__all__ = [
    "FasterWhisperTranscriber",
    "TranscriptSegment",
    "TranscriptionDependencyUnavailable",
    "TranscriptionResult",
]
