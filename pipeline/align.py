#!/usr/bin/env python3
"""Run Montreal Forced Aligner over a (wav, transcript) pair to get a phone-level TextGrid.

MFA lives in its own conda env ('aligner'); we invoke it via `conda run` so the orchestrator
can run under any Python. A temporary single-file corpus is assembled (wav + matching .lab).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

CONDA = "/opt/homebrew/Caskroom/miniforge/base/bin/conda"
ENV = "aligner"
ACOUSTIC = "ukrainian_mfa"
DICTIONARY = "ukrainian_mfa"


def align(
    wav: str | Path,
    lab: str | Path,
    out_textgrid: str | Path,
    *,
    conda: str = CONDA,
    env: str = ENV,
    acoustic: str = ACOUSTIC,
    dictionary: str = DICTIONARY,
    beam: int | None = None,
) -> Path:
    """Force-align `wav` against transcript `lab`; write the result to `out_textgrid`."""
    wav, lab, out_textgrid = Path(wav), Path(lab), Path(out_textgrid)
    stem = wav.stem

    with tempfile.TemporaryDirectory() as tmp:
        corpus = Path(tmp) / "corpus"
        aligned = Path(tmp) / "aligned"
        corpus.mkdir(parents=True)
        shutil.copy(wav, corpus / f"{stem}.wav")
        shutil.copy(lab, corpus / f"{stem}.lab")

        cmd = [
            conda, "run", "--no-capture-output", "-n", env,
            "mfa", "align",
            str(corpus), dictionary, acoustic, str(aligned),
            "--clean", "--single_speaker", "--use_mp", "false",
        ]
        if beam is not None:
            cmd += ["--beam", str(beam), "--retry_beam", str(beam * 4)]
        subprocess.run(cmd, check=True)

        produced = aligned / f"{stem}.TextGrid"
        if not produced.exists():
            # MFA may nest by speaker; search for it.
            matches = list(aligned.rglob(f"{stem}.TextGrid")) or list(aligned.rglob("*.TextGrid"))
            if not matches:
                raise FileNotFoundError(f"MFA produced no TextGrid in {aligned}")
            produced = matches[0]
        out_textgrid.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(produced, out_textgrid)
    return out_textgrid
