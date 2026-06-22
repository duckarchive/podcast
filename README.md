# Ukrainian podcast → DaVinci Resolve viseme timeline

Turn a Ukrainian-language audio file into a DaVinci Resolve–importable timeline (FCP7 XML)
where mouth-shape (viseme) stills are placed frame-accurately, synced to the speech.

```
WAV ─▶ Whisper (transcript) ─▶ MFA (force-align) ─▶ TextGrid (IPA phones)
                                                          │
   FCP7 xmeml ◀─ xmeml gen ◀─ frame-snapped spans ◀─ phone→shape mapping
```

The mouth vocabulary is the **Rhubarb 9-shape set** (A–F + G, H, X=rest). Alignment uses
**Montreal Forced Aligner** with its Ukrainian models for proper Ukrainian phonetics —
better than Rhubarb's language-independent phonetic recognizer.

## One-time setup

```bash
# conda (miniforge) — for MFA
brew install --cask miniforge

# MFA + Ukrainian models
conda create -n aligner -c conda-forge montreal-forced-aligner -y
conda run -n aligner mfa model download acoustic   ukrainian_mfa
conda run -n aligner mfa model download dictionary ukrainian_mfa
conda run -n aligner mfa model download g2p        ukrainian_mfa   # for out-of-vocab words

# whisper.cpp — for transcription (Metal-accelerated on Apple Silicon)
brew install whisper-cpp
mkdir -p models && curl -L -o models/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin

# ffmpeg (audio prep + preview)
brew install ffmpeg
```

The pipeline itself is pure Python stdlib (no `pip install` needed); it shells out to
`whisper-cli` and `conda run -n aligner mfa`.

## Usage

Put source media in `input/`; all generated files land in `output/`.

```bash
# 0. (if starting from video) extract 16 kHz mono WAV
ffmpeg -i input/sample.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le input/sample.wav

# 1. full pipeline: WAV -> timeline XML (writes to output/)
python3 -m pipeline.run input/sample.wav

#    options:
#      -o FILE          output xmeml path (default: output/<wav>.xml)
#      --outdir DIR     output directory (default: output)
#      --audio          embed the source WAV as an audio track (sync reference)
#      --min-hold N     min frames a shape is held, de-flicker (default 2)
#      --lab FILE       reuse an existing transcript (skip Whisper)
#      --textgrid FILE  reuse an existing alignment (skip Whisper+MFA)

# 2. (optional) render a sync-check preview before importing
python3 -m pipeline.preview input/sample.wav --video input/sample.mp4

# 3. in DaVinci Resolve:  File > Import > Timeline…  ->  output/sample.xml
```

Intermediate artifacts also land in `output/`: `<wav>.lab` (transcript),
`<wav>.TextGrid` (alignment), `<wav>.visemes.tsv` (the frame-by-frame shape list).

## Configuration

- `config.json` — timeline `fps` (30), `width`/`height`, and `phonemes`: the shape→PNG map.
  Set `"ntsc": true` for 29.97/23.976.
- `pipeline/mapping_uk.json` — IPA phone → mouth shape. Tunable. Phones are normalized
  (length `ː`, palatalization `ʲ`, dental/tie-bar diacritics stripped) before lookup, so
  `bʲ`, `bː`, `b` all resolve via base `b`.

## Mouth assets & transparency

The `mouth/lisa-*.png` images currently have a **solid light-gray (221,221,221) background**
(no alpha). When composited in Resolve they'll show as opaque boxes unless you either:

- add a **Luma/Chroma Keyer** (or Delta Keyer) on the video track in Resolve, or
- generate transparent versions once:  `python3 -m pipeline.make_alpha mouth mouth_alpha`
  then point `config.json` `phonemes` at `mouth_alpha/…`.

## Layout

```
pipeline/
  run.py            orchestrator / CLI
  transcribe.py     whisper.cpp wrapper        (WAV  -> .lab)
  align.py          MFA wrapper (conda run)    (WAV+.lab -> .TextGrid)
  visemes.py        TextGrid parse + IPA→shape + frame-snap + de-flicker
  mapping_uk.json   IPA phone → mouth shape
  resolve_xml.py    spans -> FCP7 xmeml
  preview.py        ffmpeg overlay sync-check
  make_alpha.py     strip solid bg → transparent mouths (optional)
config.json         fps / size / shape→PNG map
mouth/              the 9 mouth PNGs (A–F, G, H, X)
input/              source media (git-ignored)
output/             generated XML + intermediates (git-ignored)
models/             whisper ggml model (git-ignored)
research/           deep-research findings backing the design
```
