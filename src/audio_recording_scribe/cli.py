"""Base CLI entrypoint for the processing pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from audio_recording_scribe import __version__
from audio_recording_scribe.config import infer_base_dir, load_config
from audio_recording_scribe.logging import configure_logging
from audio_recording_scribe.paths import AppPaths
from audio_recording_scribe.pipeline.service import PipelineService


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

    if args.command == "scan-once":
        return service.scan_once()
    if args.command == "watch":
        return service.watch(interval_seconds=args.interval_seconds)
    if args.command == "process":
        return service.process(source=args.source)
    if args.command == "retry":
        return service.retry(job_id=args.job_id)
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
