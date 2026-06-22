#!/usr/bin/env python3
"""Transcribe a WAV to a plain-text transcript (.lab) using whisper.cpp (whisper-cli).

The transcript is required by MFA forced alignment. whisper.cpp is used for reliable,
Metal-accelerated inference on Apple Silicon with no Python dependency.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

DEFAULT_MODEL = "models/ggml-large-v3-turbo.bin"


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
