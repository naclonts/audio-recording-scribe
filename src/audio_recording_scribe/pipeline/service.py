"""Parent-owned pipeline wiring across ingestion, state, and processing lanes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from time import sleep
from typing import Sequence

from audio_recording_scribe.audio import normalize_audio
from audio_recording_scribe.classification import HeuristicLabel, classify_segments, load_gps_patterns
from audio_recording_scribe.config import AppConfig
from audio_recording_scribe.domain import ArtifactType, JobStatus
from audio_recording_scribe.ingestion import InboxScanner, StableFileDetector
from audio_recording_scribe.ingestion.source_lifecycle import SourceLifecycleManager
from audio_recording_scribe.logging import get_logger
from audio_recording_scribe.output import deterministic_output_stem, write_clean_transcript
from audio_recording_scribe.paths import AppPaths
from audio_recording_scribe.pipeline.orchestrator import PipelineOrchestrator
from audio_recording_scribe.state import JobRecord, SQLiteJobStore
from audio_recording_scribe.transcription import (
    FasterWhisperTranscriber,
    TranscriptionResult,
)


@dataclass
class PipelineService:
    config: AppConfig
    paths: AppPaths

    def __post_init__(self) -> None:
        self.logger = get_logger("audio_recording_scribe.pipeline")
        self.state_store = SQLiteJobStore(self.paths.state_db)
        self.scanner = InboxScanner(
            inbox_dir=self.paths.inbox,
            supported_extensions=self.config.ingestion.supported_extensions,
            stable_detector=StableFileDetector(
                stable_after_seconds=self.config.ingestion.stable_file_seconds
            ),
        )
        self.orchestrator = PipelineOrchestrator(
            config=self.config,
            state_store=self.state_store,
            scanner=self.scanner,
        )
        self.source_lifecycle = SourceLifecycleManager(paths=self.paths, state_store=self.state_store)
        self._transcriber: FasterWhisperTranscriber | None = None

    def scan_once(self) -> int:
        self._prepare_runtime()
        self.orchestrator.initialize()
        result = self.orchestrator.scan_once()
        processed_count, failed_count = self._process_ready_jobs(result.ready_jobs)
        self.logger.info(
            "scan-once complete: discovered=%s ready=%s processed=%s failed=%s",
            len(result.discovered_paths),
            len(result.ready_jobs),
            processed_count,
            failed_count,
        )
        return 1 if failed_count else 0

    def watch(self, *, interval_seconds: int | None = None) -> int:
        effective_interval = interval_seconds or self.config.ingestion.polling_interval_seconds
        self.logger.info("watch loop starting; polling interval=%s seconds", effective_interval)
        try:
            while True:
                self.scan_once()
                sleep(effective_interval)
        except KeyboardInterrupt:
            self.logger.info("watch loop interrupted")
        return 0

    def process(self, *, source: Path) -> int:
        self._prepare_runtime()
        self.orchestrator.initialize()
        source_path = source.expanduser().resolve()
        if not source_path.exists():
            self.logger.error("source file does not exist: %s", source_path)
            return 1
        job = self.orchestrator.register_discovered_file(source_path)
        return 0 if self._process_job(job) else 1

    def retry(self, *, job_id: str) -> int:
        self._prepare_runtime()
        self.orchestrator.initialize()
        try:
            job = self.orchestrator.retry_failed_job(job_id)
        except KeyError:
            self.logger.error("job not found: %s", job_id)
            return 1
        return 0 if self._process_job(job) else 1

    def _prepare_runtime(self) -> None:
        self.paths.ensure_runtime_directories()

    def _process_ready_jobs(self, jobs: Sequence[JobRecord]) -> tuple[int, int]:
        processed_count = 0
        failed_count = 0
        for job in jobs:
            if self._process_job(job):
                processed_count += 1
            else:
                failed_count += 1
        return processed_count, failed_count

    def _process_job(self, job: JobRecord) -> bool:
        if job.status == JobStatus.COMPLETED:
            self.logger.info("job already completed; skipping: job_id=%s", job.id)
            return True

        current_job = job
        try:
            self.logger.info("processing job_id=%s source=%s", job.id, job.source_path)
            current_job = self._transition(current_job, JobStatus.NORMALIZING)
            active_source_path = self.source_lifecycle.stage_source_for_processing(current_job)
            normalized = normalize_audio(
                active_source_path,
                self.paths.normalized,
                ffmpeg_binary=self.config.audio.ffmpeg_binary,
                sample_rate_hz=self.config.audio.target_sample_rate_hz,
                channels=self.config.audio.target_channels,
                codec=self.config.audio.pcm_codec,
            )
            self.state_store.record_artifact(
                current_job.id,
                ArtifactType.NORMALIZED_AUDIO,
                normalized.output_path,
            )

            current_job = self._transition(current_job, JobStatus.NORMALIZED)
            current_job = self._transition(current_job, JobStatus.TRANSCRIBING)
            transcription = self._get_transcriber().transcribe(normalized.output_path)
            transcript_path = self._write_transcript_segments(current_job.source_path, transcription)
            self.state_store.record_artifact(
                current_job.id,
                ArtifactType.TRANSCRIPT_SEGMENTS_JSON,
                transcript_path,
            )

            current_job = self._transition(current_job, JobStatus.CLASSIFYING)
            labels = classify_segments(
                transcription.segments,
                load_gps_patterns(self.paths.gps_patterns),
                uncertain_max_words=self.config.classification.uncertain_max_words,
            )
            labels_path = self._write_label_metadata(current_job.source_path, labels)
            self.state_store.record_artifact(
                current_job.id,
                ArtifactType.FILTERED_SEGMENTS_JSON,
                labels_path,
            )

            current_job = self._transition(current_job, JobStatus.ASSEMBLING)
            current_job = self._transition(current_job, JobStatus.WRITING_OUTPUT)
            written = write_clean_transcript(
                self.paths.outputs,
                labels,
                source_path=current_job.source_path,
                normalized_audio_path=normalized.output_path,
                transcript_model=transcription.model_name,
            )
            self.state_store.record_artifact(current_job.id, ArtifactType.CLEAN_TEXT, written.text_path)
            self.state_store.record_artifact(
                current_job.id,
                ArtifactType.CLEAN_MARKDOWN,
                written.markdown_path,
            )
            self.state_store.record_artifact(
                current_job.id,
                ArtifactType.METADATA_JSON,
                written.provenance_path,
            )
            self.source_lifecycle.archive_source(current_job)
            self.state_store.transition_job(current_job.id, JobStatus.COMPLETED)
            self.logger.info("job completed: job_id=%s", current_job.id)
            return True
        except Exception as exc:
            try:
                failed_source_path = self.source_lifecycle.move_source_to_failed(current_job)
                self.logger.info(
                    "moved failed source for job_id=%s to %s",
                    current_job.id,
                    failed_source_path,
                )
            except Exception:
                self.logger.exception("unable to move failed source for job_id=%s", current_job.id)
            self.state_store.mark_failed(job.id, str(exc))
            self.logger.exception("job failed: job_id=%s", job.id)
            return False

    def _transition(self, job: JobRecord, target: JobStatus) -> JobRecord:
        return self.state_store.transition_job(job.id, target)

    def _get_transcriber(self) -> FasterWhisperTranscriber:
        if self._transcriber is None:
            self._transcriber = FasterWhisperTranscriber(
                model_size=self.config.transcription.model_size,
                model_cache_dir=self.config.transcription.model_cache_dir,
                device=self.config.transcription.device,
                compute_type=self.config.transcription.compute_type,
                language=self.config.transcription.language,
                vad_filter=self.config.transcription.vad_filter,
            )
        return self._transcriber

    def _write_transcript_segments(
        self,
        source_path: Path,
        transcription: TranscriptionResult,
    ) -> Path:
        output_path = self.paths.metadata / f"{deterministic_output_stem(source_path)}-transcript.json"
        payload = {
            "language": transcription.language,
            "model_name": transcription.model_name,
            "provider": transcription.provider,
            "segments": [
                {
                    "end": segment.end,
                    "probability": segment.probability,
                    "start": segment.start,
                    "text": segment.text,
                }
                for segment in transcription.segments
            ],
            "source_path": str(source_path),
        }
        self._write_json(output_path, payload)
        return output_path

    def _write_label_metadata(
        self,
        source_path: Path,
        labels: Sequence[HeuristicLabel],
    ) -> Path:
        output_path = self.paths.metadata / f"{deterministic_output_stem(source_path)}-labels.json"
        payload = {
            "labels": [
                {
                    "end": label.segment.end,
                    "keep": label.keep,
                    "label": label.label.value,
                    "matched_pattern": label.matched_pattern,
                    "start": label.segment.start,
                    "text": label.segment.text,
                }
                for label in labels
            ],
            "source_path": str(source_path),
        }
        self._write_json(output_path, payload)
        return output_path

    def _write_json(self, output_path: Path, payload: dict[str, object]) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
