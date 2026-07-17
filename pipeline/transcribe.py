#!/usr/bin/env python3
"""Transcribe a WAV to a plain-text transcript (.lab) using whisper.cpp (whisper-cli).

The transcript is required by MFA forced alignment. whisper.cpp is used for reliable,
Metal-accelerated inference on Apple Silicon with no Python dependency.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_MODEL = "models/ggml-large-v3-turbo.bin"
DEFAULT_VAD_MODEL = "models/ggml-silero-v5.1.2.bin"

# Whisper hallucinates YouTube-outro phrases on silence/noise (training-data artifact).
# Segments that consist solely of one of these are dropped from the transcript.
_HALLUCINATION_RE = re.compile(
    r"^[\s.!,—-]*("
    r"дякую за перегляд|дякуємо за перегляд|дякую за увагу"
    r"|субтитри(?!\s+(до|для))\b.*|редактор субтитрів.*"
    r"|продовження в наступн\S+ частині"
    r")[\s.!,—-]*$",
    re.IGNORECASE,
)


def _resolve_cli(whisper_cli: str | None) -> str:
    """Locate the whisper-cli binary: explicit arg > $WHISPER_CLI > PATH > known install."""
    cli = whisper_cli or os.environ.get("WHISPER_CLI") or "whisper-cli"
    found = (
        (cli if Path(cli).is_file() else None)
        or shutil.which(cli)
        or next((str(p) for p in [Path.home() / ".local/src/whisper.cpp/build/bin/whisper-cli"]
                 if p.is_file()), None)
    )
    if not found:
        raise FileNotFoundError(
            f"whisper-cli not found ({cli!r}). Install whisper.cpp and either add "
            "whisper-cli to PATH or set WHISPER_CLI=/path/to/whisper-cli "
            "(see setup_env.sh)."
        )
    return found


def transcribe_segments(
    wav: str | Path,
    *,
    model: str | Path = DEFAULT_MODEL,
    language: str = "uk",
    whisper_cli: str | None = None,
    threads: int | None = None,
    best_of: int = 8,
    beam_size: int = 8,
    vad_model: str | Path | None = DEFAULT_VAD_MODEL,
    vad_threshold: float = 0.4,
    vad_speech_pad_ms: int = 120,
) -> list[dict]:
    """Transcribe `wav` and return timestamped segments [{start, end, text}] (seconds).

    Segments are needed to chop long audio into utterances for MFA (it cannot align one
    multi-minute utterance). Uses whisper.cpp JSON output.

    Silero VAD pre-segmentation (when `vad_model` exists) restricts decoding to regions
    with detected speech: without it whisper hallucinates outro phrases ("Дякую за
    перегляд!") on silence and drops quiet speech via its internal no-speech gate.
    `vad_threshold` 0.4 is slightly more speech-sensitive than the 0.5 default;
    `vad_speech_pad_ms` widens each region so word onsets aren't clipped (helps MFA).
    Known hallucination phrases are additionally filtered out of the result.
    """
    wav, model = Path(wav), Path(model)
    if not model.exists():
        raise FileNotFoundError(f"Whisper model not found: {model}")
    cli = _resolve_cli(whisper_cli)
    with tempfile.TemporaryDirectory() as tmp:
        of = Path(tmp) / "out"
        cmd = [
            cli, "-m", str(model), "-f", str(wav),
            "-l", language, "-oj", "-of", str(of),
            "-bo", str(best_of),
            "-bs", str(beam_size),
        ]
        vad = Path(vad_model) if vad_model else None
        if vad and vad.exists():
            cmd += ["--vad", "-vm", str(vad),
                    "-vt", str(vad_threshold), "-vp", str(vad_speech_pad_ms)]
        if threads:
            cmd += ["-t", str(threads)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        data = json.loads((of.with_suffix(".json")).read_text(encoding="utf-8"))

    segments: list[dict] = []
    dropped = 0
    for s in data.get("transcription", []):
        text = _clean(s.get("text", ""))
        if not text:
            continue
        if _HALLUCINATION_RE.match(text):
            dropped += 1
            continue
        off = s.get("offsets", {})
        segments.append(
            {"start": off["from"] / 1000.0, "end": off["to"] / 1000.0, "text": text}
        )
    if dropped:
        print(f"      note: dropped {dropped} hallucinated segment(s)")
    return segments


def transcribe(
    wav: str | Path,
    out_lab: str | Path | None = None,
    *,
    model: str | Path = DEFAULT_MODEL,
    language: str = "uk",
    whisper_cli: str | None = None,
) -> Path:
    """Transcribe `wav` and write the cleaned transcript to `out_lab` (default: wav with .lab)."""
    wav = Path(wav)
    out_lab = Path(out_lab) if out_lab else wav.with_suffix(".lab")
    model = Path(model)
    if not model.exists():
        raise FileNotFoundError(f"Whisper model not found: {model}")

    cli = _resolve_cli(whisper_cli)
    with tempfile.TemporaryDirectory() as tmp:
        of = Path(tmp) / "out"
        cmd = [
            cli,
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
