#!/usr/bin/env python3
"""Audio preprocessing: convert any input (mka/wav/mp4/…) to 16 kHz mono PCM WAV.

whisper.cpp requires 16 kHz mono WAV; MFA is happy with it too. We normalize once up front.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _probe_16k_mono_wav(path: Path) -> bool:
    """True if `path` is already a 16 kHz mono PCM WAV (no reconversion needed)."""
    if path.suffix.lower() != ".wav":
        return False
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name,sample_rate,channels",
             "-of", "json", str(path)],
            check=True, capture_output=True, text=True,
        ).stdout
        s = json.loads(out)["streams"][0]
        return (
            s.get("sample_rate") == "16000"
            and int(s.get("channels", 0)) == 1
            and str(s.get("codec_name", "")).startswith("pcm_s16")
        )
    except Exception:
        return False


def duration(path: str | Path) -> float:
    """Audio duration in seconds via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def to_wav16k(src: str | Path, dst: str | Path) -> Path:
    """Return a 16 kHz mono PCM WAV for `src`, writing to `dst` (unless `src` already qualifies)."""
    src, dst = Path(src), Path(dst)
    if _probe_16k_mono_wav(src):
        return src
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)],
        check=True,
    )
    return dst


# Cleanup filter chain: pre-gain, de-click transients, gently denoise, tame sibilance, normalize.
#   volume=1.2             +20% gain up front so quieter noise sits above the filter thresholds
#   adeclick=t=6           remove clicks/crackle (6 ms threshold window)
#   afftdn=nr=6            FFT denoise, very low (6 dB reduction; ffmpeg default is 12)
#   deesser=i=0.2:m=0.2:f=0.5   reduce harsh "s"/"sh" sibilance
#   loudnorm=I=-16:LRA=11:TP=-1.5   EBU R128 loudness norm (podcast target; resets final level)
_ENHANCE_FILTER = "volume=1.2,adeclick=t=6,afftdn=nr=6,deesser=i=0.2:m=0.2:f=0.5,loudnorm=I=-16:LRA=11:TP=-1.5"


def enhance(src: str | Path, dst: str | Path) -> Path:
    """Clean + loudness-normalize `src` to a 44.1 kHz PCM WAV at `dst`.

    Applies de-click, de-ess, and EBU R128 loudness normalization — suitable for
    listenable podcast output (separate from the 16 kHz mono WAV used for alignment).
    """
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-af", _ENHANCE_FILTER, "-ar", "44100", "-c:a", "pcm_s16le", str(dst)],
        check=True,
    )
    return dst
