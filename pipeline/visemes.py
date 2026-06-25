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
    """Map phone intervals to shapes, snap boundaries to frames, merge runs, de-flicker.

    - Each phone -> shape; consecutive equal shapes merge.
    - Boundaries snap to whole frames (round). Zero-length snapped spans are dropped.
    - Spans shorter than `min_hold` frames are absorbed into the previous span (or the next
      one at the very start) to prevent single-frame flicker.
    """
    if not phones:
        return []

    # 1. shape per interval, in seconds
    raw = [(iv.xmin, iv.xmax, mapper.shape_for(iv.text)) for iv in phones]

    # 2. merge consecutive equal shapes (in seconds domain)
    merged: list[list] = []
    for start, end, shape in raw:
        if merged and merged[-1][2] == shape:
            merged[-1][1] = end
        else:
            merged.append([start, end, shape])

    # 3. snap to frames, contiguous (each span ends where the next begins)
    spans: list[Span] = []
    for i, (start, end, shape) in enumerate(merged):
        start_f = round(start * fps)
        end_f = round(end * fps) if i + 1 < len(merged) else round(end * fps)
        spans.append(Span(start_f, end_f, shape))
    # enforce contiguity & monotonicity
    for i in range(len(spans) - 1):
        spans[i].end_f = spans[i + 1].start_f
    spans = [s for s in spans if s.duration > 0]

    # 4. de-flicker: absorb sub-min_hold spans into a neighbour, then re-merge equals
    spans = _smooth(spans, min_hold)
    return spans


def _smooth(spans: list[Span], min_hold: int) -> list[Span]:
    if min_hold <= 1 or len(spans) <= 1:
        return _merge_equal(spans)
    changed = True
    while changed and len(spans) > 1:
        changed = False
        for i, s in enumerate(spans):
            if s.duration >= min_hold:
                continue
            if i > 0:  # extend previous span over this one
                spans[i - 1].end_f = s.end_f
            else:  # first span: hand its frames to the next
                spans[i + 1].start_f = s.start_f
            del spans[i]
            changed = True
            break
        spans = _merge_equal(spans)
    return spans


def _merge_equal(spans: list[Span]) -> list[Span]:
    out: list[Span] = []
    for s in spans:
        if out and out[-1].shape == s.shape:
            out[-1].end_f = s.end_f
        else:
            out.append(Span(s.start_f, s.end_f, s.shape))
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
