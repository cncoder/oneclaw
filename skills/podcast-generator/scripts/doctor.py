#!/usr/bin/env python3
"""Pre-flight check for podcast-generator skill.

Usage:
    python3.12 doctor.py           # full check
    python3.12 doctor.py --quiet   # exit-code only
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


OK = "✅"
WARN = "⚠"
FAIL = "❌"


def _print(label: str, status: str, detail: str = "", fix: str = ""):
    icon = {"ok": OK, "warn": WARN, "fail": FAIL}[status]
    print(f"  {icon} {label:24s} {detail}")
    if fix and status == "fail":
        print(f"       fix: {fix}")


def check() -> list[tuple[str, str]]:
    """Return list of (label, status) pairs. status: ok|warn|fail."""
    results: list[tuple[str, str]] = []

    # 1. Platform detection — pick backend (mlx for Apple Silicon, torch otherwise)
    mach = platform.machine()
    sysname = platform.system()
    forced = os.environ.get("TTS_BACKEND", "").strip().lower()
    if forced in ("mlx", "torch"):
        backend = forced
    elif sysname == "Darwin" and mach == "arm64":
        backend = "mlx"
    else:
        backend = "torch"
    _print("platform", "ok", f"{sysname} {mach} → backend={backend}")
    results.append(("platform", "ok"))
    results.append(("backend", backend))  # stash for later checks

    # 2. python3.12 (mlx) or python3.11+ (torch — broader compatibility)
    if backend == "mlx":
        py = shutil.which("python3.12")
        if py:
            v = subprocess.run([py, "--version"], capture_output=True, text=True).stdout.strip()
            _print("python3.12", "ok", v)
            results.append(("python", "ok"))
        else:
            _print("python3.12", "fail", "not found", "brew install python@3.12")
            results.append(("python", "fail"))
    else:
        # Torch backend accepts 3.10-3.12 (qwen-tts requires transformers 4.57+)
        py = shutil.which("python3.11") or shutil.which("python3.12") or shutil.which("python3.10") or shutil.which("python3")
        if py:
            v = subprocess.run([py, "--version"], capture_output=True, text=True).stdout.strip()
            ok = any(ver in v for ver in ["3.10", "3.11", "3.12"])
            if ok:
                _print("python3.10+", "ok", f"{v} ({py})")
                results.append(("python", "ok"))
            else:
                _print("python3.10+", "fail", v, "需要 python3.10–3.12；AL2023: dnf install python3.11")
                results.append(("python", "fail"))
        else:
            _print("python3.10+", "fail", "not found", "AL2023: sudo dnf install -y python3.11 python3.11-pip")
            results.append(("python", "fail"))

    # 3. ffmpeg + ffprobe
    fix_hint = "brew install ffmpeg" if sysname == "Darwin" else \
               "sudo dnf install -y ffmpeg (AL2023: 可能需 epel/rpmfusion) 或 static build"
    for bin_ in ("ffmpeg", "ffprobe"):
        p = shutil.which(bin_)
        if p:
            _print(bin_, "ok", p)
            results.append((bin_, "ok"))
        else:
            _print(bin_, "fail", "not found", fix_hint)
            results.append((bin_, "fail"))

    # 4. Python packages — pkg list depends on backend
    if py:
        if backend == "mlx":
            pkgs = ["mlx", "mlx_audio", "numpy", "soundfile", "pyloudnorm"]
            fix = "pip3.12 install mlx mlx-audio numpy soundfile pydub pyloudnorm pyyaml boto3"
        else:
            pkgs = ["torch", "qwen_tts", "numpy", "soundfile", "pyloudnorm"]
            fix = "pip install torch qwen-tts numpy soundfile pydub pyloudnorm pyyaml boto3"
        missing = []
        for pkg in pkgs:
            r = subprocess.run([py, "-c", f"import {pkg}"], capture_output=True)
            if r.returncode != 0:
                missing.append(pkg)
        if not missing:
            _print("pip packages", "ok", f"{len(pkgs)} ok ({backend})")
            results.append(("pip", "ok"))
        else:
            _print("pip packages", "fail", f"missing: {', '.join(missing)}", fix)
            results.append(("pip", "fail"))

    # 5. Reference voices
    skill_dir = Path(__file__).parent.parent
    voices_dir = skill_dir / "assets" / "voices"
    wavs = list(voices_dir.glob("*.wav")) if voices_dir.exists() else []
    if len(wavs) >= 2:
        _print("reference voices", "ok", f"{len(wavs)} wav in {voices_dir.name}/")
        results.append(("voices", "ok"))
    else:
        _print("reference voices", "fail", f"found {len(wavs)} (need ≥2)",
               f"put WAVs into {voices_dir}")
        results.append(("voices", "fail"))

    # 5b. Linux/x86 GPU check (torch backend only — informational)
    if backend == "torch" and py:
        r = subprocess.run(
            [py, "-c", "import torch;print('cuda' if torch.cuda.is_available() else 'cpu')"],
            capture_output=True, text=True,
        )
        device = r.stdout.strip() if r.returncode == 0 else "unknown"
        if device == "cuda":
            _print("torch device", "ok", "CUDA available — will use GPU")
        else:
            _print("torch device", "warn",
                   "CPU only — OK (实测 c7i.8xlarge RTF ~1.35x，比 GPU 更划算)")
        results.append(("device", "ok"))

    # 6. HF model cache (warn only — will auto-download first run)
    hf = Path(os.environ.get("HF_HOME", "~/.cache/huggingface")).expanduser()
    model_hint = "Qwen3-TTS"
    if hf.exists() and any(model_hint in str(p) for p in hf.rglob("*") if p.is_dir()):
        _print("HF model cache", "ok", "Qwen3-TTS cached")
        results.append(("hf_cache", "ok"))
    else:
        _print("HF model cache", "warn", "will download ~800MB on first run")
        results.append(("hf_cache", "warn"))

    # 7. LLM backend — claude CLI preferred, fallback to manual
    claude = shutil.which("claude")
    if claude:
        # Smoke-test with a tiny prompt via stdin (matches one_shot.py invocation)
        try:
            r = subprocess.run(
                [claude, "--print", "--bare"],
                input="say 'ok' and nothing else",
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0 and r.stdout.strip():
                _print("LLM backend", "ok", f"claude CLI → {claude} (smoke ok)")
                results.append(("llm", "ok"))
            else:
                _print("LLM backend", "warn",
                       f"claude CLI found but smoke-test failed (rc={r.returncode})",
                       "check `claude --print --bare` works manually")
                results.append(("llm", "warn"))
        except Exception as e:
            _print("LLM backend", "warn", f"claude CLI smoke-test error: {str(e)[:80]}")
            results.append(("llm", "warn"))
    elif os.environ.get("ANTHROPIC_API_KEY"):
        _print("LLM backend", "ok", "ANTHROPIC_API_KEY set")
        results.append(("llm", "ok"))
    elif os.environ.get("OPENAI_API_KEY"):
        _print("LLM backend", "ok", "OPENAI_API_KEY set")
        results.append(("llm", "ok"))
    else:
        _print("LLM backend", "warn", "no claude CLI / API key",
               "install Claude Code or export ANTHROPIC_API_KEY")
        results.append(("llm", "warn"))

    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.quiet:
        print("=" * 60)
        print("  podcast-generator doctor")
        print("=" * 60)

    results = check()
    fails = [r for r in results if r[1] == "fail"]
    warns = [r for r in results if r[1] == "warn"]

    if not args.quiet:
        print("-" * 60)
        if fails:
            print(f"  {FAIL} {len(fails)} failed, {len(warns)} warning(s)")
            print(f"     fix the failures above before running one_shot.py")
        elif warns:
            print(f"  {OK} ready (with {len(warns)} warning, non-blocking)")
        else:
            print(f"  {OK} all checks passed")
        print("=" * 60)

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
