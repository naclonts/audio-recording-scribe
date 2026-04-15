from __future__ import annotations

from pathlib import Path

from audio_recording_scribe.config import load_config


def test_load_config_resolves_paths_relative_to_base_dir(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text(
        "\n".join(
            [
                "directories:",
                "  inbox: data/inbox",
                "  state_db: data/state/jobs.sqlite3",
                "classification:",
                "  gps_patterns_path: config/gps_patterns.yaml",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(settings_path, base_dir=tmp_path)

    assert config.directories.inbox == tmp_path / "data" / "inbox"
    assert config.directories.state_db == tmp_path / "data" / "state" / "jobs.sqlite3"
    assert config.classification.gps_patterns_path == tmp_path / "config" / "gps_patterns.yaml"


def test_load_config_applies_env_overrides(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text("{}", encoding="utf-8")

    config = load_config(
        settings_path,
        base_dir=tmp_path,
        env={
            "AUDIO_RECORDING_SCRIBE_INGESTION__POLLING_INTERVAL_SECONDS": "45",
            "AUDIO_RECORDING_SCRIBE_LOGGING__LEVEL": "DEBUG",
        },
    )

    assert config.ingestion.polling_interval_seconds == 45
    assert config.logging.level == "DEBUG"

