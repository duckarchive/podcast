# Installation Status Report

## ✅ Installed Successfully

### Miniforge (Conda)
- **Location**: ~/miniforge
- **Status**: ✅ Ready
- **Global**: 🔇 Disabled (won't show `(base)` prefix globally)
- **Project-only**: Use `source ./setup_env.sh` to enable for this project

### whisper.cpp
- **Location**: ~/.local/src/whisper.cpp (rebuilt 2026-07-09; the old /tmp build was wiped on reboot)
- **Binary**: ~/.local/src/whisper.cpp/build/bin/whisper-cli
- **Model**: ~/Projects/archive-duck/podcast/models/ggml-large-v3-turbo.bin (1.51 GB)
- **Status**: ✅ Ready for Ukrainian transcription
- The pipeline finds the binary via `$WHISPER_CLI` (set by setup_env.sh) or PATH

### ffmpeg
- **Status**: ✅ Already installed system-wide

### Project Directories
- `~/Projects/archive-duck/podcast/input/` - Create for input media
- `~/Projects/archive-duck/podcast/models/` - Created with Whisper model
- `~/Projects/archive-duck/podcast/output/` - Created for output files

## ⚠️ Needs Attention: Montreal Forced Aligner (MFA)

The conda-forge MFA package has dependency version conflicts with kalpy. This is a known issue in the ecosystem.

### Workaround Options:

1. **Use Docker** (Recommended if available):
   ```bash
   docker run -v ~/Projects/archive-duck/podcast:/work \
     ghcr.io/prosodylab/prosodylab-aligner:latest
   ```

2. **Alternative: Use Rhubarb Phoneme Recognizer** (built into many tools)
   - Simpler but less accurate for Ukrainian

3. **Manual Installation** (Advanced):
   - Install from source: https://github.com/MontrealForcedAligner/Montreal-Forced-Aligner
   - Or contact the MFA developers for pre-built Linux binaries

## Quick Start

**When working on this project**, enable the environment with:
```bash
cd ~/Projects/archive-duck/podcast
source ./setup_env.sh
```

This activates conda and whisper-cli for **this terminal only**. Close the terminal (or run `conda deactivate`) to disable it.

## Next Steps

1. Test whisper.cpp on a sample audio file:
   ```bash
   source ./setup_env.sh
   whisper-cli -m models/ggml-large-v3-turbo.bin -f input/sample.wav
   ```

2. For MFA (force alignment), resolve the dependency issue:
   - ✅ Use Docker (recommended)
   - ⚠️ Build from source (requires C++ development tools)
   - ⚠️ Request pre-built binary from MFA project

## File Locations Summary

| Tool | Path | Status |
|------|------|--------|
| Miniforge | ~/miniforge | ✅ |
| whisper-cli | ~/.local/src/whisper.cpp/build/bin/whisper-cli | ✅ |
| Whisper Model | ~/Projects/archive-duck/podcast/models/ | ✅ |
| ffmpeg | /usr/bin/ffmpeg | ✅ |
| MFA | ~/miniforge/envs/aligner | ⚠️ (dependency issue) |

