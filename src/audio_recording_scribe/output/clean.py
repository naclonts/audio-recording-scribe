"""Deterministic clean transcript assembly and output writing."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Sequence

from audio_recording_scribe.classification.heuristics import HeuristicLabel
from audio_recording_scribe.domain import SegmentLabel


@dataclass(frozen=True, slots=True)
class CleanTranscriptDocument:
    """Assembled clean transcript plus provenance."""

    text: str
    markdown: str
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WrittenCleanTranscript:
    """File paths for a written clean transcript."""

    text_path: Path
    markdown_path: Path
    provenance_path: Path


def deterministic_output_stem(source_path: Path) -> str:
    resolved = source_path.resolve()
    digest = sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    return f"{resolved.stem}-{digest}"


def assemble_clean_transcript(
    labels: Sequence[HeuristicLabel],
    *,
    source_path: Path,
    normalized_audio_path: Path | None = None,
    transcript_model: str | None = None,
) -> CleanTranscriptDocument:
    kept = tuple(label for label in labels if label.keep)
    text_lines = tuple(_normalize_segment_text(label.segment.text) for label in kept if label.segment.text.strip())
    text = "\n".join(text_lines)
    markdown_lines = ["# Clean Transcript", ""]
    if text_lines:
        markdown_lines.extend(f"- {line}" for line in text_lines)
    else:
        markdown_lines.append("_No retained speech segments._")

    provenance = {
        "source_path": str(source_path),
        "normalized_audio_path": str(normalized_audio_path) if normalized_audio_path else None,
        "transcript_model": transcript_model,
        "segment_count": len(labels),
        "kept_count": len(kept),
        "removed_count": sum(1 for label in labels if label.label == SegmentLabel.GPS_HIGH_CONFIDENCE),
        "labels": [
            {
                "start": label.segment.start,
                "end": label.segment.end,
                "text": label.segment.text,
                "label": str(label.label),
                "keep": label.keep,
                "matched_pattern": label.matched_pattern,
            }
            for label in labels
        ],
    }
    return CleanTranscriptDocument(text=text, markdown="\n".join(markdown_lines), provenance=provenance)


def write_clean_transcript(
    output_dir: Path,
    labels: Sequence[HeuristicLabel],
    *,
    source_path: Path,
    normalized_audio_path: Path | None = None,
    transcript_model: str | None = None,
) -> WrittenCleanTranscript:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = deterministic_output_stem(source_path)
    document = assemble_clean_transcript(
        labels,
        source_path=source_path,
        normalized_audio_path=normalized_audio_path,
        transcript_model=transcript_model,
    )
    text_path = output_dir / f"{stem}.txt"
    markdown_path = output_dir / f"{stem}.md"
    provenance_path = output_dir / f"{stem}.json"

    text_path.write_text(document.text, encoding="utf-8")
    markdown_path.write_text(document.markdown, encoding="utf-8")
    provenance_path.write_text(
        json.dumps(document.provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return WrittenCleanTranscript(
        text_path=text_path,
        markdown_path=markdown_path,
        provenance_path=provenance_path,
    )


def _normalize_segment_text(value: str) -> str:
    return " ".join(value.strip().split())
