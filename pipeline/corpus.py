#!/usr/bin/env python3
"""Build an MFA input TextGrid that segments long audio into utterances.

MFA can't force-align one multi-minute utterance, so we hand it a TextGrid whose single
IntervalTier carries one interval per Whisper segment (transcript text), with empty intervals
over the silences. MFA then aligns within each interval and emits word/phone tiers.
"""

from __future__ import annotations

from pathlib import Path

_EPS = 1e-4


def normalize_segments(segments: list[dict], duration: float) -> list[tuple[float, float, str]]:
    """Sort, de-overlap and clamp segments into [0, duration]; return (start, end, text)."""
    segs = sorted(((float(s["start"]), float(s["end"]), s["text"].strip()) for s in segments),
                  key=lambda x: x[0])
    out: list[tuple[float, float, str]] = []
    prev_end = 0.0
    for start, end, text in segs:
        start = max(start, prev_end)
        end = min(max(end, start), duration)
        if end - start < _EPS or not text:
            continue
        out.append((start, end, text))
        prev_end = end
    return out


def write_input_textgrid(
    segments: list[dict], duration: float, path: str | Path, tier_name: str = "speaker"
) -> Path:
    """Write a long-form Praat TextGrid with one IntervalTier of utterances + silence gaps."""
    path = Path(path)
    segs = normalize_segments(segments, duration)

    # interleave silence gaps so intervals tile [0, duration] with no holes
    intervals: list[tuple[float, float, str]] = []
    t = 0.0
    for start, end, text in segs:
        if start > t + _EPS:
            intervals.append((t, start, ""))
        intervals.append((start, end, text))
        t = end
    if duration > t + _EPS:
        intervals.append((t, duration, ""))
    if not intervals:
        intervals = [(0.0, duration, "")]

    lines = [
        'File type = "ooTextFile"',
        'Object class = "TextGrid"',
        "",
        "xmin = 0",
        f"xmax = {duration}",
        "tiers? <exists>",
        "size = 1",
        "item []:",
        "    item [1]:",
        '        class = "IntervalTier"',
        f'        name = "{tier_name}"',
        "        xmin = 0",
        f"        xmax = {duration}",
        f"        intervals: size = {len(intervals)}",
    ]
    for i, (xmin, xmax, text) in enumerate(intervals, start=1):
        text = text.replace('"', "'")  # Praat quoting safety
        lines += [
            f"        intervals [{i}]:",
            f"            xmin = {xmin}",
            f"            xmax = {xmax}",
            f'            text = "{text}"',
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
