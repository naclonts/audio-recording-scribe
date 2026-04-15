from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from audio_recording_scribe.audio.normalization import (
    BinaryNotFoundError,
    deterministic_normalized_path,
    normalize_audio,
    probe_audio,
)


def test_deterministic_normalized_path_is_stable(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "diary.m4a"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")

    path_one = deterministic_normalized_path(source, tmp_path / "normalized")
    path_two = deterministic_normalized_path(source, tmp_path / "normalized")

    assert path_one == path_two
    assert path_one.suffix == ".wav"
    assert path_one.parent == tmp_path / "normalized"


def test_normalize_audio_raises_clear_error_when_ffmpeg_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "diary.m4a"
    source.write_bytes(b"audio")

    monkeypatch.setattr("audio_recording_scribe.audio.normalization.shutil.which", lambda _: None)

    with pytest.raises(BinaryNotFoundError, match="ffmpeg"):
        normalize_audio(source, tmp_path / "normalized")


def test_probe_audio_parses_ffprobe_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "diary.wav"
    source.write_bytes(b"audio")

    monkeypatch.setattr(
        "audio_recording_scribe.audio.normalization._resolve_binary",
        lambda binary, label: binary,
    )
    monkeypatch.setattr(
        "audio_recording_scribe.audio.normalization.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "streams": [
                        {
                            "codec_type": "audio",
                            "codec_name": "pcm_s16le",
                            "sample_rate": "16000",
                            "channels": 1,
                        }
                    ],
                    "format": {"duration": "12.5"},
                }
            ),
            stderr="",
        ),
    )

    probe = probe_audio(source)

    assert probe.duration_seconds == 12.5
    assert probe.sample_rate_hz == 16000
    assert probe.channels == 1
    assert probe.codec_name == "pcm_s16le"
