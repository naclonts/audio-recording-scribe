from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from audio_recording_scribe.audio.normalization import probe_audio
from audio_recording_scribe.cli import main


ENABLE_REAL_STT_ENV = "AUDIO_RECORDING_SCRIBE_RUN_REAL_STT_TEST"
MODEL_ENV = "AUDIO_RECORDING_SCRIBE_REAL_STT_MODEL"
DEVICE_ENV = "AUDIO_RECORDING_SCRIBE_REAL_STT_DEVICE"
COMPUTE_TYPE_ENV = "AUDIO_RECORDING_SCRIBE_REAL_STT_COMPUTE_TYPE"
SPOKEN_TEXT = "I made coffee and folded laundry at home"
ANCHOR_TOKENS = ("coffee", "laundry", "folded", "home")


def test_process_command_runs_real_ffmpeg_to_faster_whisper_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_name = _require_real_stt_runtime()
    source_path = tmp_path / "recordings" / "diary-entry.m4a"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    _synthesize_test_recording(source_path)

    settings_path = _write_settings(tmp_path, model_name)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["--config", str(settings_path), "process", str(source_path)])

    assert exit_code == 0

    normalized_files = sorted((tmp_path / "data" / "normalized").glob("*.wav"))
    assert len(normalized_files) == 1
    normalized_probe = probe_audio(normalized_files[0])
    assert normalized_probe.sample_rate_hz == 16000
    assert normalized_probe.channels == 1
    assert normalized_probe.codec_name == "pcm_s16le"
    assert normalized_probe.duration_seconds is not None
    assert normalized_probe.duration_seconds > 0

    transcript_files = sorted((tmp_path / "data" / "metadata").glob("*-transcript.json"))
    assert len(transcript_files) == 1
    transcript_payload = json.loads(transcript_files[0].read_text(encoding="utf-8"))
    assert transcript_payload["provider"] == "faster-whisper"
    assert transcript_payload["model_name"]
    assert len(transcript_payload["segments"]) >= 1

    clean_text_files = sorted((tmp_path / "data" / "outputs").glob("*.txt"))
    assert len(clean_text_files) == 1
    clean_text = clean_text_files[0].read_text(encoding="utf-8").lower()
    assert _count_anchor_hits(clean_text) >= 2


def _require_real_stt_runtime() -> str:
    if os.environ.get(ENABLE_REAL_STT_ENV) != "1":
        pytest.skip(
            f"set {ENABLE_REAL_STT_ENV}=1 and {MODEL_ENV}=<local-model-or-cached-model-id> "
            "to opt into the real STT integration test"
        )

    model_name = os.environ.get(MODEL_ENV, "").strip()
    if not model_name:
        pytest.skip(f"set {MODEL_ENV} to a local model path or already-cached model id")

    try:
        __import__("faster_whisper")
    except ModuleNotFoundError:
        pytest.skip("faster_whisper is not installed in this environment")

    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            pytest.skip(f"{binary} is not installed in this environment")

    model_path = Path(model_name).expanduser()
    if any(sep in model_name for sep in (os.sep, os.altsep) if sep) and not model_path.exists():
        pytest.skip(f"{MODEL_ENV} points to a missing path: {model_path}")

    return model_name


def _write_settings(tmp_path: Path, model_name: str) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    gps_patterns_path = Path(__file__).resolve().parents[1] / "fixtures" / "gps_patterns.yaml"
    device = os.environ.get(DEVICE_ENV, "cpu")
    compute_type = os.environ.get(COMPUTE_TYPE_ENV, "int8")
    settings_path.write_text(
        "\n".join(
            [
                "transcription:",
                f"  model_size: {json.dumps(model_name)}",
                f"  device: {json.dumps(device)}",
                f"  compute_type: {json.dumps(compute_type)}",
                '  language: "en"',
                "classification:",
                f"  gps_patterns_path: {json.dumps(str(gps_patterns_path))}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return settings_path


def _synthesize_test_recording(output_path: Path) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"flite=text='{SPOKEN_TEXT}'",
        "-c:a",
        "aac",
        str(output_path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown ffmpeg flite failure"
        pytest.skip(f"ffmpeg flite synthesis is unavailable: {message}")


def _count_anchor_hits(text: str) -> int:
    return sum(1 for token in ANCHOR_TOKENS if token in text)
