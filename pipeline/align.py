#!/usr/bin/env python3
"""Run Montreal Forced Aligner to get a phone-level TextGrid.

MFA lives in its own conda env ('aligner'); we invoke it via `conda run` so the orchestrator
can run under any Python. Two corpus shapes are supported:

  align()          — wav + .lab transcript  (one short utterance)
  align_segments() — wav + input .TextGrid   (long audio pre-segmented into utterances)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ENV = "aligner"
ACOUSTIC = "ukrainian_mfa"
DICTIONARY = "ukrainian_mfa"


def _resolve_conda(conda: str | None) -> str:
    """Locate conda: explicit arg > $CONDA_EXE > PATH > known miniforge installs."""
    candidates = [
        conda,
        os.environ.get("CONDA_EXE"),
        shutil.which("conda"),
        str(Path.home() / "miniforge" / "bin" / "conda"),
        "/opt/homebrew/Caskroom/miniforge/base/bin/conda",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    raise FileNotFoundError(
        "conda not found — install miniforge (see README) or set CONDA_EXE=/path/to/conda"
    )


def _run_mfa(corpus: Path, stem: str, out_textgrid: Path, *, conda, env, acoustic,
             dictionary, beam, single_speaker) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        aligned = Path(tmp) / "aligned"
        cmd = [
            _resolve_conda(conda), "run", "--no-capture-output", "-n", env,
            "mfa", "align",
            str(corpus), dictionary, acoustic, str(aligned),
            "--clean", "--use_mp", "false",
        ]
        if single_speaker:
            cmd.append("--single_speaker")
        if beam is not None:
            cmd += ["--beam", str(beam), "--retry_beam", str(beam * 4)]
        subprocess.run(cmd, check=True)

        produced = aligned / f"{stem}.TextGrid"
        if not produced.exists():
            matches = list(aligned.rglob(f"{stem}.TextGrid")) or list(aligned.rglob("*.TextGrid"))
            if not matches:
                raise FileNotFoundError(f"MFA produced no TextGrid in {aligned}")
            produced = matches[0]
        out_textgrid.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(produced, out_textgrid)
    return out_textgrid


def align(wav, lab, out_textgrid, *, conda=None, env=ENV, acoustic=ACOUSTIC,
          dictionary=DICTIONARY, beam=None) -> Path:
    """Force-align `wav` against a single-utterance `.lab` transcript."""
    wav, lab, out_textgrid = Path(wav), Path(lab), Path(out_textgrid)
    stem = wav.stem
    with tempfile.TemporaryDirectory() as tmp:
        corpus = Path(tmp) / "corpus"
        corpus.mkdir(parents=True)
        shutil.copy(wav, corpus / f"{stem}.wav")
        shutil.copy(lab, corpus / f"{stem}.lab")
        return _run_mfa(corpus, stem, out_textgrid, conda=conda, env=env, acoustic=acoustic,
                        dictionary=dictionary, beam=beam, single_speaker=True)


def align_segments(wav, input_textgrid, out_textgrid, *, conda=None, env=ENV,
                   acoustic=ACOUSTIC, dictionary=DICTIONARY, beam=None) -> Path:
    """Force-align `wav` using an input TextGrid that segments it into utterances."""
    wav, input_textgrid, out_textgrid = Path(wav), Path(input_textgrid), Path(out_textgrid)
    stem = wav.stem
    with tempfile.TemporaryDirectory() as tmp:
        corpus = Path(tmp) / "corpus"
        corpus.mkdir(parents=True)
        shutil.copy(wav, corpus / f"{stem}.wav")
        shutil.copy(input_textgrid, corpus / f"{stem}.TextGrid")
        return _run_mfa(corpus, stem, out_textgrid, conda=conda, env=env, acoustic=acoustic,
                        dictionary=dictionary, beam=beam, single_speaker=True)
