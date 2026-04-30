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

    # 1. Apple Silicon
    mach = platform.machine()
    if mach == "arm64":
        _print("Apple Silicon", "ok", f"arch={mach}")
        results.append(("apple_silicon", "ok"))
    else:
        _print("Apple Silicon", "fail", f"arch={mach}",
               "mlx-audio 仅支持 Apple Silicon，Intel/Linux 不可用")
        results.append(("apple_silicon", "fail"))

    # 2. python3.12
    py = shutil.which("python3.12")
    if py:
        v = subprocess.run([py, "--version"], capture_output=True, text=True).stdout.strip()
        _print("python3.12", "ok", v)
        results.append(("python312", "ok"))
    else:
        _print("python3.12", "fail", "not found", "brew install python@3.12")
        results.append(("python312", "fail"))

    # 3. ffmpeg + ffprobe
    for bin_ in ("ffmpeg", "ffprobe"):
        p = shutil.which(bin_)
        if p:
            _print(bin_, "ok", p)
            results.append((bin_, "ok"))
        else:
            _print(bin_, "fail", "not found", "brew install ffmpeg")
            results.append((bin_, "fail"))

    # 4. Python packages (only check if python3.12 present)
    if py:
        pkgs = ["mlx", "mlx_audio", "numpy", "soundfile", "pyloudnorm"]
        missing = []
        for pkg in pkgs:
            r = subprocess.run([py, "-c", f"import {pkg}"], capture_output=True)
            if r.returncode != 0:
                missing.append(pkg)
        if not missing:
            _print("pip packages", "ok", f"{len(pkgs)} ok")
            results.append(("pip", "ok"))
        else:
            _print("pip packages", "fail", f"missing: {', '.join(missing)}",
                   "pip3.12 install mlx mlx-audio numpy soundfile pydub pyloudnorm pyyaml boto3")
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
