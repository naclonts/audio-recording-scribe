"""Base CLI entrypoint for the processing pipeline."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Sequence

from audio_recording_scribe import __version__
from audio_recording_scribe.config import infer_base_dir, load_config
from audio_recording_scribe.domain import JobStatus
from audio_recording_scribe.ingestion.drive import (
    GoogleDriveDownloadError,
    UnsupportedGoogleDriveLinkError,
    build_google_drive_download_request,
    download_google_drive_file,
    parse_google_drive_url,
)
from audio_recording_scribe.logging import configure_logging
from audio_recording_scribe.paths import AppPaths
from audio_recording_scribe.pipeline.service import PipelineService
from audio_recording_scribe.transcription.runtime_checks import probe_transcription_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="audio-recording-scribe")
    parser.add_argument("--config", type=Path, help="Path to a YAML settings file.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("scan-once", help="Discover stable files and enqueue them once.")

    watch_parser = subparsers.add_parser("watch", help="Poll the inbox continuously.")
    watch_parser.add_argument(
        "--interval-seconds",
        type=int,
        help="Override the polling interval from configuration.",
    )

    process_parser = subparsers.add_parser("process", help="Process a single source file.")
    process_parser.add_argument("source", type=Path, help="Source audio file to process.")

    gdrive_parser = subparsers.add_parser(
        "process-gdrive",
        help="Download a public Google Drive file and process it once.",
    )
    gdrive_parser.add_argument("url", help="Public Google Drive file URL.")

    subparsers.add_parser(
        "check-runtime",
        help="Inspect whether the current environment can run real local transcription.",
    )

    retry_parser = subparsers.add_parser("retry", help="Retry a failed job by identifier.")
    retry_parser.add_argument("job_id", help="Job identifier to retry.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    base_dir = infer_base_dir(args.config)
    config = load_config(args.config, base_dir=base_dir)
    paths = AppPaths(
        root=base_dir,
        inbox=config.directories.inbox,
        processing=config.directories.processing,
        archive=config.directories.archive,
        failed=config.directories.failed,
        normalized=config.directories.normalized,
        outputs=config.directories.outputs,
        metadata=config.directories.metadata,
        logs=config.directories.logs,
        state_db=config.directories.state_db,
        gps_patterns=config.classification.gps_patterns_path,
    )
    configure_logging(config.logging, log_file=paths.app_log_file)
    service = PipelineService(config=config, paths=paths)

    if args.command == "check-runtime":
        return _check_runtime()
    if args.command == "scan-once":
        return service.scan_once()
    if args.command == "watch":
        return service.watch(interval_seconds=args.interval_seconds)
    if args.command == "process":
        return service.process(source=args.source)
    if args.command == "process-gdrive":
        return _process_google_drive(service, args.url)
    if args.command == "retry":
        return service.retry(job_id=args.job_id)
    parser.error(f"Unsupported command: {args.command}")
    return 2


def _check_runtime() -> int:
    readiness = probe_transcription_runtime()
    print(json.dumps(asdict(readiness), indent=2, sort_keys=True))
    return 0 if readiness.ready else 1


def _process_google_drive(service: PipelineService, url: str) -> int:
    service.paths.ensure_runtime_directories()
    service.orchestrator.initialize()
    try:
        file_ref = parse_google_drive_url(url)
        source_path = service.paths.processing / "gdrive" / file_ref.file_id
        existing = service.state_store.get_job_by_source_path(source_path)
        if existing is not None and existing.status == JobStatus.COMPLETED:
            service.logger.info(
                "google drive file already processed; skipping download: job_id=%s file_id=%s",
                existing.id,
                file_ref.file_id,
            )
            return 0

        request = build_google_drive_download_request(file_ref)
        result = download_google_drive_file(request, source_path)
        if result.bytes_written <= 0:
            service.logger.error("downloaded zero bytes from Google Drive: %s", url)
            return 1
        return service.process(source=result.destination)
    except (GoogleDriveDownloadError, UnsupportedGoogleDriveLinkError) as exc:
        service.logger.error("google drive processing failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
