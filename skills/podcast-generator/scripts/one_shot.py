#!/usr/bin/env python3
"""One-shot podcast generator: topic → research → script → TTS → HTML.

Pipeline:
  - per-stage log with icons + elapsed
  - non-fatal try/except per stage (research fail → digest fallback, TTS fail → still HTML)
  - --rebuild skips research + script, reuses existing script.txt
  - metadata.json at the end with all paths + stats
  - output at output/YYYY-MM-DD/{slug}/

Usage:
    python3.12 one_shot.py "AI 能否取代程序员"
    python3.12 one_shot.py "BTC 到底值多少" --duration 30min --style debate
    python3.12 one_shot.py "..." --rebuild                # reuse existing script.txt
    python3.12 one_shot.py "..." --skip-research          # skip web research
    python3.12 one_shot.py "..." --skip-tts --skip-html   # script only

LLM backend priority:
    1. claude CLI (if in PATH) — zero config
    2. ANTHROPIC_API_KEY / OPENAI_API_KEY (stdin prompt, manual paste)
    3. manual mode: print prompt, wait for user to paste script path
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# ── Stage logging (抄自 roundtable/generate.py) ──────────────────────

ICONS = {"ok": "✅", "fail": "❌", "warn": "⚠", "start": "⏳", "skip": "⏭"}


def _log_stage(stage: str, status: str, detail: str = "", elapsed: float = 0) -> None:
    icon = ICONS.get(status, "ℹ")
    el = f" ({elapsed:.0f}s)" if elapsed else ""
    sep = f": {detail}" if detail else ""
    print(f"  {icon} [{stage}] {status}{el}{sep}", flush=True)


# ── Slug / dir ────────────────────────────────────────────────────────

def _slug(topic: str, max_len: int = 40) -> str:
    """URL-safe slug. Falls back to md5 when slugify unavailable."""
    try:
        from slugify import slugify  # type: ignore
        s = slugify(topic, max_length=max_len)
        if s:
            return s
    except ImportError:
        pass
    # Fallback: keep ASCII alnum + dash, collapse others, md5 tail
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", topic).strip("-").lower()[:20]
    h = hashlib.md5(topic.encode("utf-8")).hexdigest()[:8]
    return f"{ascii_part}-{h}" if ascii_part else h


# ── LLM backends ──────────────────────────────────────────────────────

def _call_claude_cli(prompt: str, timeout: int = 600) -> str | None:
    """Call claude CLI in print mode. Returns None if not available or fails."""
    claude = shutil.which("claude")
    if not claude:
        return None
    try:
        # Pass prompt via stdin to avoid arg parsing issues with long/special chars.
        # --bare: minimal mode (skip hooks, plugins, auto-memory); prompt stays clean.
        r = subprocess.run(
            [claude, "--print", "--bare"],
            input=prompt,
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        print(f"    claude CLI rc={r.returncode}, stderr={r.stderr[:300]}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"    claude CLI 超时 {timeout}s", file=sys.stderr)
    except Exception as e:
        print(f"    claude CLI 异常: {e}", file=sys.stderr)
    return None


def _call_anthropic_api(prompt: str, system: str = "") -> str | None:
    """Call Anthropic API via ANTHROPIC_API_KEY if present."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import urllib.request
        import urllib.error
        body = json.dumps({
            "model": "claude-sonnet-4-6",
            "max_tokens": 16000,
            "system": system or None,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read())
        parts = data.get("content", [])
        return "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
    except Exception as e:
        print(f"    Anthropic API 异常: {e}", file=sys.stderr)
        return None


def _llm(prompt: str, system: str = "", label: str = "llm") -> str | None:
    """Try each LLM backend in order. Returns None if all fail."""
    merged = f"{system}\n\n{prompt}" if system else prompt
    # 1. claude CLI
    out = _call_claude_cli(merged)
    if out:
        return out
    # 2. Anthropic API
    out = _call_anthropic_api(prompt, system)
    if out:
        return out
    # 3. Manual fallback
    print(f"\n  ℹ [{label}] 无可用 LLM，转为手动模式。")
    print(f"     把下方 prompt 贴给 Claude/ChatGPT，把回答保存到一个文件，路径贴回来：\n")
    print("─" * 60)
    print(merged)
    print("─" * 60)
    resp_path = input("\n  >>> 回答所在的文件路径 (Enter 跳过): ").strip()
    if resp_path and Path(resp_path).exists():
        return Path(resp_path).read_text(encoding="utf-8").strip()
    return None


# ── Research ──────────────────────────────────────────────────────────

def _research(topic: str, out_dir: Path, extra_context: str = "") -> tuple[str, str]:
    """Return (research_text, data_date). data_date = 'realtime' or a YYYY-MM-DD."""
    research_path = out_dir / "research.json"

    prompt = f"""你是播客调研员。围绕以下话题做结构化调研，输出 JSON。

话题：{topic}
{f"额外背景：{extra_context}" if extra_context else ""}

请输出如下结构的 JSON（不要 markdown 代码块，直接 JSON）：
{{
  "facts": ["5-10 条核心事实，必须客观、可验证"],
  "data_points": ["5-10 条关键数据点（带数字）"],
  "opinions": [
    {{"source": "人名/机构名", "viewpoint": "观点一句话"}}
  ],
  "controversies": ["2-4 条争议焦点/对立立场"],
  "predictions": ["2-4 条前瞻预测"],
  "sources": [
    {{"title": "来源标题", "url": "URL", "source_type": "news/paper/blog/forum"}}
  ]
}}

要求：至少 3 个独立信息源；避免空话套话；有争议就说清两边立场，不和稀泥。"""

    out = _llm(prompt, label="research")
    if not out:
        _log_stage("research", "warn", "无调研数据，LLM 仅凭自身知识写稿")
        research_path.write_text("{}", encoding="utf-8")
        return "", "none"

    # Try parse JSON; fall back to raw text
    cleaned = out.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        research_path.write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        return cleaned, "realtime"
    except json.JSONDecodeError:
        research_path.write_text(cleaned, encoding="utf-8")
        return cleaned, "realtime"


# ── Script generation ────────────────────────────────────────────────

SYSTEM_PROMPT = """你是一个顶级播客脚本写手，负责为双人播客撰写对话脚本。

## 角色设定
- 主持人A（标记：【Host_A】）：博学、犀利、爱抖机灵，善于类比和反问，偶尔自嘲
- 主持人B（标记：【Host_B】）：感性、直觉敏锐、善于从普通人视角切入，偶尔吐槽主持人A

## 格式约束
- **段落长度（重要）**：70% 段落 30-80 字，20% 段落 80-150 字，10% 段落 150-290 字
  - 原因：TTS 引擎 chunk_hard_limit=290，超过会被切分产生合并痕迹
- 长短交替，避免连续 5 段都是长段
- 格式严格：【Host_A】...（换行）【Host_B】...（换行）交替
- 不要加任何 markdown 标记（不要 #、*、- 等）
- 穿插语气词（嗯、对、哈哈、其实、你看、我觉得）

## 内容约束
- 叙事优先用具体案例引入，再从案例提炼方法论
- 同一对话中不得出现互相矛盾的观点（若讨论争议则明确标注为不同立场）
- 比喻和类比为信息服务，全文最多 10 个比喻
- 每个话题要有起承转合：引入→展开→碰撞→总结/金句

## 输出
- 只输出对话脚本正文，不要输出标题、摘要、导语
- 两人交替发言"""


def _gen_script(topic: str, target_chars: int, style: str, research: str) -> str | None:
    minutes = round(target_chars / 387)
    research_block = f"\n\n参考素材：\n{research}" if research else ""
    prompt = f"""请为以下主题生成播客对话脚本。

话题：{topic}
目标字数：{target_chars} 字（约 {minutes} 分钟音频）
风格：{style}

要求：
1. 只输出对话脚本正文，不要输出标题、摘要、导语
2. 每行格式：【Host_A】对话内容 或 【Host_B】对话内容
3. 段落长度按 70/20/10 分布（30-80 / 80-150 / 150-290 字）
4. 总字数控制在 {target_chars} 字左右{research_block}"""

    return _llm(prompt, system=SYSTEM_PROMPT, label="script")


def _sanitize_script(script: str) -> tuple[str, list[str]]:
    """Ensure【Host_A】/【Host_B】tags; strip markdown; alternate checks."""
    warnings: list[str] = []
    # Strip markdown code fences
    script = re.sub(r"^```.*?\n", "", script, flags=re.MULTILINE)
    script = re.sub(r"\n```\s*$", "", script)
    # Normalize tag variants (【主持人A】/[Host_A]/（A）)
    script = re.sub(r"[\[【]\s*(?:主持人)?\s*[Aa](?:\s*：)?\s*[\]】]", "【Host_A】", script)
    script = re.sub(r"[\[【]\s*(?:主持人)?\s*[Bb](?:\s*：)?\s*[\]】]", "【Host_B】", script)
    script = re.sub(r"[\[【]\s*Host[_\-]?A\s*[\]】]", "【Host_A】", script, flags=re.IGNORECASE)
    script = re.sub(r"[\[【]\s*Host[_\-]?B\s*[\]】]", "【Host_B】", script, flags=re.IGNORECASE)

    lines = [l for l in script.split("\n") if l.strip()]
    tag_lines = [l for l in lines if l.startswith("【Host_A】") or l.startswith("【Host_B】")]
    if len(tag_lines) < 4:
        warnings.append(f"仅找到 {len(tag_lines)} 行带角色标记，脚本可能格式错误")
    return "\n".join(tag_lines) if tag_lines else script, warnings


# ── Pipeline ────────────────────────────────────────────────────────

DURATION_MAP = {
    "5min": 1933, "10min": 3870, "15min": 5800, "20min": 7740,
    "30min": 11600, "45min": 17400, "60min": 23200,
}


def run(args: argparse.Namespace) -> int:
    t_start = time.time()
    today = date.today().isoformat()
    slug = _slug(args.topic)

    out_base = Path(args.output_dir) if args.output_dir else (Path.cwd() / "output")
    out_dir = out_base / today / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    target_chars = DURATION_MAP.get(args.duration, 5800)

    print("=" * 60)
    print(f"  话题: {args.topic}")
    print(f"  风格: {args.style}  时长: {args.duration} (~{target_chars}字)")
    print(f"  输出: {out_dir}")
    print("=" * 60)

    script_path = out_dir / "script.txt"
    mp3_path = out_dir / "podcast.mp3"
    html_path = out_dir / "index.html"

    # ── Doctor pre-check ─────────────────────────────────────────
    if not args.skip_doctor:
        _log_stage("doctor", "start")
        r = subprocess.run([sys.executable, str(SCRIPT_DIR / "doctor.py"), "--quiet"])
        if r.returncode != 0:
            _log_stage("doctor", "fail", "运行 python3.12 doctor.py 查看详情")
            return 2
        _log_stage("doctor", "ok")

    # ── 1. Research ─────────────────────────────────────────────
    research_text = ""
    data_date = "none"
    if args.rebuild and script_path.exists():
        _log_stage("research", "skip", "rebuild 模式")
    elif args.skip_research:
        _log_stage("research", "skip", "--skip-research")
    else:
        _log_stage("research", "start")
        t0 = time.time()
        try:
            research_text, data_date = _research(args.topic, out_dir, args.context)
            _log_stage("research", "ok", f"date={data_date}, chars={len(research_text)}",
                       elapsed=time.time() - t0)
        except Exception as e:
            _log_stage("research", "fail", str(e)[:150], elapsed=time.time() - t0)

    # ── 2. Script ───────────────────────────────────────────────
    if args.rebuild and script_path.exists():
        script = script_path.read_text(encoding="utf-8")
        _log_stage("script", "skip", f"rebuild: {len(script)} 字")
    else:
        _log_stage("script", "start")
        t0 = time.time()
        script = _gen_script(args.topic, target_chars, args.style, research_text)
        if not script:
            _log_stage("script", "fail", "LLM 未返回内容，退出", elapsed=time.time() - t0)
            return 3
        script, warns = _sanitize_script(script)
        for w in warns:
            print(f"    ⚠ {w}")
        script_path.write_text(script, encoding="utf-8")
        _log_stage("script", "ok", f"{len(script)} 字 → {script_path.name}",
                   elapsed=time.time() - t0)

    # ── 3. TTS ─────────────────────────────────────────────────
    duration_display = ""
    if args.skip_tts:
        _log_stage("tts", "skip")
    elif mp3_path.exists() and not args.force_tts:
        _log_stage("tts", "skip", f"已存在 {mp3_path.name}")
    else:
        _log_stage("tts", "start")
        t0 = time.time()
        tts_cmd = [
            sys.executable if sys.version_info[:2] == (3, 12) else "python3.12",
            str(SCRIPT_DIR / "podcast_tts.py"),
            str(script_path),
            str(mp3_path),
        ]
        if args.enable_asr:
            tts_cmd.append("--enable-asr")
        try:
            r = subprocess.run(tts_cmd, timeout=args.tts_timeout)
            if r.returncode == 0 and mp3_path.exists():
                duration_display = _probe_duration(mp3_path)
                size_mb = mp3_path.stat().st_size / 1024 / 1024
                _log_stage("tts", "ok", f"{size_mb:.1f}MB, {duration_display}",
                           elapsed=time.time() - t0)
            else:
                _log_stage("tts", "fail", f"rc={r.returncode}", elapsed=time.time() - t0)
        except subprocess.TimeoutExpired:
            _log_stage("tts", "fail", f"超时 {args.tts_timeout}s", elapsed=time.time() - t0)
        except Exception as e:
            _log_stage("tts", "fail", str(e)[:150], elapsed=time.time() - t0)

    # ── 4. HTML ────────────────────────────────────────────────
    if args.skip_html or not mp3_path.exists():
        if args.skip_html:
            _log_stage("html", "skip")
        else:
            _log_stage("html", "skip", "无 MP3")
    else:
        _log_stage("html", "start")
        t0 = time.time()
        try:
            cmd = [
                sys.executable if sys.version_info[:2] == (3, 12) else "python3.12",
                str(SCRIPT_DIR / "generate_player_html.py"),
                str(mp3_path),
                str(script_path),
                str(html_path),
                "--title", args.topic,
                "--subtitle", f"Host_A × Host_B · {duration_display or args.duration}",
            ]
            r = subprocess.run(cmd, timeout=60)
            if r.returncode == 0 and html_path.exists():
                _log_stage("html", "ok", html_path.name, elapsed=time.time() - t0)
            else:
                _log_stage("html", "fail", f"rc={r.returncode}", elapsed=time.time() - t0)
        except Exception as e:
            _log_stage("html", "fail", str(e)[:150], elapsed=time.time() - t0)

    # ── 5. Publish (optional) ──────────────────────────────────
    cdn_url = ""
    if args.publish and mp3_path.exists() and html_path.exists():
        _log_stage("publish", "start")
        t0 = time.time()
        try:
            cmd = [
                sys.executable if sys.version_info[:2] == (3, 12) else "python3.12",
                str(SCRIPT_DIR / "publish_to_cdn.py"), "publish",
                "--mp3", str(mp3_path), "--html", str(html_path), "--slug", slug,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if r.returncode == 0:
                m = re.search(r"https?://\S+\.cloudfront\.net\S+", r.stdout)
                cdn_url = m.group(0) if m else "published"
                _log_stage("publish", "ok", cdn_url, elapsed=time.time() - t0)
            else:
                _log_stage("publish", "fail", r.stderr[:150], elapsed=time.time() - t0)
        except Exception as e:
            _log_stage("publish", "fail", str(e)[:150], elapsed=time.time() - t0)

    # ── metadata.json ──────────────────────────────────────────
    meta = {
        "topic": args.topic,
        "style": args.style,
        "duration": args.duration,
        "target_chars": target_chars,
        "script_chars": len(script) if script else 0,
        "date": today,
        "data_date": data_date,
        "slug": slug,
        "output_dir": str(out_dir),
        "script_path": str(script_path) if script_path.exists() else None,
        "mp3_path": str(mp3_path) if mp3_path.exists() else None,
        "html_path": str(html_path) if html_path.exists() else None,
        "duration_display": duration_display,
        "cdn_url": cdn_url or None,
        "elapsed_sec": round(time.time() - t_start, 1),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    total = time.time() - t_start
    print("=" * 60)
    print(f"  ✅ 完成 — 总耗时 {total:.0f}s ({total/60:.1f} min)")
    print(f"  输出目录: {out_dir}")
    for label, p in [("script", script_path), ("mp3", mp3_path), ("html", html_path)]:
        if p.exists():
            print(f"    {label}: {p}")
    if cdn_url:
        print(f"    cdn:    {cdn_url}")
    print("=" * 60)
    return 0


def _probe_duration(mp3: Path) -> str:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(mp3)],
            capture_output=True, text=True, timeout=10,
        )
        dur = float(r.stdout.strip())
        m, s = divmod(int(dur), 60)
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(
        description="One-shot podcast: topic → research → script → TTS → HTML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("topic", help="播客主题（一句话）")
    ap.add_argument("--duration", default="15min",
                    choices=list(DURATION_MAP.keys()), help="目标时长")
    ap.add_argument("--style", default="deep_dive",
                    choices=["debate", "deep_dive", "casual", "interview", "tutorial"])
    ap.add_argument("--context", default="", help="额外背景信息（调研阶段注入）")
    ap.add_argument("--output-dir", default="", help="输出根目录（默认 ./output）")
    ap.add_argument("--rebuild", action="store_true",
                    help="复用已有 script.txt，跳过调研+脚本生成")
    ap.add_argument("--skip-research", action="store_true")
    ap.add_argument("--skip-tts", action="store_true")
    ap.add_argument("--skip-html", action="store_true")
    ap.add_argument("--skip-doctor", action="store_true")
    ap.add_argument("--force-tts", action="store_true", help="即使 MP3 存在也重做")
    ap.add_argument("--enable-asr", action="store_true", help="TTS ASR 回检（慢但更稳）")
    ap.add_argument("--tts-timeout", type=int, default=3600)
    ap.add_argument("--publish", action="store_true", help="上传 CloudFront (需 AWS)")
    args = ap.parse_args()

    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n中断。已生成文件保留，可用 --rebuild 续跑。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
