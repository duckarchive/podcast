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

from . import align, transcribe
from .resolve_xml import build_xmeml
from .visemes import textgrid_to_spans


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("wav", help="Input WAV (16 kHz mono recommended)")
    p.add_argument("-c", "--config", default="config.json", help="Config JSON (fps/size/image map)")
    p.add_argument("-m", "--mapping", default="pipeline/mapping_uk.json", help="IPA->shape JSON")
    p.add_argument("-o", "--output", help="Output xmeml (default: <outdir>/<wav>.xml)")
    p.add_argument("--outdir", default="output", help="Directory for outputs + intermediates")
    p.add_argument("--min-hold", type=int, default=2, help="Min frames a mouth shape is held (de-flicker)")
    p.add_argument("--audio", action="store_true", help="Embed the source WAV as an audio track")
    p.add_argument("--lab", help="Use this transcript instead of running Whisper")
    p.add_argument("--textgrid", help="Use this TextGrid instead of running Whisper+MFA")
    p.add_argument("--model", default=transcribe.DEFAULT_MODEL, help="Whisper ggml model path")
    p.add_argument("--lang", default="uk", help="Transcription language code")
    args = p.parse_args(argv)

    wav = Path(args.wav)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out = Path(args.output) if args.output else outdir / f"{wav.stem}.xml"
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    fps = cfg.get("fps", 30)
    ntsc = bool(cfg.get("ntsc", False))
    image_for_shape = cfg["phonemes"]

    # 1-2. transcript + alignment (skippable via --lab/--textgrid)
    if args.textgrid:
        textgrid = Path(args.textgrid)
        print(f"[skip] using existing TextGrid: {textgrid}")
    else:
        if args.lab:
            lab = Path(args.lab)
            print(f"[skip] using existing transcript: {lab}")
        else:
            print("[1/4] transcribing (whisper.cpp)…")
            lab = transcribe.transcribe(wav, outdir / f"{wav.stem}.lab", model=args.model, language=args.lang)
            print(f"      transcript -> {lab}")
            print(f"      \"{lab.read_text(encoding='utf-8').strip()[:120]}…\"")
        print("[2/4] force-aligning (MFA)…")
        textgrid = align.align(wav, lab, outdir / f"{wav.stem}.TextGrid")
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
        audio_path=str(wav) if args.audio else None,
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
