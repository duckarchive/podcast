#!/usr/bin/env python3
"""End-to-end: Ukrainian audio/video -> DaVinci Resolve viseme timeline (FCP7 xmeml).

    python -m pipeline.run                      # everything in input/
    python -m pipeline.run input/episode.mkv    # one file

Inputs may be audio (wav/mp3/mka/…) or video containers (mkv/mp4/…). Audio files are
processed directly; for videos each audio track is extracted to its own 16 kHz mono WAV
and run through the pipeline separately (track N -> <stem>.aN.xml).

Stages: Whisper transcript -> MFA align -> phone->shape mapping -> xmeml. Intermediate
artifacts (.lab, .TextGrid, .visemes.tsv) are written next to the output for inspection and
to allow re-running later stages without redoing transcription/alignment.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import align, audio, corpus, transcribe
from .resolve_xml import build_xmeml
from .visemes import textgrid_to_spans


def _expand_inputs(paths: list[Path]) -> list[Path]:
    """Flatten files/folders into a file list (folders: non-hidden files, sorted)."""
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.is_file() and not f.name.startswith("."))
        elif p.exists():
            files.append(p)
        else:
            print(f"[skip] not found: {p}", file=sys.stderr)
    return files


def _build_jobs(
    files: list[Path], track_arg: int | str | None, rules: dict | None = None
) -> list[tuple[Path, int | str, str]]:
    """One (src, track, stem) pipeline job per audio track to process.

    Single-track files (typical audio) yield one job under the file's own stem.
    Multi-track files (2-track OBS MKV, mka…) fan out one job per track as <stem>.aN.

    `rules` (config.json "sources") sets per-extension defaults, e.g.
    {"mkv": {"track": 1, "name": "alex"}} pins the track and renames the outputs.
    An explicit `track_arg` (from --track) overrides rule tracks; None means
    "rule track if any, else each".
    """
    jobs: list[tuple[Path, int | str, str]] = []
    seen: set[str] = set()
    for f in files:
        try:
            tracks = audio.audio_tracks(f)
        except subprocess.CalledProcessError:
            print(f"[skip] unreadable media: {f}", file=sys.stderr)
            continue
        if not tracks:
            print(f"[skip] no audio streams: {f}", file=sys.stderr)
            continue
        if len(tracks) > 1:
            desc = ", ".join(f"a:{t['index']} ({t['title'] or t['codec']}, {t['channels']}ch)" for t in tracks)
            print(f"[scan] {f.name}: {len(tracks)} audio tracks — {desc}")
        rule = (rules or {}).get(f.suffix.lower().lstrip("."), {})
        track = track_arg if track_arg is not None else rule.get("track", "each")
        if track != "each":
            pairs = [(track, "{base}")]
        elif len(tracks) == 1:
            pairs = [("mix", "{base}")]
        else:
            pairs = [(t["index"], f"{{base}}.a{t['index']}") for t in tracks]
        base = rule.get("name") or f.stem
        if any(tpl.format(base=base) in seen for _, tpl in pairs):
            base = f.name  # stem collision (foo.mkv + foo.mp4): qualify outputs with the extension
        for trk, tpl in pairs:
            stem = tpl.format(base=base)
            seen.add(stem)
            jobs.append((f, trk, stem))
    return jobs


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="*", default=["input"],
                   help="Media file(s) and/or folder(s) (default: input/)")
    p.add_argument("-c", "--config", default="config.json", help="Config JSON (fps/size/image map)")
    p.add_argument("-m", "--mapping", default="pipeline/mapping_uk.json", help="IPA->shape JSON")
    p.add_argument("-o", "--output", help="Output xmeml (default: <outdir>/<stem>.xml; single job only)")
    p.add_argument("--outdir", default="output", help="Directory for outputs + intermediates")
    p.add_argument("--min-hold", type=int, default=2, help="Min frames a mouth shape is held (de-flicker)")
    p.add_argument("--audio", action="store_true", help="Embed the source audio as an audio track")
    p.add_argument("--track", default=None,
                   help='Multi-track handling: "each" runs the pipeline per track, "mix" mixes '
                        'all tracks into one, or a 0-based track index. Default: the config\'s '
                        'per-extension "sources" rule if any, else "each". Overrides rules.')
    p.add_argument("--textgrid", help="Use this aligned TextGrid instead of running Whisper+MFA (single job only)")
    p.add_argument("--model", default=transcribe.DEFAULT_MODEL, help="Whisper ggml model path")
    p.add_argument("--lang", default="uk", help="Transcription language code")
    args = p.parse_args(argv)
    if args.track is not None and args.track not in ("each", "mix"):
        try:
            args.track = int(args.track)
        except ValueError:
            p.error(f'--track must be "each", "mix", or a 0-based track index (got {args.track!r})')

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))

    files = _expand_inputs([Path(i) for i in args.inputs])
    jobs = _build_jobs(files, args.track, cfg.get("sources"))
    if not jobs:
        print("nothing to process", file=sys.stderr)
        return 1
    if (args.output or args.textgrid) and len(jobs) != 1:
        p.error(f"-o/--textgrid apply to a single pipeline run, but {len(jobs)} were queued "
                "(pass one single-track file, or pin --track)")

    failed: list[str] = []
    for i, (src, track, stem) in enumerate(jobs, 1):
        label = src.name + (f" [a:{track}]" if isinstance(track, int) else "")
        if len(jobs) > 1:
            print(f"\n=== [{i}/{len(jobs)}] {label} ===")
        try:
            _process(src, track, stem, args, cfg, outdir)
        except Exception as e:
            failed.append(label)
            print(f"[fail] {label}: {e}", file=sys.stderr)
    if failed:
        print(f"\n{len(failed)}/{len(jobs)} failed: {', '.join(failed)}", file=sys.stderr)
    return 1 if failed else 0


def _process(src: Path, track: int | str, stem: str, args, cfg: dict, outdir: Path) -> None:
    """Run one audio track through transcript -> alignment -> visemes -> xmeml."""
    fps = cfg.get("fps", 30)
    ntsc = bool(cfg.get("ntsc", False))
    image_for_shape = cfg["phonemes"]
    out = Path(args.output) if args.output else outdir / f"{stem}.xml"

    # 1-2. transcript + alignment (skippable via --textgrid)
    wav = None  # the 16 kHz mono working WAV (set when not skipping alignment)
    if args.textgrid:
        textgrid = Path(args.textgrid)
        print(f"[skip] using existing TextGrid: {textgrid}")
    else:
        print("[0/4] preprocessing audio -> 16 kHz mono WAV…")
        wav = audio.to_wav16k(src, outdir / f"{stem}.16k.wav", track=track)
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


def _dump_tsv(spans, fps, path: Path) -> None:
    lines = ["start_f\tend_f\tstart_s\tend_s\tshape"]
    for s in spans:
        lines.append(f"{s.start_f}\t{s.end_f}\t{s.start_f / fps:.3f}\t{s.end_f / fps:.3f}\t{s.shape}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
