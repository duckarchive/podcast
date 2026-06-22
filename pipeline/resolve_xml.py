#!/usr/bin/env python3
"""Build a DaVinci Resolve-importable FCP7 XML (xmeml v5) timeline from viseme spans.

Each span becomes a still-frame clip of the mapped mouth PNG, placed at exact frame positions.
Time is expressed in integer frames (no decimal-seconds drift). Optionally lays the source
audio on an audio track so picture + sound import already in sync.

The xmeml structure mirrors the project's known-good `rhubarb_to_resolve.py` output; only the
front-end (where spans come from) changed.
"""

from __future__ import annotations

from pathlib import Path
from xml.dom import minidom
import xml.etree.ElementTree as ET

from .visemes import Span


def _rate(parent: ET.Element, fps, ntsc: bool = False) -> None:
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(int(round(fps)))
    ET.SubElement(rate, "ntsc").text = "TRUE" if ntsc else "FALSE"


def _file_url(path: str | Path) -> str:
    return Path(path).resolve().as_uri()  # proper file:// + percent-escaping


def build_xmeml(
    spans: list[Span],
    image_for_shape: dict[str, str],
    *,
    fps: float,
    width: int,
    height: int,
    ntsc: bool = False,
    sequence_name: str = "viseme_timeline",
    audio_path: str | Path | None = None,
) -> str:
    if not spans:
        raise ValueError("No spans to write")

    total_frames = spans[-1].end_f

    xmeml = ET.Element("xmeml", version="5")
    seq = ET.SubElement(xmeml, "sequence", id="sequence1")
    ET.SubElement(seq, "name").text = sequence_name
    ET.SubElement(seq, "duration").text = str(total_frames)
    _rate(seq, fps, ntsc)
    media = ET.SubElement(seq, "media")

    # ── video ───────────────────────────────────────────────────────────────────────
    video = ET.SubElement(media, "video")
    fmt = ET.SubElement(video, "format")
    sc = ET.SubElement(fmt, "samplecharacteristics")
    _rate(sc, fps, ntsc)
    ET.SubElement(sc, "width").text = str(width)
    ET.SubElement(sc, "height").text = str(height)
    track = ET.SubElement(video, "track")

    seen_files: dict[str, str] = {}
    skipped: list[str] = []
    for i, span in enumerate(spans):
        img = image_for_shape.get(span.shape)
        if img is None:
            skipped.append(span.shape)
            continue
        abs_path = str(Path(img).resolve())
        name = Path(abs_path).name
        ci = ET.SubElement(track, "clipitem", id=f"clipitem{i + 1}")
        ET.SubElement(ci, "name").text = name
        ET.SubElement(ci, "duration").text = str(span.duration)
        _rate(ci, fps, ntsc)
        ET.SubElement(ci, "start").text = str(span.start_f)
        ET.SubElement(ci, "end").text = str(span.end_f)
        ET.SubElement(ci, "in").text = "0"
        ET.SubElement(ci, "out").text = str(span.duration)
        if abs_path not in seen_files:
            fid = f"file{len(seen_files) + 1}"
            seen_files[abs_path] = fid
            fe = ET.SubElement(ci, "file", id=fid)
            ET.SubElement(fe, "name").text = name
            ET.SubElement(fe, "pathurl").text = _file_url(abs_path)
            _rate(fe, fps, ntsc)
            ET.SubElement(fe, "duration").text = str(total_frames)
            fmedia = ET.SubElement(fe, "media")
            fvideo = ET.SubElement(fmedia, "video")
            fsc = ET.SubElement(fvideo, "samplecharacteristics")
            _rate(fsc, fps, ntsc)
            ET.SubElement(fsc, "width").text = str(width)
            ET.SubElement(fsc, "height").text = str(height)
        else:
            ET.SubElement(ci, "file", id=seen_files[abs_path])
        ET.SubElement(ci, "stillframe").text = "TRUE"

    # ── audio (optional) ──────────────────────────────────────────────────────────────
    if audio_path is not None:
        _append_audio(media, Path(audio_path), total_frames, fps, ntsc)

    if skipped:
        uniq = sorted(set(skipped))
        print(f"Warning: no image mapped for shapes {uniq} ({len(skipped)} clips skipped)")

    return _serialize(xmeml)


def _append_audio(media: ET.Element, audio: Path, total_frames: int, fps, ntsc) -> None:
    a = ET.SubElement(media, "audio")
    tr = ET.SubElement(a, "track")
    ci = ET.SubElement(tr, "clipitem", id="audioclip1")
    ET.SubElement(ci, "name").text = audio.name
    ET.SubElement(ci, "duration").text = str(total_frames)
    _rate(ci, fps, ntsc)
    ET.SubElement(ci, "start").text = "0"
    ET.SubElement(ci, "end").text = str(total_frames)
    ET.SubElement(ci, "in").text = "0"
    ET.SubElement(ci, "out").text = str(total_frames)
    fe = ET.SubElement(ci, "file", id="audiofile1")
    ET.SubElement(fe, "name").text = audio.name
    ET.SubElement(fe, "pathurl").text = _file_url(audio)
    _rate(fe, fps, ntsc)
    fmedia = ET.SubElement(fe, "media")
    fa = ET.SubElement(fmedia, "audio")
    asc = ET.SubElement(fa, "samplecharacteristics")
    ET.SubElement(asc, "depth").text = "16"
    ET.SubElement(asc, "samplerate").text = "16000"
    st = ET.SubElement(ci, "sourcetrack")
    ET.SubElement(st, "mediatype").text = "audio"
    ET.SubElement(st, "trackindex").text = "1"


def _serialize(root: ET.Element) -> str:
    raw = ET.tostring(root, encoding="unicode")
    body = "\n".join(minidom.parseString(raw).toprettyxml(indent="  ").splitlines()[1:])
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE xmeml PUBLIC "-//Apple//DTD XMEML//EN"'
        ' "http://developer.apple.com/dtd/xmeml.dtd">\n' + body
    )
