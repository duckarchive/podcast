#!/usr/bin/env python3
"""Convert an MFA phone-level TextGrid into a frame-snapped viseme (mouth-shape) timeline.

Pipeline position:  TextGrid (IPA phones, seconds)  ->  [start_frame, end_frame, shape] spans

The shape vocabulary is the Rhubarb 9-shape set (A-F basic, G/H/X extended). The IPA->shape
table lives in mapping_uk.json; phones are normalized (length/palatalization/diacritics stripped)
before lookup so palatalized and long variants collapse onto their base phone.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# Modifier letters (Unicode category Lm) we strip during normalization. Combining marks
# (category Mn: dental "̪", affricate tie bar "͡", etc.) are stripped wholesale separately.
_STRIP_MODIFIERS = {
    "ː",  # U+02D0 length
    "ˑ",  # U+02D1 half-long
    "ʲ",  # U+02B2 palatalization
    "ʷ",  # U+02B7 labialization
    "ˠ",  # U+02E0 velarization
    "ʰ",  # U+02B0 aspiration
}


def normalize_phone(phone: str) -> str:
    """Reduce an MFA IPA phone to a base symbol for shape lookup.

    Strips length, palatalization and other secondary-articulation modifier letters, plus all
    combining marks (dental diacritic, tie bars). E.g. 'bʲː'->'b', 't̪'->'t', 'd̪z̪'->'dz',
    't͡ʃ'->'tʃ'.
    """
    s = unicodedata.normalize("NFD", phone.strip())
    out = []
    for ch in s:
        if unicodedata.category(ch) == "Mn":  # combining mark
            continue
        if ch in _STRIP_MODIFIERS:
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


@dataclass
class Interval:
    xmin: float
    xmax: float
    text: str


@dataclass
class Span:
    start_f: int
    end_f: int
    shape: str

    @property
    def duration(self) -> int:
        return self.end_f - self.start_f


# ── TextGrid parsing ────────────────────────────────────────────────────────────────────

_TIER_RE = re.compile(r'class\s*=\s*"IntervalTier".*?name\s*=\s*"([^"]*)"', re.DOTALL)


def parse_textgrid(path: str | Path) -> dict[str, list[Interval]]:
    """Parse a (long-form) Praat TextGrid into {tier_name: [Interval, ...]}.

    Handles the standard long TextGrid that MFA emits. Whitespace/quoting tolerant.
    """
    text = Path(path).read_text(encoding="utf-8")
    # Split the file into per-tier chunks at each `item [n]:` boundary.
    chunks = re.split(r"item\s*\[\d+\]\s*:", text)[1:]
    tiers: dict[str, list[Interval]] = {}
    for chunk in chunks:
        name_m = re.search(r'name\s*=\s*"([^"]*)"', chunk)
        class_m = re.search(r'class\s*=\s*"([^"]*)"', chunk)
        if not name_m or not class_m or class_m.group(1) != "IntervalTier":
            continue
        name = name_m.group(1)
        intervals: list[Interval] = []
        for m in re.finditer(
            r"intervals\s*\[\d+\]\s*:\s*"
            r"xmin\s*=\s*([\d.]+)\s*"
            r"xmax\s*=\s*([\d.]+)\s*"
            r'text\s*=\s*"((?:[^"\\]|\\.)*)"',
            chunk,
        ):
            intervals.append(
                Interval(float(m.group(1)), float(m.group(2)), m.group(3).strip())
            )
        tiers[name] = intervals
    return tiers


# ── Mapping & span construction ─────────────────────────────────────────────────────────


class VisemeMapper:
    def __init__(self, mapping_path: str | Path):
        cfg = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
        self.table: dict[str, str] = cfg["phone_to_shape"]
        self.silence: set[str] = set(cfg.get("silence_labels", ["", "sil", "sp", "spn"]))
        self.default: str = cfg.get("default_shape", "B")
        self.rest_shape = "X"
        self.unmapped: dict[str, int] = {}

    def shape_for(self, label: str) -> str:
        if label.strip() in self.silence:
            return self.rest_shape
        base = normalize_phone(label)
        if base in self.table:
            return self.table[base]
        # Try the raw (un-normalized) label too, then record the miss.
        if label in self.table:
            return self.table[label]
        self.unmapped[label] = self.unmapped.get(label, 0) + 1
        return self.default


def build_spans(
    phones: list[Interval],
    mapper: VisemeMapper,
    fps: float,
    min_hold: int = 2,
) -> list[Span]:
    """Map phone intervals to shapes, de-flicker, snap to frames, enforce contiguity.

    Key change: De-flicker in seconds domain BEFORE snapping to frames.
    This avoids losing legitimate brief events to rounding artifacts.

    Steps:
    - Each phone -> shape; consecutive equal shapes merge (seconds)
    - De-flicker: remove spans < min_hold_s seconds (prevents noise)
    - Re-merge consecutive equals after de-flicker
    - Snap to whole frames (round)
    - Enforce contiguity (each span's end = next span's start)
    - Filter any remaining zero-duration spans
    """
    if not phones:
        return []

    min_hold_s = min_hold / fps  # Convert frame threshold to seconds

    # 1. shape per interval, in seconds
    raw = [(iv.xmin, iv.xmax, mapper.shape_for(iv.text)) for iv in phones]

    # 2. merge consecutive equal shapes (in seconds domain)
    merged: list[list] = []
    for start, end, shape in raw:
        if merged and merged[-1][2] == shape:
            merged[-1][1] = end
        else:
            merged.append([start, end, shape])

    # 3. de-flicker in seconds domain (before snapping)
    # Remove spans shorter than min_hold_s; this prevents losing legitimate brief events
    # that only become problematic after rounding to frames.
    merged = _smooth_seconds(merged, min_hold_s)

    # 4. re-merge consecutive equals (de-flicker may have made neighbors identical)
    merged = _merge_seconds_equal(merged)

    # 5. snap to frames, contiguous
    spans: list[Span] = []
    for start, end, shape in merged:
        start_f = round(start * fps)
        end_f = round(end * fps)
        spans.append(Span(start_f, end_f, shape))

    # enforce contiguity & monotonicity (each span's end = next span's start)
    for i in range(len(spans) - 1):
        spans[i].end_f = spans[i + 1].start_f

    spans = [s for s in spans if s.duration > 0]
    return spans


# Visually salient shapes: vowels (C/D/E/F) plus the distinctive closures A (p/b/m)
# and G (f/v). In fast speech these phones often run 30-50 ms — under min_hold — but
# they are what makes a word readable on the mouth, so de-flicker grows them to the
# minimum hold by taking time from neighbors instead of deleting them. Generic
# consonant shapes (B, H) and rest (X) are absorbed into a neighbor when too brief.
_PRIORITY_SHAPES = frozenset("ACDEFG")

_EPS = 1e-9


def _smooth_seconds(merged: list[list], min_hold_s: float) -> list[list]:
    """De-flicker in the seconds domain before snapping to frames.

    Args:
        merged: List of [start_s, end_s, shape] tuples
        min_hold_s: Minimum duration in seconds (e.g., 2/30 ≈ 0.067s for 2 frames)

    Too-brief priority shapes (vowels/closures) are widened to min_hold_s by borrowing
    time from their neighbors — B/H/X donate down to zero, priority neighbors only down
    to min_hold_s. Too-brief B/H/X spans are absorbed into the longer neighbor. The old
    absorb-into-previous strategy erased every short vowel between consonants, squashing
    whole fast-spoken words into a single consonant shape.
    """
    if min_hold_s <= 0 or len(merged) <= 1:
        return merged

    def too_short(s: list) -> bool:
        return s[1] - s[0] < min_hold_s - _EPS

    changed = True
    while changed:
        merged = _merge_seconds_equal([s for s in merged if s[1] - s[0] > _EPS])
        if len(merged) <= 1:
            break
        changed = False
        for i, span in enumerate(merged):
            if not too_short(span):
                continue
            neighbors = [j for j in (i - 1, i + 1) if 0 <= j < len(merged)]
            if span[2] in _PRIORITY_SHAPES:
                # Grow toward min_hold, borrowing from the longer neighbor first.
                for j in sorted(neighbors, key=lambda j: merged[j][1] - merged[j][0], reverse=True):
                    floor = min_hold_s if merged[j][2] in _PRIORITY_SHAPES else 0.0
                    avail = max(0.0, (merged[j][1] - merged[j][0]) - floor)
                    take = min(avail, min_hold_s - (span[1] - span[0]))
                    if take <= _EPS:
                        continue
                    if j < i:
                        merged[j][1] -= take
                        span[0] -= take
                    else:
                        merged[j][0] += take
                        span[1] += take
                if not too_short(span):
                    changed = True
                    break
            # Unfixable priority span, or a brief B/H/X: absorb into the longer neighbor.
            j = max(neighbors, key=lambda j: merged[j][1] - merged[j][0])
            if j < i:
                merged[j][1] = span[1]
            else:
                merged[j][0] = span[0]
            del merged[i]
            changed = True
            break
    return merged


def _merge_seconds_equal(merged: list[list]) -> list[list]:
    """Merge consecutive spans with identical shapes (seconds domain).

    Called after de-flicker to clean up adjacent spans that now have the same shape.
    """
    out: list[list] = []
    for start, end, shape in merged:
        if out and out[-1][2] == shape:
            out[-1][1] = end
        else:
            out.append([start, end, shape])
    return out


def textgrid_to_spans(
    textgrid_path: str | Path,
    mapping_path: str | Path,
    fps: float,
    min_hold: int = 2,
    phone_tier: str = "phones",
) -> tuple[list[Span], VisemeMapper]:
    tiers = parse_textgrid(textgrid_path)
    name = _find_phone_tier(tiers, phone_tier)
    if name is None:
        raise ValueError(
            f"No '{phone_tier}' tier in {textgrid_path}. Tiers found: {list(tiers)}"
        )
    mapper = VisemeMapper(mapping_path)
    spans = build_spans(tiers[name], mapper, fps, min_hold)
    return spans, mapper


def _find_phone_tier(tiers: dict[str, list[Interval]], phone_tier: str) -> str | None:
    """Locate the phones tier, tolerating MFA's 'speaker - phones' naming."""
    if phone_tier in tiers:
        return phone_tier
    for name in tiers:
        low = name.lower()
        if low == phone_tier or low.endswith(f"- {phone_tier}") or low.endswith(phone_tier):
            return name
    return None
