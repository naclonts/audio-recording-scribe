from audio_recording_scribe.config import load_config


def test_default_repository_config_is_loadable() -> None:
    config = load_config()

    assert config.transcription.provider == "faster-whisper"
    assert config.classification.gps_patterns_path.name == "gps_patterns.yaml"
