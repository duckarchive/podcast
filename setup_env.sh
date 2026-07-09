#!/bin/bash
# Podcast pipeline environment setup
# Usage: source ./setup_env.sh (note: source, not bash)

export MINIFORGE_HOME="$HOME/miniforge"
export PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export WHISPER_CLI="$HOME/.local/src/whisper.cpp/build/bin/whisper-cli"
export WHISPER_MODEL="$PROJECT_ROOT/models/ggml-large-v3-turbo.bin"

# Add whisper-cli's directory to PATH
export PATH="$(dirname "$WHISPER_CLI"):$PATH"

# Initialize conda (only for this session/terminal)
if [ -f "$MINIFORGE_HOME/etc/profile.d/conda.sh" ]; then
    source "$MINIFORGE_HOME/etc/profile.d/conda.sh"
    echo "✅ Conda enabled for this session only"
    echo "   To use MFA: conda activate aligner"
    echo "   (Close this terminal to disable conda)"
else
    echo "⚠️  Miniforge not found at $MINIFORGE_HOME"
    exit 1
fi

# Verify tools
echo ""
echo "🔧 Tool Status:"
echo "   ffmpeg: $(which ffmpeg)"
echo "   whisper-cli: $WHISPER_CLI"
echo "   whisper model: $WHISPER_MODEL"
[ -f "$WHISPER_MODEL" ] && echo "   ✅ Model exists ($(du -h "$WHISPER_MODEL" | cut -f1))"

echo ""
echo "📁 Project directories:"
echo "   input/  : $PROJECT_ROOT/input/"
echo "   output/ : $PROJECT_ROOT/output/"
echo "   models/ : $PROJECT_ROOT/models/"
