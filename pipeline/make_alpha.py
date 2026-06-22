#!/usr/bin/env python3
"""Make mouth PNGs transparent by removing their solid background colour.

The lisa-*.png mouths sit on a uniform light-gray background; this turns pixels near that
colour transparent so the mouths composite cleanly in Resolve without a keyer.

    python3 -m pipeline.make_alpha mouth mouth_alpha [--tolerance 24]

Requires Pillow (pip install pillow). Non-destructive: writes to a new directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def make_alpha(src_dir: str, dst_dir: str, tolerance: int = 24) -> int:
    from PIL import Image  # local import so the rest of the pipeline needs no Pillow

    src, dst = Path(src_dir), Path(dst_dir)
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for png in sorted(src.glob("*.png")):
        im = Image.open(png).convert("RGBA")
        bg = im.getpixel((2, 2))[:3]  # sample a corner as the background colour
        px = im.load()
        w, h = im.size
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if abs(r - bg[0]) <= tolerance and abs(g - bg[1]) <= tolerance and abs(b - bg[2]) <= tolerance:
                    px[x, y] = (r, g, b, 0)
        im.save(dst / png.name)
        count += 1
        print(f"  {png.name}: bg {bg} -> transparent")
    print(f"Wrote {count} transparent PNG(s) to {dst}/")
    return count


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", help="Source dir of opaque PNGs (e.g. mouth)")
    p.add_argument("dst", help="Output dir for transparent PNGs (e.g. mouth_alpha)")
    p.add_argument("--tolerance", type=int, default=24, help="Colour distance treated as background")
    args = p.parse_args(argv)
    make_alpha(args.src, args.dst, args.tolerance)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
