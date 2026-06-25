#!/usr/bin/env python3
"""Transcribe a WAV to a plain-text transcript (.lab) using whisper.cpp (whisper-cli).

The transcript is required by MFA forced alignment. whisper.cpp is used for reliable,
Metal-accelerated inference on Apple Silicon with no Python dependency.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

DEFAULT_MODEL = "models/ggml-large-v3-turbo.bin"


def transcribe_segments(
    wav: str | Path,
    *,
    model: str | Path = DEFAULT_MODEL,
    language: str = "uk",
    whisper_cli: str = "whisper-cli",
    threads: int | None = None,
) -> list[dict]:
    """Transcribe `wav` and return timestamped segments [{start, end, text}] (seconds).

    Segments are needed to chop long audio into utterances for MFA (it cannot align one
    multi-minute utterance). Uses whisper.cpp JSON output.
    """
    wav, model = Path(wav), Path(model)
    if not model.exists():
        raise FileNotFoundError(f"Whisper model not found: {model}")
    with tempfile.TemporaryDirectory() as tmp:
        of = Path(tmp) / "out"
        cmd = [
            whisper_cli, "-m", str(model), "-f", str(wav),
            "-l", language, "-oj", "-of", str(of),
        ]
        if threads:
            cmd += ["-t", str(threads)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        data = json.loads((of.with_suffix(".json")).read_text(encoding="utf-8"))

    segments: list[dict] = []
    for s in data.get("transcription", []):
        text = _clean(s.get("text", ""))
        if not text:
            continue
        off = s.get("offsets", {})
        segments.append(
            {"start": off["from"] / 1000.0, "end": off["to"] / 1000.0, "text": text}
        )
    return segments


def transcribe(
    wav: str | Path,
    out_lab: str | Path | None = None,
    *,
    model: str | Path = DEFAULT_MODEL,
    language: str = "uk",
    whisper_cli: str = "whisper-cli",
) -> Path:
    """Transcribe `wav` and write the cleaned transcript to `out_lab` (default: wav with .lab)."""
    wav = Path(wav)
    out_lab = Path(out_lab) if out_lab else wav.with_suffix(".lab")
    model = Path(model)
    if not model.exists():
        raise FileNotFoundError(f"Whisper model not found: {model}")

    with tempfile.TemporaryDirectory() as tmp:
        of = Path(tmp) / "out"
        cmd = [
            whisper_cli,
            "-m", str(model),
            "-f", str(wav),
            "-l", language,
            "-otxt",
            "-nt",            # no timestamps in the text output
            "-of", str(of),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        text = (of.with_suffix(".txt")).read_text(encoding="utf-8")

    cleaned = _clean(text)
    out_lab.write_text(cleaned + "\n", encoding="utf-8")
    return out_lab


def _clean(text: str) -> str:
    """Collapse whitespace/newlines into a single transcript line for MFA."""
    text = re.sub(r"\s+", " ", text).strip()
    return text
