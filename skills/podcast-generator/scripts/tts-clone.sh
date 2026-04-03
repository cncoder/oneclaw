#!/usr/bin/env bash
# Qwen3-TTS Voice Clone — standalone single-shot TTS script
#
# Usage: tts-clone.sh "text to speak" output.mp3
# Voice selection via TTS_VOICE env var (default: host_female)
#
# Supported voices (customize by adding WAVs to VOICES_DIR):
#   host_female  — Female host (default)
#   host_male    — Male host
#
# Requirements:
#   - python3.12 + mlx-audio + soundfile
#   - ffmpeg (for WAV → MP3)
#   - Apple Silicon (M1/M2/M3/M4)
#   - Reference audio WAVs in $VOICES_DIR

set -euo pipefail

TEXT="$1"
OUTPUT="$2"

if [ -z "$TEXT" ] || [ -z "$OUTPUT" ]; then
  echo "Usage: tts-clone.sh <text> <output.mp3>" >&2
  echo "  TTS_VOICE=host_male tts-clone.sh \"text\" out.mp3" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VOICES_DIR="${VOICES_DIR:-$SCRIPT_DIR/../assets/voices}"
VOICE="${TTS_VOICE:-host_female}"
TTS_MODEL="${TTS_MODEL:-mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit}"

case "$VOICE" in
  host_female)
    REF_AUDIO="$VOICES_DIR/host_female_10s.wav"
    REF_TEXT="我觉得我刚开始小时候的时候，比如说，其实我是一个挺害羞的人，但我小时候会有一种，就是到了人群里边，我就想让大家开心。"
    ;;
  host_male)
    REF_AUDIO="$VOICES_DIR/host_male_12s.wav"
    REF_TEXT="我觉得这是我最想生在的时代，不是什么宋朝，也不是什么秦朝，起码这时代有空调啊，对吧？"
    ;;
  *)
    # Custom voice: expects $VOICES_DIR/$VOICE.wav and TTS_REF_TEXT env var
    REF_AUDIO="$VOICES_DIR/$VOICE.wav"
    REF_TEXT="${TTS_REF_TEXT:-}"
    if [ -z "$REF_TEXT" ]; then
      echo "Custom voice '$VOICE': set TTS_REF_TEXT env var with reference transcript" >&2
      exit 1
    fi
    ;;
esac

if [ ! -f "$REF_AUDIO" ]; then
  echo "Error: Reference audio not found: $REF_AUDIO" >&2
  echo "  Set VOICES_DIR to the directory containing your reference WAVs" >&2
  exit 1
fi

# Generate WAV first, then convert to MP3
TEMP_WAV=$(mktemp /tmp/tts_wav_XXXXXXXX.wav)
TEMP_TEXT=$(mktemp /tmp/tts_text_XXXXXXXX) || { echo "mktemp failed" >&2; exit 1; }

# Write text to temp file (safe, avoids shell injection)
printf '%s' "$TEXT" > "$TEMP_TEXT"

# Pass parameters via environment variables
TTS_TEXT_FILE="$TEMP_TEXT" TTS_REF_AUDIO="$REF_AUDIO" TTS_REF_TEXT="$REF_TEXT" \
TTS_OUTPUT_WAV="$TEMP_WAV" TTS_MODEL_ID="$TTS_MODEL" \
python3.12 << 'PYEOF'
import sys, os
try:
    from mlx_audio.tts.utils import load_model
    import numpy as np
    import soundfile as sf

    text_file = os.environ["TTS_TEXT_FILE"]
    ref_audio = os.environ["TTS_REF_AUDIO"]
    ref_text = os.environ["TTS_REF_TEXT"]
    output_wav = os.environ["TTS_OUTPUT_WAV"]
    model_id = os.environ.get("TTS_MODEL_ID", "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit")

    with open(text_file, "r") as f:
        text = f.read().strip()

    if not text:
        print("Error: empty text", file=sys.stderr)
        sys.exit(1)

    model = load_model(model_id)

    def generate_once():
        results = list(model.generate(
            text=text,
            ref_audio=ref_audio,
            ref_text=ref_text,
            language="Chinese",
            max_tokens=1024,
        ))
        return np.array(results[0].audio)

    audio = generate_once()

    # Quality check: retry if too quiet
    rms = np.sqrt(np.mean(audio**2))
    if rms < 0.01:
        audio = generate_once()

    # ASR quality check: retry once if similarity < 0.5
    try:
        import re
        from difflib import SequenceMatcher
        from mlx_audio.stt.utils import load_model as load_stt_model

        sf.write(output_wav, audio, 24000)
        asr_model = load_stt_model("mlx-community/Qwen3-ASR-0.6B-8bit")
        asr_result = asr_model.generate(output_wav, language="Chinese")
        asr_text = asr_result.text.strip()
        clean_orig = re.sub(r'[，。！？、；：\u201c\u201d\u2018\u2019（）…—\s]', '', text)
        clean_asr = re.sub(r'[，。！？、；：\u201c\u201d\u2018\u2019（）…—\s]', '', asr_text)
        similarity = SequenceMatcher(None, clean_orig, clean_asr).ratio()
        print(f"ASR similarity: {similarity:.0%} (heard: {asr_text[:80]})", file=sys.stderr)
        if similarity < 0.5:
            print("ASR quality low, retrying...", file=sys.stderr)
            audio = generate_once()
    except Exception as e:
        print(f"ASR check skipped: {e}", file=sys.stderr)

    sf.write(output_wav, audio, 24000)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF

# Clean up temp text file
rm -f "$TEMP_TEXT"

if [ $? -ne 0 ] || [ ! -s "$TEMP_WAV" ]; then
  echo "TTS generation failed" >&2
  rm -f "$TEMP_WAV"
  exit 1
fi

# Convert to MP3 (128k bitrate, 24kHz mono)
ffmpeg -y -i "$TEMP_WAV" -codec:a libmp3lame -b:a 128k -ar 24000 -ac 1 "$OUTPUT" 2>/dev/null

rm -f "$TEMP_WAV"

if [ ! -s "$OUTPUT" ]; then
  echo "MP3 conversion failed" >&2
  exit 1
fi

echo "OK: $OUTPUT" >&2
