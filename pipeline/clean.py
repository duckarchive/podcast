#!/usr/bin/env python3
"""Clean + loudness-normalize podcast audio to listenable 44.1 kHz WAV.

    python -m pipeline.clean input/alex.mka            # -> output/alex.clean.wav
    python -m pipeline.clean input/*.wav -o output/    # batch
    python -m pipeline.clean in.wav -o cleaned.wav     # explicit single dst

Runs the ffmpeg chain: adeclick (de-click), deesser (de-ess), loudnorm (EBU R128).
This is the polished-listening render — distinct from the 16 kHz mono WAV the
alignment pipeline (pipeline.run) consumes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import audio


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="+", help="Input audio file(s), any format")
    p.add_argument("-o", "--output",
                   help="Output file (single input) or directory (default: output/)")
    p.add_argument("--track", default="mix",
                   help='Audio track for multi-track inputs (e.g. 2-track OBS MKV): '
                        '0-based index, or "mix" to mix all tracks (default)')
    args = p.parse_args(argv)

    inputs = [Path(i) for i in args.inputs]

    # Resolve where each output goes: explicit file only valid for a single input.
    out_arg = Path(args.output) if args.output else None
    single_file_dst = out_arg is not None and len(inputs) == 1 and out_arg.suffix.lower() == ".wav"
    outdir = (out_arg if (out_arg and not single_file_dst) else Path("output"))

    for src in inputs:
        if not src.exists():
            print(f"[skip] not found: {src}", file=sys.stderr)
            continue
        dst = out_arg if single_file_dst else outdir / f"{src.stem}.clean.wav"
        print(f"[clean] {src} -> {dst}")
        audio.enhance(src, dst, track=args.track)
    return 0


if __name__ == "__main__":
    sys.exit(main())
