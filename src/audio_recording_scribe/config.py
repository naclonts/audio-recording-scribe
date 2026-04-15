"""Typed settings loader with YAML plus env overrides."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from audio_recording_scribe.paths import project_root

ENV_PREFIX = "AUDIO_RECORDING_SCRIBE_"
CONFIG_ENV_VAR = f"{ENV_PREFIX}CONFIG"


class DirectoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbox: Path = Path("data/inbox")
    processing: Path = Path("data/processing")
    archive: Path = Path("data/archive")
    failed: Path = Path("data/failed")
    normalized: Path = Path("data/normalized")
    outputs: Path = Path("data/outputs")
    metadata: Path = Path("data/metadata")
    logs: Path = Path("data/logs")
    state_db: Path = Path("data/state/jobs.sqlite3")


class IngestionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    polling_interval_seconds: int = Field(default=30, ge=1)
    stable_file_seconds: int = Field(default=15, ge=0)
    supported_extensions: tuple[str, ...] = (".m4a", ".mp3", ".mp4", ".wav", ".aac")

    @field_validator("supported_extensions", mode="before")
    @classmethod
    def normalize_extensions(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            value = [value]
        return tuple(extension.lower() if extension.startswith(".") else f".{extension.lower()}" for extension in value)


class AudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    target_sample_rate_hz: int = Field(default=16000, ge=8000)
    target_channels: int = Field(default=1, ge=1)
    pcm_codec: str = "pcm_s16le"


class TranscriptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "faster-whisper"
    model_size: str = "small"
    device: str = "auto"
    compute_type: str = "auto"
    vad_filter: bool = True
    language: str | None = None


class ClassificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gps_patterns_path: Path = Path("config/gps_patterns.yaml")
    uncertain_max_words: int = Field(default=12, ge=1)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"
    structured: bool = False


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directories: DirectoryConfig = Field(default_factory=DirectoryConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def resolve_paths(self, base_dir: Path) -> "AppConfig":
        directories = self.directories.model_copy(
            update={
                field_name: _resolve_path(getattr(self.directories, field_name), base_dir)
                for field_name in type(self.directories).model_fields
            }
        )
        classification = self.classification.model_copy(
            update={"gps_patterns_path": _resolve_path(self.classification.gps_patterns_path, base_dir)}
        )
        return self.model_copy(update={"directories": directories, "classification": classification})


def default_config_path(root: Path | None = None) -> Path:
    base_dir = root or project_root()
    return base_dir / "config" / "settings.yaml"


def load_config(
    config_path: Path | str | None = None,
    *,
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    env_map = dict(os.environ if env is None else env)
    resolved_base_dir = (base_dir or infer_base_dir(config_path, env=env_map)).resolve()
    settings_path = _resolve_config_path(config_path, env_map, resolved_base_dir)
    with settings_path.open("r", encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle) or {}
    config_data = _deep_merge(raw_config, _env_overrides(env_map))
    return AppConfig.model_validate(config_data).resolve_paths(resolved_base_dir)


def infer_base_dir(
    config_path: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    env_map = dict(os.environ if env is None else env)
    candidate: Path | None = None
    if config_path is not None:
        candidate = Path(config_path)
    elif CONFIG_ENV_VAR in env_map:
        candidate = Path(env_map[CONFIG_ENV_VAR])

    if candidate is None:
        return project_root()

    resolved_candidate = candidate if candidate.is_absolute() else (Path.cwd() / candidate).resolve()
    if resolved_candidate.parent.name == "config":
        return resolved_candidate.parent.parent
    return resolved_candidate.parent


def _resolve_config_path(
    explicit_path: Path | str | None,
    env_map: Mapping[str, str],
    base_dir: Path,
) -> Path:
    if explicit_path is not None:
        candidate = Path(explicit_path)
    elif CONFIG_ENV_VAR in env_map:
        candidate = Path(env_map[CONFIG_ENV_VAR])
    else:
        candidate = default_config_path(base_dir)
    return candidate if candidate.is_absolute() else (base_dir / candidate).resolve()


def _resolve_path(path_value: Path, base_dir: Path) -> Path:
    return path_value if path_value.is_absolute() else (base_dir / path_value).resolve()


def _env_overrides(env_map: Mapping[str, str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, raw_value in env_map.items():
        if not key.startswith(ENV_PREFIX) or key == CONFIG_ENV_VAR:
            continue
        path = key.removeprefix(ENV_PREFIX).lower().split("__")
        current = overrides
        for segment in path[:-1]:
            current = current.setdefault(segment, {})
        current[path[-1]] = yaml.safe_load(raw_value)
    return overrides


def _deep_merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged
