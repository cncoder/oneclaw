#!/usr/bin/env python3
"""Podcast TTS wrapper — configurable voice + model setup over loqui_tts engine.

This is the project-specific layer that configures voices and calls the
generic loqui_tts engine. Customize VOICES, DISPLAY_NAMES, and VOICE_PAN
for your podcast hosts.

Usage:
    python3.12 podcast_tts.py script.txt output.mp3
    python3.12 podcast_tts.py script.txt output.mp3 --voices-dir ./voices --enable-asr

Requires:
    - python3.12 + mlx-audio + soundfile + numpy + pyloudnorm
    - ffmpeg (for WAV → MP3)
    - Apple Silicon (M1/M2/M3/M4)
    - Reference audio WAVs in --voices-dir
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Add scripts/ to path so loqui_tts is importable
sys.path.insert(0, str(Path(__file__).parent))

from loqui_tts import TTSConfig, synthesize
from loqui_tts.config import VoiceConfig


# ═══════════════════════════════════════════════════════════════════════
# CUSTOMIZE THESE for your podcast
# ═══════════════════════════════════════════════════════════════════════

# TTS model — Qwen3-TTS 8bit recommended for quality/speed balance on Apple Silicon.
# 4bit is faster but has audio jitter on long text (>200 chars).
MODEL_ID = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"

# ASR model for quality back-check (optional, set empty to disable)
ASR_MODEL_ID = "mlx-community/Qwen3-ASR-0.6B-8bit"

# Default voices directory
DEFAULT_VOICES_DIR = Path(__file__).parent.parent / "assets" / "voices"

# Voice configurations — add your own hosts here.
# ref_audio: path to 10-30s WAV reference audio (quiet environment, no BGM)
# ref_text: transcript of the reference audio (must match exactly)
# min_rms: minimum RMS volume threshold (lower = more tolerant of quiet voices)
def build_voices(voices_dir: Path) -> dict[str, dict]:
    return {
        "Host_A": {
            "ref_audio": str(voices_dir / "host_female_10s.wav"),
            "ref_text": (
                "我觉得我刚开始小时候的时候，比如说，其实我是一个挺害羞的人，"
                "但我小时候会有一种，就是到了人群里边，我就想让大家开心。"
            ),
            "min_rms": 0.07,
        },
        "Host_B": {
            "ref_audio": str(voices_dir / "host_male_12s.wav"),
            "ref_text": (
                "我觉得这是我最想生在的时代，不是什么宋朝，也不是什么秦朝，"
                "起码这时代有空调啊，对吧？"
            ),
            "min_rms": 0.03,
        },
    }

DEFAULT_VOICE = "Host_A"

# Real name → display name mapping.
# Prevents real names from leaking into TTS audio.
# The script may contain role markers like 【RealName】 for voice routing,
# but spoken content should use display names only.
DISPLAY_NAMES: dict[str, str] = {
    # "RealName": "DisplayName",
    # Example: "窦文涛": "涛哥", "周迅": "小周",
}

# Stereo panning: (left_gain, right_gain)
# Creates spatial separation between hosts
VOICE_PAN: dict[str, tuple[float, float]] = {
    "Host_A": (1.0, 0.7),   # slightly left
    "Host_B": (0.7, 1.0),   # slightly right
}

# ═══════════════════════════════════════════════════════════════════════


def sanitize_names(text: str) -> str:
    """Replace real names in dialogue body with display names.

    Keeps role markers (【name】) intact so voice routing still works;
    only substitutes occurrences inside the spoken content.
    """
    if not DISPLAY_NAMES:
        return text
    lines = text.split("\n")
    result = []
    for line in lines:
        m = re.match(r'^(【[^】]+】)\s*(.*)', line, re.DOTALL)
        if m:
            marker, content = m.group(1), m.group(2)
            for real, display in DISPLAY_NAMES.items():
                content = content.replace(real, display)
            result.append(f"{marker}{content}")
        else:
            for real, display in DISPLAY_NAMES.items():
                line = line.replace(real, display)
            result.append(line)
    return "\n".join(result)


def build_config(voices_dir: Path, enable_asr: bool = False) -> TTSConfig:
    """Build TTSConfig from customizable constants."""
    voices_map = build_voices(voices_dir)
    voices = {}
    for name, v in voices_map.items():
        voices[name] = VoiceConfig(
            name=name,
            ref_audio=v["ref_audio"],
            ref_text=v["ref_text"],
            min_rms=v.get("min_rms", 0.08),
        )
    return TTSConfig(
        model_id=MODEL_ID,
        voices=voices,
        default_voice=DEFAULT_VOICE,
        asr_model_id=ASR_MODEL_ID if enable_asr else "",
        cache_dir=Path("tts_cache"),
    )


def run(
    script_path: Path,
    output_path: Path,
    voices_dir: Path | None = None,
    enable_asr: bool = False,
) -> Path:
    """Run TTS synthesis on a script file."""
    if voices_dir is None:
        voices_dir = DEFAULT_VOICES_DIR

    script = script_path.read_text(encoding="utf-8")
    script = sanitize_names(script)
    cfg = build_config(voices_dir, enable_asr=enable_asr)

    persist_dir = output_path.parent / "_tts_chunks"
    return synthesize(
        script=script,
        output_path=output_path,
        cfg=cfg,
        persist_dir=persist_dir,
        enable_asr=enable_asr,
        voice_pan=VOICE_PAN,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Podcast TTS — convert dialogue script to audio",
        epilog="Customize voice configs by editing VOICES in this file.",
    )
    parser.add_argument("script", type=Path, help="Input script file (with 【Role】 tags)")
    parser.add_argument("output", type=Path, help="Output MP3 path")
    parser.add_argument("--voices-dir", type=Path, default=None,
                        help=f"Directory with reference WAVs (default: {DEFAULT_VOICES_DIR})")
    parser.add_argument("--enable-asr", action="store_true",
                        help="Enable ASR quality back-check (slower, uses more memory)")
    args = parser.parse_args()

    if not args.script.exists():
        print(f"Error: script not found: {args.script}", file=sys.stderr)
        sys.exit(1)

    result = run(args.script, args.output, args.voices_dir, args.enable_asr)
    print(f"Done: {result}")


if __name__ == "__main__":
    main()
