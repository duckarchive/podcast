#!/usr/bin/env python3
"""Render a sync-check preview: overlay the timed mouth-shape sequence onto a video + audio.

Lets you eyeball lip-sync before importing into Resolve. Uses ffmpeg's concat demuxer to turn
the viseme spans into a timed image stream, then overlays it on the source clip.

    python -m pipeline.preview sample.wav -c config.json --video sample.mp4 -o preview.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from .visemes import Span, textgrid_to_spans


def _concat_file(spans: list[Span], image_for_shape: dict[str, str], fps: float, path: Path) -> None:
    lines: list[str] = []
    last_img = None
    for s in spans:
        img = Path(image_for_shape[s.shape]).resolve()
        last_img = img
        lines.append(f"file '{img}'")
        lines.append(f"duration {s.duration / fps:.4f}")
    if last_img is not None:  # concat demuxer needs the final file repeated
        lines.append(f"file '{last_img}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render(
    spans: list[Span],
    image_for_shape: dict[str, str],
    *,
    fps: float,
    out: Path,
    video: Path | None,
    width: int,
    height: int,
    scale: float,
    pos: str,
) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        concat = Path(tmp) / "mouths.txt"
        _concat_file(spans, image_for_shape, fps, concat)
        mw = int(408 * scale)
        if video is not None:
            # overlay mouths onto the source video, keep its audio
            x, y = _pos_expr(pos)
            fc = f"[1:v]fps={fps},scale={mw}:-1[m];[0:v][m]overlay={x}:{y}:format=auto[v]"
            cmd = [
                "ffmpeg", "-y", "-v", "error",
                "-i", str(video),
                "-f", "concat", "-safe", "0", "-i", str(concat),
                "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
                "-c:a", "aac", "-shortest", str(out),
            ]
        else:
            # render mouths over a solid background (no source video)
            x, y = _pos_expr(pos)
            total_s = spans[-1].end_f / fps  # bound the (otherwise infinite) color source
            cmd = [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", f"color=c=gray:s={width}x{height}:r={fps}:d={total_s:.4f}",
                "-f", "concat", "-safe", "0", "-i", str(concat),
                "-filter_complex",
                f"[1:v]fps={fps},scale={mw}:-1[m];[0:v][m]overlay={x}:{y}:format=auto[v]",
                "-map", "[v]", "-t", f"{total_s:.4f}", str(out),
            ]
        subprocess.run(cmd, check=True)
    return out


def _pos_expr(pos: str) -> tuple[str, str]:
    return {
        "center": ("(W-w)/2", "(H-h)/2"),
        "bottom": ("(W-w)/2", "H-h-20"),
        "top": ("(W-w)/2", "20"),
    }.get(pos, ("(W-w)/2", "H-h-20"))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("wav")
    p.add_argument("-c", "--config", default="config.json")
    p.add_argument("-m", "--mapping", default="pipeline/mapping_uk.json")
    p.add_argument("--textgrid", help="TextGrid (default: output/<wav>.TextGrid)")
    p.add_argument("--video", help="Background video to overlay onto (e.g. input/sample.mp4)")
    p.add_argument("-o", "--output", default="output/preview.mp4")
    p.add_argument("--min-hold", type=int, default=2)
    p.add_argument("--scale", type=float, default=1.0, help="Mouth scale factor")
    p.add_argument("--pos", default="bottom", choices=["center", "bottom", "top"])
    args = p.parse_args(argv)

    wav = Path(args.wav)
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    fps = cfg.get("fps", 30)
    tg = Path(args.textgrid) if args.textgrid else Path("output") / f"{wav.stem}.TextGrid"
    spans, _ = textgrid_to_spans(tg, args.mapping, fps, min_hold=args.min_hold)
    out = render(
        spans, cfg["phonemes"], fps=fps, out=Path(args.output),
        video=Path(args.video) if args.video else None,
        width=cfg.get("width", 1920), height=cfg.get("height", 1080),
        scale=args.scale, pos=args.pos,
    )
    print(f"Preview -> {out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
