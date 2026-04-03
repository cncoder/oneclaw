"""TTS configuration — all tunable parameters in one place."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VoiceConfig:
    """Configuration for a single voice."""
    name: str
    ref_audio: str
    ref_text: str
    min_rms: float = 0.08


@dataclass
class TTSConfig:
    """All TTS engine parameters.

    Attributes:
        model_id: MLX model identifier (e.g. "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit").
        chunk_hard_limit: Max characters per TTS chunk.
        sample_rate: Audio sample rate in Hz.
        max_tokens: Max tokens for TTS model generation.
        min_rms: Minimum RMS threshold for quality check.
        max_audio_sec_per_char: Max audio seconds per character (duration cap).
        asr_similarity_threshold: ASR back-check similarity threshold.
        asr_model_id: ASR model for quality checking (empty = disabled).
        voices: Mapping of voice name to VoiceConfig.
        default_voice: Default voice name when no role tag is found.
        cache_dir: Directory for cross-day chunk cache. None = no caching.
        max_retries: Max retry attempts per chunk.
        crossfade_ms: Crossfade duration between chunks in milliseconds.
        pink_noise_db: Pink noise floor level in dB.
        mp3_bitrate: Output MP3 bitrate (e.g. "192k").
    """
    model_id: str = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"
    chunk_hard_limit: int = 290
    sample_rate: int = 24000
    max_tokens: int = 1024
    min_rms: float = 0.08
    max_audio_sec_per_char: float = 0.25
    asr_similarity_threshold: float = 0.55
    asr_model_id: str = ""
    voices: dict[str, VoiceConfig] = field(default_factory=dict)
    default_voice: str = ""
    cache_dir: Path | None = None
    max_retries: int = 2
    crossfade_ms: int = 200
    pink_noise_db: float | None = None
    mp3_bitrate: str = "192k"
