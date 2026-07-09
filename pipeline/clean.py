#!/usr/bin/env python3
"""Clean + loudness-normalize podcast audio to listenable 44.1 kHz WAV (no whisper/MFA).

    python -m pipeline.clean                       # everything in input/
    python -m pipeline.clean input/episode.mkv     # one file
    python -m pipeline.clean in.wav -o cleaned.wav # explicit single dst

Same input handling as pipeline.run: audio files are processed directly; for videos
(mkv/mp4/…) each audio track is extracted and cleaned separately (-> <stem>.aN.clean.wav),
controlled by --track each|mix|N.

Runs the ffmpeg chain: adeclick (de-click), afftdn (denoise), deesser (de-ess),
loudnorm (EBU R128). This is the polished-listening render — distinct from the
16 kHz mono WAV the alignment pipeline (pipeline.run) consumes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import audio
from .run import _build_jobs, _expand_inputs


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="*", default=["input"],
                   help="Media file(s) and/or folder(s) (default: input/)")
    p.add_argument("-c", "--config", default="config.json",
                   help='Config JSON (for per-extension "sources" rules)')
    p.add_argument("-o", "--output",
                   help="Output file (single job) or directory (default: output/)")
    p.add_argument("--track", default=None,
                   help='Multi-track handling: "each" cleans every track separately, "mix" mixes '
                        'all tracks into one, or a 0-based track index. Default: the config\'s '
                        'per-extension "sources" rule if any, else "each". Overrides rules.')
    args = p.parse_args(argv)
    if args.track is not None and args.track not in ("each", "mix"):
        try:
            args.track = int(args.track)
        except ValueError:
            p.error(f'--track must be "each", "mix", or a 0-based track index (got {args.track!r})')

    cfg_path = Path(args.config)
    rules = json.loads(cfg_path.read_text(encoding="utf-8")).get("sources") if cfg_path.exists() else None

    files = _expand_inputs([Path(i) for i in args.inputs])
    jobs = _build_jobs(files, args.track, rules)
    if not jobs:
        print("nothing to process", file=sys.stderr)
        return 1

    # Resolve where each output goes: explicit file only valid for a single job.
    out_arg = Path(args.output) if args.output else None
    single_file_dst = out_arg is not None and len(jobs) == 1 and out_arg.suffix.lower() == ".wav"
    outdir = out_arg if (out_arg and not single_file_dst) else Path("output")

    for src, track, stem in jobs:
        dst = out_arg if single_file_dst else outdir / f"{stem}.clean.wav"
        label = src.name + (f" [a:{track}]" if isinstance(track, int) else "")
        print(f"[clean] {label} -> {dst}")
        audio.enhance(src, dst, track=track)
    return 0


if __name__ == "__main__":
    sys.exit(main())
