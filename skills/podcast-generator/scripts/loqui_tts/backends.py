"""TTS backend selector — MLX (Apple Silicon) vs Torch (Linux x86_64).

Both backends expose the same stdin/stdout JSON worker protocol used by
engine.py. The worker script source is selected based on platform + env.

Selection order:
1. Explicit env TTS_BACKEND=mlx|torch
2. Apple Silicon (darwin + arm64) → mlx
3. Everything else (linux / x86_64) → torch
"""
from __future__ import annotations

import os
import platform
from pathlib import Path


def detect_backend() -> str:
    forced = os.environ.get("TTS_BACKEND", "").strip().lower()
    if forced in ("mlx", "torch"):
        return forced
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "mlx"
    return "torch"


# ── MLX worker (Apple Silicon) ────────────────────────────────────────
_MLX_WORKER = r'''
import sys, json, time, os

import numpy as np
import soundfile as sf
from mlx_audio.tts.utils import load_model

SR = int(os.environ.get("TTS_SAMPLE_RATE", "24000"))
SKIP_ASR = os.environ.get("TTS_SKIP_ASR") == "1"

def trim_trailing_silence(audio, sr=SR, threshold=0.01, window_sec=0.5, keep_sec=0.3):
    window = int(sr * window_sec)
    last_voice = len(audio)
    for i in range(len(audio) - window, 0, -window):
        w_rms = float(np.sqrt(np.mean(audio[i:i+window]**2)))
        if w_rms >= threshold:
            last_voice = i + window
            break
    end = min(len(audio), last_voice + int(sr * keep_sec))
    return audio[:end]

def trim_leading_silence(audio, sr=SR, threshold=0.01, window_sec=0.1):
    window = int(sr * window_sec)
    for i in range(0, len(audio) - window, window):
        w_rms = float(np.sqrt(np.mean(audio[i:i+window]**2)))
        if w_rms >= threshold:
            return audio[max(0, i - int(sr * 0.05)):]
    return audio

model_id = sys.argv[1] if len(sys.argv) > 1 else ""
model = load_model(model_id)

asr_model = None
print(json.dumps({"ready": True}), flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        args = json.loads(line)
    except json.JSONDecodeError:
        print(json.dumps({"ok": False, "error": "bad JSON"}), flush=True)
        continue

    t0 = time.time()
    try:
        results = list(model.generate(
            text=args["text"],
            ref_audio=args["ref_audio"],
            ref_text=args["ref_text"],
            language="Chinese",
            max_tokens=args["max_tokens"],
        ))
        audio = np.array(results[0].audio)

        rms = float(np.sqrt(np.mean(audio**2)))
        if rms < 0.01:
            results = list(model.generate(
                text=args["text"],
                ref_audio=args["ref_audio"],
                ref_text=args["ref_text"],
                language="Chinese",
                max_tokens=args["max_tokens"],
            ))
            audio = np.array(results[0].audio)
            rms = float(np.sqrt(np.mean(audio**2)))

        raw_len = len(audio)
        audio = trim_trailing_silence(audio)
        audio = trim_leading_silence(audio)

        max_sec = len(args["text"]) * float(args.get("max_sec_per_char", 0.25)) * 2
        if len(audio) / SR > max_sec:
            audio = audio[:int(max_sec * SR)]
            audio = trim_trailing_silence(audio)

        trimmed = raw_len - len(audio)
        rms = float(np.sqrt(np.mean(audio**2)))
        sf.write(args["output"], audio, SR)
        dur = len(audio) / SR

        repetition_detected = False
        try:
            seg_len = int(SR * 0.5)
            if len(audio) > seg_len * 2:
                for start in range(0, len(audio) - seg_len * 2, seg_len):
                    seg1 = audio[start:start + seg_len]
                    seg2 = audio[start + seg_len:start + seg_len * 2]
                    norm1 = np.sqrt(np.sum(seg1**2))
                    norm2 = np.sqrt(np.sum(seg2**2))
                    if norm1 > 0.001 and norm2 > 0.001:
                        corr = float(np.sum(seg1 * seg2) / (norm1 * norm2))
                        if corr > 0.9:
                            repetition_detected = True
                            break
        except Exception:
            pass

        abnormal_silence = False
        try:
            window_ms = 50
            window_n = int(SR * window_ms / 1000)
            silence_thresh = 0.005
            max_silence_samples = int(SR * 1.5)
            margin = int(SR * 0.3)
            if len(audio) > margin * 2 + window_n:
                consecutive_silence = 0
                for pos in range(margin, len(audio) - margin - window_n, window_n):
                    w_rms = float(np.sqrt(np.mean(audio[pos:pos + window_n]**2)))
                    if w_rms < silence_thresh:
                        consecutive_silence += window_n
                        if consecutive_silence >= max_silence_samples:
                            abnormal_silence = True
                            break
                    else:
                        consecutive_silence = 0
        except Exception:
            pass

        asr_text = ""
        asr_similarity = 1.0
        asr_model_id = args.get("asr_model_id", "")
        if asr_model_id and not SKIP_ASR:
            try:
                import re
                from difflib import SequenceMatcher
                from mlx_audio.stt.utils import load_model as load_stt_model
                if asr_model is None:
                    asr_model = load_stt_model(asr_model_id)
                asr_result = asr_model.generate(args["output"], language="Chinese")
                asr_text = asr_result.text.strip()
                clean_orig = re.sub(r'[，。！？、；：“”‘’（）…—\s]', '', args["text"])
                clean_asr = re.sub(r'[，。！？、；：“”‘’（）…—\s]', '', asr_text)
                asr_similarity = SequenceMatcher(None, clean_orig, clean_asr).ratio()
            except Exception as e:
                asr_text = f"ASR_ERROR: {e}"
                asr_similarity = 1.0

        elapsed = time.time() - t0
        print(json.dumps({"ok": True, "duration": dur, "rms": rms, "elapsed": elapsed,
                           "trimmed": trimmed / SR, "asr_text": asr_text,
                           "asr_similarity": asr_similarity,
                           "repetition_detected": repetition_detected,
                           "abnormal_silence": abnormal_silence}), flush=True)
    except Exception as e:
        elapsed = time.time() - t0
        print(json.dumps({"ok": False, "error": str(e), "elapsed": elapsed}), flush=True)
'''


# ── Torch worker (Linux x86_64, CPU or CUDA) ──────────────────────────
# Uses the official `qwen-tts` pip package + Qwen3-TTS Base for voice clone.
# Model is auto-downloaded from HF on first run (~1.5GB).
_TORCH_WORKER = r'''
import sys, json, time, os

import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

SR = int(os.environ.get("TTS_SAMPLE_RATE", "24000"))
SKIP_ASR = os.environ.get("TTS_SKIP_ASR") == "1"

# Prefer CUDA when available, fall back to CPU.
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.bfloat16 if DEVICE == "cuda" else torch.float32

def trim_trailing_silence(audio, sr=SR, threshold=0.01, window_sec=0.5, keep_sec=0.3):
    window = int(sr * window_sec)
    last_voice = len(audio)
    for i in range(len(audio) - window, 0, -window):
        w_rms = float(np.sqrt(np.mean(audio[i:i+window]**2)))
        if w_rms >= threshold:
            last_voice = i + window
            break
    end = min(len(audio), last_voice + int(sr * keep_sec))
    return audio[:end]

def trim_leading_silence(audio, sr=SR, threshold=0.01, window_sec=0.1):
    window = int(sr * window_sec)
    for i in range(0, len(audio) - window, window):
        w_rms = float(np.sqrt(np.mean(audio[i:i+window]**2)))
        if w_rms >= threshold:
            return audio[max(0, i - int(sr * 0.05)):]
    return audio

# Voice clone uses the Base model (CustomVoice model is preset-only).
# Caller-supplied model_id is honored so users can pick 0.6B or 1.7B.
model_id = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
model = Qwen3TTSModel.from_pretrained(model_id, dtype=DTYPE, device_map=DEVICE)

asr_model = None
asr_processor = None
print(json.dumps({"ready": True, "device": DEVICE}), flush=True)

def _resample(audio, src_sr, dst_sr):
    if src_sr == dst_sr:
        return audio
    n = int(round(len(audio) * dst_sr / src_sr))
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        args = json.loads(line)
    except json.JSONDecodeError:
        print(json.dumps({"ok": False, "error": "bad JSON"}), flush=True)
        continue

    t0 = time.time()
    try:
        # qwen-tts voice clone API returns (wavs_list, sampling_rate)
        wavs, src_sr = model.generate_voice_clone(
            text=args["text"],
            ref_audio=args["ref_audio"],
            x_vector_only_mode=True,
        )
        audio = np.asarray(wavs[0], dtype=np.float32)
        src_sr = int(src_sr)

        audio = _resample(audio, src_sr, SR)

        # Normalize amplitude if near clipping or very quiet
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        if peak > 0.95:
            audio = audio * (0.9 / peak)

        rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0

        raw_len = len(audio)
        audio = trim_trailing_silence(audio)
        audio = trim_leading_silence(audio)

        max_sec = len(args["text"]) * float(args.get("max_sec_per_char", 0.25)) * 2
        if len(audio) / SR > max_sec:
            audio = audio[:int(max_sec * SR)]
            audio = trim_trailing_silence(audio)

        trimmed = raw_len - len(audio)
        rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0
        sf.write(args["output"], audio, SR)
        dur = len(audio) / SR

        repetition_detected = False
        try:
            seg_len = int(SR * 0.5)
            if len(audio) > seg_len * 2:
                for start in range(0, len(audio) - seg_len * 2, seg_len):
                    seg1 = audio[start:start + seg_len]
                    seg2 = audio[start + seg_len:start + seg_len * 2]
                    norm1 = np.sqrt(np.sum(seg1**2))
                    norm2 = np.sqrt(np.sum(seg2**2))
                    if norm1 > 0.001 and norm2 > 0.001:
                        corr = float(np.sum(seg1 * seg2) / (norm1 * norm2))
                        if corr > 0.9:
                            repetition_detected = True
                            break
        except Exception:
            pass

        abnormal_silence = False
        try:
            window_ms = 50
            window_n = int(SR * window_ms / 1000)
            silence_thresh = 0.005
            max_silence_samples = int(SR * 1.5)
            margin = int(SR * 0.3)
            if len(audio) > margin * 2 + window_n:
                consecutive_silence = 0
                for pos in range(margin, len(audio) - margin - window_n, window_n):
                    w_rms = float(np.sqrt(np.mean(audio[pos:pos + window_n]**2)))
                    if w_rms < silence_thresh:
                        consecutive_silence += window_n
                        if consecutive_silence >= max_silence_samples:
                            abnormal_silence = True
                            break
                    else:
                        consecutive_silence = 0
        except Exception:
            pass

        asr_text = ""
        asr_similarity = 1.0
        asr_model_id = args.get("asr_model_id", "")
        if asr_model_id and not SKIP_ASR:
            try:
                import re
                from difflib import SequenceMatcher
                if asr_model is None:
                    # qwen-asr package name (may vary); fall back silently if unavailable.
                    try:
                        from qwen_asr import Qwen3ASRModel
                        asr_model = Qwen3ASRModel.from_pretrained(asr_model_id, device_map=DEVICE)
                    except ImportError:
                        asr_text = "ASR_UNAVAILABLE"
                        raise
                asr_result = asr_model.transcribe(args["output"], language="Chinese")
                asr_text = asr_result.text.strip() if hasattr(asr_result, "text") else str(asr_result).strip()
                clean_orig = re.sub(r'[，。！？、；：“”‘’（）…—\s]', '', args["text"])
                clean_asr = re.sub(r'[，。！？、；：“”‘’（）…—\s]', '', asr_text)
                asr_similarity = SequenceMatcher(None, clean_orig, clean_asr).ratio()
            except Exception as e:
                if not asr_text:
                    asr_text = f"ASR_ERROR: {e}"
                asr_similarity = 1.0

        elapsed = time.time() - t0
        print(json.dumps({"ok": True, "duration": dur, "rms": rms, "elapsed": elapsed,
                           "trimmed": trimmed / SR, "asr_text": asr_text,
                           "asr_similarity": asr_similarity,
                           "repetition_detected": repetition_detected,
                           "abnormal_silence": abnormal_silence}), flush=True)
    except Exception as e:
        elapsed = time.time() - t0
        print(json.dumps({"ok": False, "error": str(e), "elapsed": elapsed}), flush=True)
'''


# ── Default model ID per backend ──────────────────────────────────────
DEFAULT_MODEL_ID = {
    "mlx": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
    # Base model (not CustomVoice) — CustomVoice is preset-only, can't clone.
    "torch": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
}


def get_worker_script(backend: str | None = None) -> str:
    b = backend or detect_backend()
    if b == "mlx":
        return _MLX_WORKER
    if b == "torch":
        return _TORCH_WORKER
    raise ValueError(f"Unknown backend: {b}")


def get_default_model_id(backend: str | None = None) -> str:
    b = backend or detect_backend()
    return DEFAULT_MODEL_ID[b]
