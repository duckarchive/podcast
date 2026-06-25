#!/usr/bin/env python3
"""End-to-end: Ukrainian WAV -> DaVinci Resolve viseme timeline (FCP7 xmeml).

    python -m pipeline.run sample.wav -c config.json -o sample.xml

Stages: Whisper transcript -> MFA align -> phone->shape mapping -> xmeml. Intermediate
artifacts (.lab, .TextGrid, .visemes.tsv) are written next to the output for inspection and
to allow re-running later stages without redoing transcription/alignment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import align, audio, corpus, transcribe
from .resolve_xml import build_xmeml
from .visemes import textgrid_to_spans


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("wav", help="Input audio (any format; converted to 16 kHz mono internally)")
    p.add_argument("-c", "--config", default="config.json", help="Config JSON (fps/size/image map)")
    p.add_argument("-m", "--mapping", default="pipeline/mapping_uk.json", help="IPA->shape JSON")
    p.add_argument("-o", "--output", help="Output xmeml (default: <outdir>/<wav>.xml)")
    p.add_argument("--outdir", default="output", help="Directory for outputs + intermediates")
    p.add_argument("--min-hold", type=int, default=2, help="Min frames a mouth shape is held (de-flicker)")
    p.add_argument("--audio", action="store_true", help="Embed the source audio as an audio track")
    p.add_argument("--textgrid", help="Use this aligned TextGrid instead of running Whisper+MFA")
    p.add_argument("--model", default=transcribe.DEFAULT_MODEL, help="Whisper ggml model path")
    p.add_argument("--lang", default="uk", help="Transcription language code")
    args = p.parse_args(argv)

    src = Path(args.wav)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    out = Path(args.output) if args.output else outdir / f"{stem}.xml"
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    fps = cfg.get("fps", 30)
    ntsc = bool(cfg.get("ntsc", False))
    image_for_shape = cfg["phonemes"]

    # 1-2. transcript + alignment (skippable via --lab/--textgrid)
    wav = None  # the 16 kHz mono working WAV (set when not skipping alignment)
    if args.textgrid:
        textgrid = Path(args.textgrid)
        print(f"[skip] using existing TextGrid: {textgrid}")
    else:
        print("[0/4] preprocessing audio -> 16 kHz mono WAV…")
        wav = audio.to_wav16k(src, outdir / f"{stem}.16k.wav")
        duration = audio.duration(wav)
        print(f"      audio -> {wav}  ({duration:.1f}s)")

        print("[1/4] transcribing (whisper.cpp)…")
        segments = transcribe.transcribe_segments(wav, model=args.model, language=args.lang)
        joined = " ".join(s["text"] for s in segments)
        (outdir / f"{stem}.lab").write_text(joined + "\n", encoding="utf-8")
        print(f"      {len(segments)} segments  ·  transcript -> {outdir / f'{stem}.lab'}")
        print(f"      \"{joined[:120]}…\"")

        print("[2/4] segmenting + force-aligning (MFA)…")
        input_tg = corpus.write_input_textgrid(segments, duration, outdir / f"{stem}.input.TextGrid", tier_name=stem)
        textgrid = align.align_segments(wav, input_tg, outdir / f"{stem}.TextGrid")
        print(f"      alignment -> {textgrid}")

    # 3. phones -> frame-snapped viseme spans
    print("[3/4] mapping phones -> mouth shapes…")
    spans, mapper = textgrid_to_spans(textgrid, args.mapping, fps, min_hold=args.min_hold)
    print(f"      {len(spans)} viseme spans @ {fps} fps")
    if mapper.unmapped:
        print(f"      note: unmapped phones (-> default '{mapper.default}'): {mapper.unmapped}")
    _dump_tsv(spans, fps, out.with_suffix(".visemes.tsv"))

    # 4. xmeml
    print("[4/4] writing FCP7 xmeml…")
    xml = build_xmeml(
        spans, image_for_shape,
        fps=fps, width=cfg.get("width", 1920), height=cfg.get("height", 1080),
        ntsc=ntsc, sequence_name=out.stem,
        audio_path=str(wav or src) if args.audio else None,
    )
    out.write_text(xml, encoding="utf-8")
    print(f"Done -> {out}  (import in Resolve: File > Import > Timeline)")
    return 0


def _dump_tsv(spans, fps, path: Path) -> None:
    lines = ["start_f\tend_f\tstart_s\tend_s\tshape"]
    for s in spans:
        lines.append(f"{s.start_f}\t{s.end_f}\t{s.start_f / fps:.3f}\t{s.end_f / fps:.3f}\t{s.shape}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
