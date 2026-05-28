"""TTS engine — process-isolated worker, chunk cache, advanced audio merge."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .config import TTSConfig, VoiceConfig

# Persistent worker script: loads model once, processes tasks via stdin/stdout JSON
from .backends import get_worker_script as _get_worker_script

# Legacy placeholder kept for any direct reference; actual script is selected
# dynamically by backend (mlx or torch) via _write_worker_script below.
_WORKER_SCRIPT = r'''
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
            return audio[max(0, i - int(sr * 0.05)):]  # keep 50ms before
    return audio

# Load model once on startup
model_id = sys.argv[1] if len(sys.argv) > 1 else ""
model = load_model(model_id)

# Optional ASR model (loaded lazily on first use)
asr_model = None

# Signal ready
print(json.dumps({"ready": True}), flush=True)

# Process tasks from stdin, one JSON per line
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

        # Quality check: if too quiet, retry once
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

        # Trim trailing + leading silence
        raw_len = len(audio)
        audio = trim_trailing_silence(audio)
        audio = trim_leading_silence(audio)

        # Cap max duration
        max_sec = len(args["text"]) * float(args.get("max_sec_per_char", 0.25)) * 2
        if len(audio) / SR > max_sec:
            audio = audio[:int(max_sec * SR)]
            audio = trim_trailing_silence(audio)

        trimmed = raw_len - len(audio)
        rms = float(np.sqrt(np.mean(audio**2)))

        sf.write(args["output"], audio, SR)
        dur = len(audio) / SR

        # Repetition detection: autocorrelation for >0.5s repeated segments
        repetition_detected = False
        try:
            seg_len = int(SR * 0.5)  # 0.5s segments
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

        # Abnormal silence detection: >1.5s silence in the middle
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

        # ASR quality check
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
                clean_orig = re.sub(r'[，。！？、；：\u201c\u201d\u2018\u2019（）…—\s]', '', args["text"])
                clean_asr = re.sub(r'[，。！？、；：\u201c\u201d\u2018\u2019（）…—\s]', '', asr_text)
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


# ── Chunk cache (cross-day, keyed by sha256(voice+text)) ──────────────

def _cache_key(voice_name: str, text: str) -> str:
    """SHA-256 of voice_name + normalized text."""
    normalized = text.replace("\n", " ").replace("\r", " ").strip()
    return hashlib.sha256(f"{voice_name}:{normalized}".encode()).hexdigest()


def _cache_get(voice_name: str, text: str, cache_dir: Path | None) -> Path | None:
    """Return cached WAV path if exists, else None."""
    if cache_dir is None:
        return None
    key = _cache_key(voice_name, text)
    cached = cache_dir / f"{key}.wav"
    return cached if cached.exists() else None


def _cache_put(voice_name: str, text: str, wav_path: Path, cache_dir: Path | None) -> None:
    """Copy WAV into cache."""
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(voice_name, text)
    dst = cache_dir / f"{key}.wav"
    try:
        shutil.copy2(wav_path, dst)
    except Exception:
        pass


# ── Process-isolated worker management ────────────────────────────────

def _write_worker_script(tmp: Path) -> Path:
    """Write persistent worker script to temp dir.

    Worker source is selected by backend (mlx for Apple Silicon,
    torch for everything else). Override with env TTS_BACKEND=mlx|torch.
    """
    worker = tmp / "_tts_worker.py"
    worker.write_text(_get_worker_script())
    return worker


def _start_worker(worker: Path, cfg: TTSConfig) -> subprocess.Popen:
    """Start a persistent worker process. Blocks until worker signals ready."""
    env = os.environ.copy()
    env["TTS_SAMPLE_RATE"] = str(cfg.sample_rate)
    proc = subprocess.Popen(
        [sys.executable, str(worker), cfg.model_id],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    t0 = time.time()
    startup_timeout = int(os.environ.get("TTS_STARTUP_TIMEOUT", "300"))
    while time.time() - t0 < startup_timeout:
        line = proc.stdout.readline()
        if not line:
            stderr = proc.stderr.read()
            raise RuntimeError(f"Worker died during startup: {stderr[:500]}")
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("ready"):
                return proc
        except json.JSONDecodeError:
            continue
    proc.kill()
    raise RuntimeError(f"Worker startup timeout ({startup_timeout}s)")


def _send_task(proc: subprocess.Popen, task: dict, timeout: float = 300) -> dict | None:
    """Send a task to worker and read one JSON response line."""
    try:
        proc.stdin.write(json.dumps(task, ensure_ascii=False) + "\n")
        proc.stdin.flush()
    except (BrokenPipeError, OSError):
        return None

    t0 = time.time()
    while time.time() - t0 < timeout:
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def _synthesize_chunk(
    proc: subprocess.Popen,
    text: str,
    output: Path,
    chunk_idx: int,
    total: int,
    voice_name: str,
    voice_cfg: VoiceConfig,
    cfg: TTSConfig,
) -> dict | None:
    """Send a chunk to persistent worker, return info dict or None."""
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if not text:
        return None

    task = {
        "text": text,
        "ref_audio": voice_cfg.ref_audio,
        "ref_text": voice_cfg.ref_text,
        "max_tokens": cfg.max_tokens,
        "max_sec_per_char": cfg.max_audio_sec_per_char,
        "output": str(output),
        "asr_model_id": cfg.asr_model_id,
    }

    t0 = time.time()
    info = _send_task(proc, task, timeout=300)
    elapsed = time.time() - t0

    if info is None:
        print(f"  [TTS] chunk {chunk_idx}/{total} [{voice_name}]: TIMEOUT/DEAD ({elapsed:.1f}s)")
        return None

    if not info.get("ok"):
        err = info.get("error", "unknown")
        print(f"  [TTS] chunk {chunk_idx}/{total} [{voice_name}]: FAILED ({elapsed:.1f}s) {err}")
        return None

    if output.exists():
        dur = info.get("duration", 0)
        rms = info.get("rms", 0)
        trimmed = info.get("trimmed", 0)
        asr_sim = info.get("asr_similarity", 1.0)
        trim_str = f", trimmed {trimmed:.1f}s" if trimmed > 0.5 else ""
        asr_str = f", ASR={asr_sim:.0%}" if asr_sim < 1.0 or info.get("asr_text") else ""
        print(f"  [TTS] chunk {chunk_idx}/{total} [{voice_name}]: {len(text)} chars -> "
              f"{dur:.1f}s audio, RMS={rms:.3f}{asr_str} ({elapsed:.1f}s{trim_str})")
        return info
    else:
        print(f"  [TTS] chunk {chunk_idx}/{total} [{voice_name}]: no output file ({elapsed:.1f}s)")
        return None


def _synthesize_all(
    dialogue: list[tuple[str, str]],
    tmp: Path,
    cfg: TTSConfig,
    persist_dir: Path | None = None,
) -> list[Path]:
    """Persistent worker mode: model loaded once, chunks processed via stdin/stdout.

    Quality checks: RMS, repetition detection, abnormal silence, ASR back-check.
    Breakpoint resume via persist_dir.

    2026-05-19: 支持 cfg.parallel_workers > 1 — 启动多个 worker round-robin
    分发 chunks，GPU 利用率提升 ~2x。EC2 A10G 22GB 可同时跑 2-3 个 model.
    """
    parallel_workers = max(1, getattr(cfg, "parallel_workers", 1))
    if parallel_workers > 1:
        return _synthesize_all_parallel(dialogue, tmp, cfg, persist_dir, parallel_workers)

    worker_script = _write_worker_script(tmp)
    wav_files = []
    failed = 0

    # Breakpoint resume tracking
    progress_file: Path | None = None
    completed: set[int] = set()
    if persist_dir is not None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        progress_file = persist_dir / "_progress.json"
        if progress_file.exists():
            try:
                progress_data = json.loads(progress_file.read_text())
                completed = set(progress_data.get("completed", []))
                print(f"[TTS] Resuming: {len(completed)}/{len(dialogue)} chunks done")
            except Exception:
                completed = set()

    print(f"[TTS] Starting persistent worker (loading model)...")
    t_start = time.time()
    proc = _start_worker(worker_script, cfg)
    print(f"[TTS] Worker ready ({time.time() - t_start:.1f}s)")

    default_voice_cfg = cfg.voices.get(cfg.default_voice) if cfg.default_voice else None

    try:
        for i, (voice_name, chunk) in enumerate(dialogue):
            wav_dir = persist_dir if persist_dir is not None else tmp
            wav_path = wav_dir / f"chunk_{i}.wav"

            # Resume: skip completed chunks
            if i in completed and wav_path.exists():
                print(f"  [TTS] chunk {i}/{len(dialogue)} [{voice_name}]: done, skipping")
                wav_files.append(wav_path)
                continue

            # Cache hit: reuse cross-day WAV
            cached = _cache_get(voice_name, chunk, cfg.cache_dir)
            if cached is not None:
                shutil.copy2(cached, wav_path)
                print(f"  [TTS] chunk {i}/{len(dialogue)} [{voice_name}]: cache hit")
                wav_files.append(wav_path)
                if progress_file is not None:
                    completed.add(i)
                    try:
                        progress_file.write_text(json.dumps({"completed": sorted(completed)}))
                    except Exception:
                        pass
                continue

            voice_cfg = cfg.voices.get(voice_name, default_voice_cfg)
            if voice_cfg is None:
                print(f"  [TTS] chunk {i}/{len(dialogue)} [{voice_name}]: no voice config, skipping")
                failed += 1
                continue
            voice_min_rms = voice_cfg.min_rms

            info = None
            for attempt in range(cfg.max_retries):
                if proc.poll() is not None:
                    print(f"  [TTS] Worker died (rc={proc.returncode}), restarting...")
                    proc = _start_worker(worker_script, cfg)

                info = _synthesize_chunk(proc, chunk, wav_path, i, len(dialogue),
                                         voice_name=voice_name, voice_cfg=voice_cfg, cfg=cfg)
                if info is None:
                    print(f"  [TTS] chunk {i} [{voice_name}]: attempt {attempt+1} failed, retrying...")
                    continue
                rms = info.get("rms", 0)
                if rms < voice_min_rms:
                    print(f"  [TTS] chunk {i} [{voice_name}]: RMS={rms:.3f} < {voice_min_rms} (quality too low), retrying...")
                    continue
                if info.get("repetition_detected"):
                    print(f"  [TTS] chunk {i} [{voice_name}]: repetition detected, retrying...")
                    continue
                if info.get("abnormal_silence"):
                    print(f"  [TTS] chunk {i} [{voice_name}]: abnormal silence (>1.5s), retrying...")
                    continue
                asr_sim = info.get("asr_similarity", 1.0)
                if asr_sim < cfg.asr_similarity_threshold:
                    asr_text = info.get("asr_text", "")
                    print(f"  [TTS] chunk {i} [{voice_name}]: ASR={asr_sim:.0%} < {cfg.asr_similarity_threshold:.0%} "
                          f"(noise/garbage), retrying... ASR heard: '{asr_text[:50]}'")
                    continue
                break

            if info is not None:
                wav_files.append(wav_path)
                _cache_put(voice_name, chunk, wav_path, cfg.cache_dir)
                if progress_file is not None:
                    completed.add(i)
                    try:
                        progress_file.write_text(json.dumps({"completed": sorted(completed)}))
                    except Exception:
                        pass
            else:
                failed += 1
    finally:
        try:
            proc.stdin.close()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print(f"[TTS] Synthesis done: {len(wav_files)}/{len(dialogue)} chunks"
          f"{f', {failed} failed' if failed else ''}")
    return wav_files


def _synthesize_all_parallel(
    dialogue: list[tuple[str, str]],
    tmp: Path,
    cfg: TTSConfig,
    persist_dir: Path | None,
    parallel_workers: int,
) -> list[Path]:
    """启动 N 个 _tts_worker.py 并发处理 chunks (round-robin via ThreadPoolExecutor).

    2026-05-19: Abel 要求 EC2 GPU 双 chunk 并行,A10G 22GB 富余可承载.
    每个 worker 独立 stdin/stdout,线程池分发 chunk,顺序保证 (索引由调用方维护).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    worker_script = _write_worker_script(tmp)
    wav_files: list[Path | None] = [None] * len(dialogue)
    failed_count = 0
    failed_lock = threading.Lock()

    # Breakpoint resume tracking (shared, lock-protected)
    progress_file: Path | None = None
    completed: set[int] = set()
    completed_lock = threading.Lock()
    if persist_dir is not None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        progress_file = persist_dir / "_progress.json"
        if progress_file.exists():
            try:
                progress_data = json.loads(progress_file.read_text())
                completed = set(progress_data.get("completed", []))
                print(f"[TTS] Resuming: {len(completed)}/{len(dialogue)} chunks done")
            except Exception:
                completed = set()

    print(f"[TTS] Starting {parallel_workers} parallel workers (loading model)...")
    t_start = time.time()
    workers: list[subprocess.Popen] = []
    worker_locks: list[threading.Lock] = []
    for w_idx in range(parallel_workers):
        proc = _start_worker(worker_script, cfg)
        workers.append(proc)
        worker_locks.append(threading.Lock())
        print(f"[TTS] Worker {w_idx+1}/{parallel_workers} ready ({time.time() - t_start:.1f}s)")

    default_voice_cfg = cfg.voices.get(cfg.default_voice) if cfg.default_voice else None

    def _process_one(idx: int, voice_name: str, chunk: str) -> tuple[int, Path | None]:
        """单 chunk 处理 (在 thread pool 里跑). 返回 (idx, wav_path 或 None)."""
        nonlocal failed_count
        wav_dir = persist_dir if persist_dir is not None else tmp
        wav_path = wav_dir / f"chunk_{idx}.wav"

        # Resume: skip
        with completed_lock:
            if idx in completed and wav_path.exists():
                print(f"  [TTS] chunk {idx}/{len(dialogue)} [{voice_name}]: done, skipping")
                return idx, wav_path

        # Cache hit
        cached = _cache_get(voice_name, chunk, cfg.cache_dir)
        if cached is not None:
            shutil.copy2(cached, wav_path)
            print(f"  [TTS] chunk {idx}/{len(dialogue)} [{voice_name}]: cache hit")
            with completed_lock:
                completed.add(idx)
                if progress_file is not None:
                    try:
                        progress_file.write_text(json.dumps({"completed": sorted(completed)}))
                    except Exception:
                        pass
            return idx, wav_path

        voice_cfg = cfg.voices.get(voice_name, default_voice_cfg)
        if voice_cfg is None:
            print(f"  [TTS] chunk {idx}/{len(dialogue)} [{voice_name}]: no voice config, skipping")
            with failed_lock:
                failed_count += 1
            return idx, None
        voice_min_rms = voice_cfg.min_rms

        # Round-robin: 每个 chunk 用 idx % N 的 worker (lock 保护 stdin/stdout)
        w_idx = idx % parallel_workers
        info = None
        for attempt in range(cfg.max_retries):
            with worker_locks[w_idx]:
                proc = workers[w_idx]
                if proc.poll() is not None:
                    print(f"  [TTS] Worker {w_idx} died (rc={proc.returncode}), restarting...")
                    workers[w_idx] = _start_worker(worker_script, cfg)
                    proc = workers[w_idx]

                info = _synthesize_chunk(proc, chunk, wav_path, idx, len(dialogue),
                                         voice_name=voice_name, voice_cfg=voice_cfg, cfg=cfg)
            # quality 检查 (不需要锁)
            if info is None:
                print(f"  [TTS] chunk {idx} [{voice_name}]: attempt {attempt+1} failed, retrying...")
                continue
            rms = info.get("rms", 0)
            if rms < voice_min_rms:
                print(f"  [TTS] chunk {idx} [{voice_name}]: RMS={rms:.3f} < {voice_min_rms}, retrying...")
                continue
            if info.get("repetition_detected"):
                print(f"  [TTS] chunk {idx} [{voice_name}]: repetition, retrying...")
                continue
            if info.get("abnormal_silence"):
                print(f"  [TTS] chunk {idx} [{voice_name}]: abnormal silence, retrying...")
                continue
            asr_sim = info.get("asr_similarity", 1.0)
            if asr_sim < cfg.asr_similarity_threshold:
                asr_text = info.get("asr_text", "")
                print(f"  [TTS] chunk {idx} [{voice_name}]: ASR={asr_sim:.0%} < "
                      f"{cfg.asr_similarity_threshold:.0%}, retrying... heard: '{asr_text[:50]}'")
                continue
            break

        if info is not None:
            _cache_put(voice_name, chunk, wav_path, cfg.cache_dir)
            with completed_lock:
                completed.add(idx)
                if progress_file is not None:
                    try:
                        progress_file.write_text(json.dumps({"completed": sorted(completed)}))
                    except Exception:
                        pass
            return idx, wav_path
        else:
            with failed_lock:
                failed_count += 1
            return idx, None

    # 提交所有 chunks 到线程池
    try:
        with ThreadPoolExecutor(max_workers=parallel_workers) as pool:
            futures = [
                pool.submit(_process_one, i, voice_name, chunk)
                for i, (voice_name, chunk) in enumerate(dialogue)
            ]
            for fut in as_completed(futures):
                try:
                    idx, wav_path = fut.result()
                    if wav_path is not None:
                        wav_files[idx] = wav_path
                except Exception as exc:
                    print(f"  [TTS] chunk future error: {exc}")
    finally:
        for proc in workers:
            try:
                proc.stdin.close()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    final_files = [w for w in wav_files if w is not None]
    print(f"[TTS] Parallel synthesis done ({parallel_workers}x workers): "
          f"{len(final_files)}/{len(dialogue)} chunks"
          f"{f', {failed_count} failed' if failed_count else ''}")
    return final_files


# ── Advanced Merge (crossfade + stereo pan + pink noise + LUFS) ──────

def _generate_breath(sr: int, dur_sec: float = 0.25) -> "np.ndarray":
    """Generate synthetic breath sound: band-limited noise with envelope."""
    import numpy as np
    n = int(sr * dur_sec)
    white = np.random.randn(n).astype("float32")
    kernel_size = max(1, sr // 600)
    kernel = np.ones(kernel_size, "float32") / kernel_size
    filtered = np.convolve(white, kernel, mode="same")
    hp_kernel_size = max(1, sr // 150)
    hp_kernel = np.ones(hp_kernel_size, "float32") / hp_kernel_size
    bass = np.convolve(white, hp_kernel, mode="same")
    breath = filtered - bass * 0.5
    env = np.ones(n, "float32")
    fade_in = int(n * 0.15)
    fade_out = int(n * 0.4)
    env[:fade_in] = np.linspace(0, 1, fade_in)
    env[-fade_out:] = np.linspace(1, 0, fade_out)
    breath *= env
    peak = np.abs(breath).max()
    if peak > 0:
        breath /= peak
    return breath


def _compress_tail(audio: "np.ndarray", sr: int,
                   tail_sec: float = 0.4,
                   threshold_db: float = -20,
                   ratio: float = 3.0) -> "np.ndarray":
    """Apply soft-knee compression to the tail of audio."""
    import numpy as np
    tail_samples = int(sr * tail_sec)
    if len(audio) < tail_samples:
        return audio
    audio = audio.copy()
    tail = audio[-tail_samples:]
    threshold_lin = 10 ** (threshold_db / 20)
    envelope = np.abs(tail)
    smooth_n = max(1, sr // 100)
    kernel = np.ones(smooth_n, "float32") / smooth_n
    envelope = np.convolve(envelope, kernel, mode="same")
    gain = np.ones_like(tail)
    above = envelope > threshold_lin
    if above.any():
        env_db = np.where(above, 20 * np.log10(np.clip(envelope, 1e-10, None)), 0)
        thresh_db = 20 * np.log10(threshold_lin)
        compressed_db = thresh_db + (env_db - thresh_db) / ratio
        gain[above] = 10 ** ((compressed_db[above] - env_db[above]) / 20)
    tail *= gain
    audio[-tail_samples:] = tail
    return audio


def _speed_up_audio(audio: "np.ndarray", factor: float) -> "np.ndarray":
    """Speed up audio by factor using numpy interpolation."""
    import numpy as np
    if factor <= 1.0:
        return audio
    new_len = int(len(audio) / factor)
    indices = np.linspace(0, len(audio) - 1, new_len)
    return np.interp(indices, np.arange(len(audio)), audio).astype("float32")


def _fallback_ffmpeg_concat(wav_files: list[Path], output_wav: Path) -> None:
    """Simple ffmpeg concat fallback — no crossfade/stereo, but complete."""
    list_file = output_wav.parent / "_concat_list.txt"
    with open(list_file, "w") as f:
        for wf in wav_files:
            f.write(f"file '{wf}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), str(output_wav)],
        capture_output=True, timeout=120,
    )
    list_file.unlink(missing_ok=True)
    if output_wav.exists():
        print(f"  [TTS] Fallback concat done: {output_wav}")
    else:
        raise RuntimeError("Fallback ffmpeg concat also failed")


def _safe_merge(
    wav_files: list[Path],
    dialogue: list[tuple[str, str]],
    concat_wav: Path,
    cfg: TTSConfig,
    voice_pan: dict[str, tuple[float, float]] | None = None,
    timeout_sec: int = 300,
) -> None:
    """Advanced merge with timeout, falls back to simple ffmpeg concat."""
    result = {"ok": False, "error": None}

    def _do_merge():
        try:
            _merge_chunks_advanced(wav_files, dialogue, concat_wav, cfg, voice_pan=voice_pan)
            result["ok"] = True
        except Exception as e:
            result["error"] = str(e)

    t = threading.Thread(target=_do_merge, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)

    if t.is_alive() or not result["ok"]:
        reason = "timeout" if t.is_alive() else f"failed: {result['error']}"
        print(f"  [TTS] Advanced merge {reason}, falling back to simple concat")
        _fallback_ffmpeg_concat(wav_files, concat_wav)


def _merge_chunks_advanced(
    wav_files: list[Path],
    dialogue: list[tuple[str, str]],
    output_wav: Path,
    cfg: TTSConfig,
    voice_pan: dict[str, tuple[float, float]] | None = None,
) -> None:
    """Advanced merge: crossfade + short-chunk overlay + stereo pan + pink noise + LUFS.

    Args:
        voice_pan: Mapping of voice_name -> (left_gain, right_gain) for stereo panning.
                   If None, all voices are centered (1.0, 1.0).
    """
    import numpy as np
    import soundfile as sf

    sr = cfg.sample_rate
    crossfade_samples = int(sr * cfg.crossfade_ms / 1000)
    short_chunk_sec = 3.0
    overlap_samples = int(sr * 0.5)

    chunks: list[tuple[np.ndarray, str]] = []
    for i, wav_path in enumerate(wav_files):
        try:
            audio, file_sr = sf.read(wav_path, dtype="float32")
            if file_sr != sr:
                ratio = sr / file_sr
                new_len = int(len(audio) * ratio)
                audio = np.interp(np.linspace(0, len(audio) - 1, new_len),
                                  np.arange(len(audio)), audio)
            voice = dialogue[i][0] if i < len(dialogue) else cfg.default_voice
            chunks.append((audio, voice))
        except Exception as e:
            print(f"  [Merge] Skipping chunk {i}: {e}")

    if not chunks:
        raise RuntimeError("No valid chunks to merge")

    # Post-processing: speed up short reactions + compress tails
    for ci in range(len(chunks)):
        audio_c, voice_c = chunks[ci]
        dur = len(audio_c) / sr
        if dur < short_chunk_sec:
            factor = np.random.uniform(1.05, 1.10)
            audio_c = _speed_up_audio(audio_c, factor)
        audio_c = _compress_tail(audio_c, sr)
        chunks[ci] = (audio_c, voice_c)

    # Build merged mono audio with crossfade and short-chunk overlay
    merged_parts: list[tuple[np.ndarray, str]] = []

    i = 0
    while i < len(chunks):
        audio, voice = chunks[i]
        dur_sec = len(audio) / sr

        if (i + 1 < len(chunks)
                and len(chunks[i + 1][0]) / sr < short_chunk_sec
                and dur_sec > short_chunk_sec):
            next_audio, next_voice = chunks[i + 1]
            overlap = min(overlap_samples, len(audio), len(next_audio))
            tail_start = max(0, len(audio) - overlap)
            needed_len = tail_start + len(next_audio)
            if needed_len > len(audio):
                audio = np.pad(audio, (0, needed_len - len(audio)))
            audio[tail_start:tail_start + len(next_audio)] += next_audio * 0.85
            audio = np.clip(audio, -1.0, 1.0)
            merged_parts.append((audio, voice))
            i += 2
            continue

        merged_parts.append((audio, voice))
        i += 1

    breath_mono = _generate_breath(sr)
    breath_samples = len(breath_mono)

    total_samples = sum(len(a) for a, _ in merged_parts)
    total_samples -= crossfade_samples * max(0, len(merged_parts) - 1)
    total_samples += breath_samples * max(0, len(merged_parts) - 1)
    stereo = np.zeros((total_samples + sr, 2), dtype="float32")

    pos = 0
    for idx, (audio, voice) in enumerate(merged_parts):
        if voice_pan and voice in voice_pan:
            left_gain, right_gain = voice_pan[voice]
        else:
            left_gain = right_gain = 1.0

        end = pos + len(audio)
        if end > len(stereo):
            end = len(stereo)
            audio = audio[:end - pos]

        if idx > 0 and crossfade_samples > 0:
            fade_len = min(crossfade_samples, len(audio))
            fade_in = np.linspace(0, 1, fade_len, dtype="float32")
            fade_out = np.linspace(1, 0, fade_len, dtype="float32")
            stereo[pos:pos + fade_len, 0] *= fade_out
            stereo[pos:pos + fade_len, 1] *= fade_out
            audio[:fade_len] *= fade_in

        stereo[pos:end, 0] += audio * left_gain
        stereo[pos:end, 1] += audio * right_gain

        pos = end - crossfade_samples if idx < len(merged_parts) - 1 else end

    stereo = stereo[:pos + crossfade_samples]

    # Pink noise floor (disabled when pink_noise_db is None)
    if cfg.pink_noise_db is not None:
        pink_amplitude = 10 ** (cfg.pink_noise_db / 20)
        white = np.random.randn(len(stereo), 2).astype("float32")
        kernel_size = 16
        kernel = np.ones(kernel_size, dtype="float32") / kernel_size
        pink = np.zeros_like(white)
        for ch in range(2):
            pink[:, ch] = np.convolve(white[:, ch], kernel, mode="same")
        pink_max = np.abs(pink).max()
        if pink_max > 0:
            pink = pink / pink_max * pink_amplitude
        stereo += pink

    stereo = np.clip(stereo, -1.0, 1.0)

    # LUFS loudness normalization to -16 LUFS
    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(sr)
        loudness = meter.integrated_loudness(stereo)
        if loudness > -60:
            stereo = pyln.normalize.loudness(stereo, loudness, -16.0)
            stereo = np.clip(stereo, -1.0, 1.0)
    except Exception as e:
        print(f"  [Merge] LUFS normalization skipped: {e}")

    sf.write(str(output_wav), stereo, sr)
    dur = len(stereo) / sr
    print(f"  [Merge] Advanced merge done: {len(merged_parts)} parts -> {dur:.0f}s stereo, "
          f"crossfade={cfg.crossfade_ms}ms, pink={'off' if cfg.pink_noise_db is None else f'{cfg.pink_noise_db}dB'}")


# ── Main Entry ───────────────────────────────────────────────────────────

def synthesize(
    script: str,
    output_path: Path,
    cfg: TTSConfig | None = None,
    persist_dir: Path | None = None,
    enable_asr: bool = False,
    voice_pan: dict[str, tuple[float, float]] | None = None,
) -> Path:
    """Full TTS pipeline: clean text -> chunk -> subprocess synthesis -> merge to MP3.

    Args:
        script: Podcast script text (with optional role tags like 【Name】).
        output_path: Output MP3 path.
        cfg: TTS configuration. Uses defaults if None.
        persist_dir: Breakpoint resume directory. None = use temp dir.
        enable_asr: Enable ASR back-check (adds ~30% memory/time).
        voice_pan: Stereo panning per voice, e.g. {"Alice": (1.0, 0.7), "Bob": (0.7, 1.0)}.

    Returns:
        output_path
    """
    from .chunker import clean_markdown, split_chunks
    from .dialogue import parse_dialogue

    if cfg is None:
        cfg = TTSConfig()

    clean = clean_markdown(script)
    role_names = list(cfg.voices.keys()) if cfg.voices else None
    dialogue = parse_dialogue(clean, role_names=role_names, default_voice=cfg.default_voice)
    if not dialogue:
        raise RuntimeError("Script has no valid TTS content")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_chars = sum(len(c) for _, c in dialogue)
    voices_used = set(v for v, _ in dialogue)
    print(f"[TTS] Process-isolated mode ({', '.join(voices_used)})")
    print(f"[TTS] {len(dialogue)} chunks, {total_chars} chars")
    if persist_dir:
        print(f"[TTS] Resume dir: {persist_dir}")
    if not enable_asr:
        print(f"[TTS] ASR back-check disabled")

    def _run_synthesis(tmp: Path) -> tuple[list[Path], float]:
        t0 = time.time()
        if not enable_asr:
            os.environ["TTS_SKIP_ASR"] = "1"
        wav_files = _synthesize_all(dialogue, tmp, cfg, persist_dir=persist_dir)
        synth_time = time.time() - t0
        return wav_files, synth_time

    def _merge_and_encode(wav_files: list[Path], work_dir: Path) -> None:
        print(f"[TTS] Advanced merge {len(wav_files)} chunks (crossfade + stereo + pink noise)...")
        concat_wav = work_dir / "_concat_stereo.wav"
        _safe_merge(wav_files, dialogue, concat_wav, cfg, voice_pan=voice_pan)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(concat_wav),
             "-codec:a", "libmp3lame", "-b:a", cfg.mp3_bitrate,
             "-ar", str(cfg.sample_rate), str(output_path)],
            capture_output=True, timeout=180,
        )

    if persist_dir:
        persist_dir.mkdir(parents=True, exist_ok=True)
        wav_files, synth_time = _run_synthesis(persist_dir)
        if not wav_files:
            raise RuntimeError("All TTS chunks failed")
        _merge_and_encode(wav_files, persist_dir)
    else:
        with tempfile.TemporaryDirectory(prefix="loqui_tts_") as tmpdir:
            tmp = Path(tmpdir)
            wav_files, synth_time = _run_synthesis(tmp)
            if not wav_files:
                raise RuntimeError("All TTS chunks failed")
            _merge_and_encode(wav_files, tmp)

    if not output_path.exists():
        raise RuntimeError("ffmpeg encoding failed, MP3 not generated")

    size_kb = output_path.stat().st_size // 1024

    # MP3 integrity check
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(output_path)],
            capture_output=True, text=True, timeout=10,
        )
        mp3_duration = float(probe.stdout.strip()) if probe.stdout.strip() else 0
        mp3_min = mp3_duration / 60
        expected_min = total_chars / 800
        if mp3_min < expected_min * 0.4:
            print(f"[TTS] WARNING: MP3 duration too short: {mp3_min:.1f}min (expected ~{expected_min:.0f}min)")
        elif mp3_min < expected_min * 0.7:
            print(f"[TTS] WARNING: MP3 duration short: {mp3_min:.1f}min (expected ~{expected_min:.0f}min)")
        else:
            print(f"[TTS] MP3 duration OK: {mp3_min:.1f}min (expected ~{expected_min:.0f}min)")
    except Exception as e:
        print(f"[TTS] ffprobe check skipped: {e}")

    print(f"[TTS] Output: {output_path} ({size_kb} KB)")
    print(f"[TTS] Synthesis time: {synth_time:.0f}s ({synth_time/60:.1f}min)")
    return output_path
