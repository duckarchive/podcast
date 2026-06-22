# Implementation Plan — Ukrainian Podcast WAV → DaVinci Resolve Viseme Timeline

_Date: 2026-06-22. Based on the verified deep-research findings in `findings-digest.md`._

## Goal

Take a Ukrainian-language podcast `.wav` file and produce a **DaVinci Resolve–importable
XML timeline** in which mouth-shape (viseme) still images appear, **frame-accurately synced
to the speech**, at **30 fps**.

## Locked decisions

| Decision | Choice |
|---|---|
| Alignment engine | **Whisper (transcribe) → Montreal Forced Aligner (align)** |
| Viseme inventory | **Rhubarb 9-shape set**: A, B, C, D, E, F (basic) + G, H, X (extended; X = rest) |
| Resolve delivery | **Generate an XML file to import** (primary: FCP7 `xmeml`; FCPXML 1.10 as fallback) |
| Frame rate | **30 fps** (29.97 NTSC variant supported) |
| Language / runtime | Python 3.12 + ffmpeg + conda (for MFA) |

## Why this pipeline (research-backed)

- Rhubarb's only Ukrainian path is its `-r phonetic` recognizer, which the docs say is
  "usually less precise" — that's the quality gap. **MFA has first-class Ukrainian models**
  (`ukrainian_mfa` acoustic + dictionary + G2P, v3.0.0, IPA phone set), giving phone-level
  timings with real Ukrainian phonetics.
- MFA does **forced alignment**, which **requires a transcript** → we generate one with
  **Whisper** (Ukrainian) first.
- Resolve reliably imports **FCP7 `xmeml`** (frame-integer timing — a perfect fit for
  frame-snapped stills) and **FCPXML 1.8–1.13**. All time must be **frame-aligned**;
  decimal seconds cause sync drift. Stills need an **explicit duration**.

---

## Pipeline (stages)

```
WAV ─▶ [1] preprocess ─▶ [2] Whisper transcript ─▶ [3] MFA align ─▶ TextGrid
        (16k mono)          (.lab / .txt)            (phones tier, IPA, seconds)
                                                          │
                                                          ▼
   FCP7 xmeml  ◀─ [6] XML gen ◀─ [5] viseme timeline ◀─ [4] parse TextGrid
   (+ audio track)               (frames @30fps,          (phone, start, end)
                                  smoothed, gap-filled)
                                        ▲
                              mapping_uk.yaml (IPA phone → A–F/G/H/X)
```

### 1. Audio preprocess (`audio.py`)
- `ffmpeg` → 16 kHz mono PCM WAV (MFA/Whisper friendly). Keep original for the final timeline's audio track.

### 2. Transcribe (`transcribe.py`)
- `faster-whisper` (large-v3), language=`uk`. Produce plain-text transcript.
- Write `<basename>.lab` next to the wav (MFA corpus convention: matching names).
- Keep Whisper's word timestamps as a sanity-check artifact (not used for final timing).

### 3. Force-align (`align.py`)
- One-time setup: `conda create -n aligner -c conda-forge montreal-forced-aligner`;
  `mfa model download acoustic ukrainian_mfa`, `... dictionary ukrainian_mfa`, `... g2p ukrainian_mfa`.
- Corpus dir = `{audio.wav, audio.lab}`.
- `mfa validate` then `mfa align <corpus> ukrainian_mfa ukrainian_mfa <out>`.
- G2P fills OOV words. Output: `audio.TextGrid` with `words` + `phones` tiers.

### 4. Parse TextGrid (`textgrid_parse.py`)
- `praatio` → extract `phones` tier as `[(ipa_label, start_s, end_s)]`.
- Empty / `sil` / `sp` intervals → rest.

### 5. Phone → viseme + timeline build (`visemes.py`)
- Tokenize multi-char IPA (handle palatalization `ʲ`, length `ː`, dental `̪`).
- Map each phone to a Rhubarb shape via `mapping_uk.yaml` (table below).
- Convert seconds → frames: `frame = round(sec * 30)`.
- Build contiguous, non-overlapping spans `[start_frame, next_start_frame)`.
- **Smoothing**: enforce a minimum hold (default 2 frames) — merge sub-threshold visemes
  into neighbors to prevent flicker. Fill silence/gaps with **X** (rest).

### 6. Generate FCP7 xmeml (`resolve_xml.py`)
- One video track of `clipitem`s, each referencing a mouth PNG (`file` `pathurl=file:///…`),
  integer `start`/`end` (timeline frames), `in`/`out` for the still.
- `rate`: timebase 30 (set `ntsc` true for 29.97). Add the **original audio** as an audio track
  so picture + sound import already aligned.
- Handle the FCP7 still-frame `duration` quirk; verify in Resolve early.
- Fallback generator: FCPXML 1.10 (`fcpxml.py`) — stills as `Video` elements w/ `duration=0s`
  asset, rational frame-aligned time (e.g. `1001/30000s`).

### 7. CLI orchestration (`cli.py`)
- `podcast-viseme run input.wav --fps 30 --mouths assets/mouths --out timeline.xml`
- Each stage independently runnable (`transcribe`, `align`, `build`, `xml`) for iteration.
- All knobs in `config.yaml` (fps, min-hold frames, mapping file, asset dir, resolution).

---

## Proposed IPA → Rhubarb shape mapping (`mapping_uk.yaml`, tunable)

| Rhubarb shape | Mouth | Ukrainian IPA phones (length/palatal variants folded in) |
|---|---|---|
| **A** closed | P/B/M | `p b m` (+ palatalized `pʲ bʲ mʲ`) |
| **G** teeth-on-lip | F/V | `f v ʋ` (+ `fʲ ʋʲ`) |
| **B** clenched teeth | most consonants + EE | `t d n s z ts dz tsʲ dzʲ k ɡ x ɦ j c ç ʝ ɲ ɾ r` dentals `t̪ d̪ s̪ z̪ n̪`; close front vowels `i ɪ` |
| **C** open mid | EH/AE | mid vowels `ɛ e` |
| **D** wide open | AA | open vowels `ɑ ɐ a` |
| **E** rounded | AO/ER | mid-back rounded `ɔ o` |
| **F** puckered | UW/OW/W | close-back rounded `u ʊ`; glide `w` |
| **H** L-shape | L | `l ʎ` |
| **B/C** affric./postalv. | — | `tʃ dʒ ʃ ʒ` → **B** (tunable to C) |
| **X** rest | idle | silence `sil sp`, pauses, gaps |

_(Mapping is a config file so you can re-tune per taste; a preview tool helps calibrate.)_

---

## Tech stack
`python 3.12` · `ffmpeg` · `faster-whisper` · `montreal-forced-aligner` (conda) ·
`praatio` (TextGrid) · `lxml`/`xml.etree` + Jinja2 (XML) · `PyYAML` (config/mapping).

## Project structure
```
podcast/
  research/                      # done (digest, verdicts, this plan)
  src/podcast_viseme/
    cli.py  audio.py  transcribe.py  align.py
    textgrid_parse.py  visemes.py  resolve_xml.py  fcpxml.py
    mapping_uk.yaml
  assets/mouths/                 # mouth_A.png … mouth_X.png (your art)
  config.yaml  pyproject.toml  README.md
```

## Milestones
1. **Env + tooling**: conda MFA, models, ffmpeg, deps; align a 30-sec sample → TextGrid. ✅ gate: valid TextGrid.
2. **Whisper** transcription integrated → `.lab`.
3. **Parse + map + timeline** (frame snap + smoothing + rest-fill).
4. **FCP7 xmeml** gen; **import a short clip into Resolve and verify sync** (critical gate).
5. **End-to-end CLI** on the full podcast; tune mapping & min-hold.
6. *(optional)* FCPXML fallback, Resolve Python-API generator, preview/QA renderer.

## Risks & mitigations
- **FCP7 still-frame duration quirk** → test in Resolve at M4; FCPXML fallback ready.
- **MFA conda install on macOS arm64** friction → document exact env; sample-clip smoke test first.
- **Whisper transcript errors** propagate → MFA tolerates minor errors; G2P handles OOV; can hand-correct transcript.
- **Viseme flicker** on rapid phones → min-hold smoothing (config).
- **Mapping subjectivity** → externalized YAML + preview tool for calibration.

## What I need from you to start building
- A sample `.wav` (or a short clip) to validate the MFA + Whisper chain.
- The mouth-shape PNGs (9 images) — or confirm you want me to generate labeled placeholders first.
- Confirm macOS + conda is acceptable for MFA (vs. Docker).
