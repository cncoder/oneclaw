#!/usr/bin/env python3.12
"""Generate a self-contained HTML player page for a podcast MP3 + script.

Output is one standalone file:
- Liquid-glass themed dark/light page (same aesthetic as Abel's daily digest).
- Fixed-bottom audio player with play/pause, ±15/30s skip, scrubber, time.
- Dialogue transcript rendered as chat bubbles, color-coded per role.
- LocalStorage resume: reopens at last playback position (keyed by MP3 hash).
- Click a bubble to jump to its estimated timestamp.
- Optional --embed mode bakes MP3 as base64 data URI (truly single-file).

Usage:
    python3.12 generate_player_html.py <mp3> <script.txt> <out.html>
                                         [--title "Episode Title"]
                                         [--subtitle "..."]
                                         [--embed]
                                         [--role-color Host_A=#6366f1 Host_B=#ec4899]

Script format (same as podcast_tts.py input):
    【Host_A】今天我们聊聊...
    【Host_B】好啊，这话题...
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html as _html
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    role: str
    text: str


def parse_script(path: Path) -> list[Segment]:
    """Parse a 【Role】tagged script into ordered segments."""
    raw = path.read_text(encoding="utf-8")
    parts = re.split(r"【([^】]+)】", raw)
    segs: list[Segment] = []
    # parts[0] = preamble (often empty); then [role, body, role, body, ...]
    if parts[0].strip():
        segs.append(Segment(role="", text=parts[0].strip()))
    for i in range(1, len(parts), 2):
        role = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if body:
            segs.append(Segment(role=role, text=body))
    return segs


def probe_duration(mp3: Path) -> float:
    """Return MP3 duration in seconds via ffprobe, or 0 on failure."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(mp3)],
            stderr=subprocess.DEVNULL, timeout=30,
        ).decode().strip()
        return float(out)
    except Exception:
        return 0.0


def file_hash(path: Path, length: int = 12) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


def _esc(text: str) -> str:
    return _html.escape(str(text)) if text else ""


# Default role palette — extend as needed.
_DEFAULT_COLORS = [
    "#6366f1",  # indigo
    "#ec4899",  # pink
    "#22d3ee",  # cyan
    "#a78bfa",  # violet
    "#f59e0b",  # amber
    "#34d399",  # emerald
]


def assign_colors(roles: list[str], overrides: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    i = 0
    for r in roles:
        if r in overrides:
            out[r] = overrides[r]
        else:
            out[r] = _DEFAULT_COLORS[i % len(_DEFAULT_COLORS)]
            i += 1
    return out


# ---------------------------------------------------------------------------
# CSS — same liquid-glass language as the daily digest template.
# ---------------------------------------------------------------------------

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;600;800&display=swap');
[data-theme="dark"]{
  --bg:#0a0a1a;--bg2:#10102a;
  --card:rgba(255,255,255,0.06);--card-hover:rgba(255,255,255,0.09);
  --text:#f4f4fc;--text2:#c8c8e0;--muted:#8888a8;
  --accent:#6366f1;--accent2:#818cf8;--accent-glow:rgba(99,102,241,0.3);
  --neon:#22d3ee;--neon-glow:rgba(34,211,238,0.25);
  --violet:#a78bfa;
  --border:rgba(255,255,255,0.12);--border2:rgba(255,255,255,0.18);
  --glass:rgba(255,255,255,0.05);
  --player-bg:rgba(12,12,28,0.88);
}
[data-theme="light"]{
  --bg:#f0f0f5;--bg2:#e8e8f0;
  --card:rgba(255,255,255,0.85);--card-hover:rgba(255,255,255,0.95);
  --text:#1a1a2e;--text2:#444466;--muted:#8888a0;
  --accent:#4f46e5;--accent2:#6366f1;--accent-glow:rgba(79,70,229,0.15);
  --neon:#0891b2;--neon-glow:rgba(8,145,178,0.15);
  --violet:#7c3aed;
  --border:rgba(0,0,0,0.08);--border2:rgba(0,0,0,0.12);
  --glass:rgba(255,255,255,0.6);
  --player-bg:rgba(255,255,255,0.88);
}
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:Inter,"PingFang SC","Hiragino Sans GB",-apple-system,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.85;font-size:15px;
  -webkit-font-smoothing:antialiased;padding-bottom:170px;overflow-x:hidden;
  transition:background 0.4s,color 0.4s;
}
[data-theme="dark"] body::before{
  content:'';position:fixed;inset:0;pointer-events:none;z-index:-1;
  background:
    radial-gradient(ellipse 600px 400px at 15% 20%,rgba(99,102,241,0.10),transparent),
    radial-gradient(ellipse 500px 350px at 85% 60%,rgba(236,72,153,0.07),transparent),
    radial-gradient(ellipse 400px 400px at 50% 90%,rgba(34,211,238,0.06),transparent);
}
.mono{font-family:'JetBrains Mono',monospace}
.theme-toggle{
  position:fixed;top:16px;right:16px;z-index:1000;
  width:40px;height:40px;border-radius:50%;border:1px solid var(--border2);
  background:var(--card);backdrop-filter:blur(12px);
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  font-size:18px;transition:background .3s,border-color .3s;
}
.theme-toggle:hover{background:var(--card-hover);border-color:var(--accent)}
.container{max-width:720px;margin:0 auto;padding:0 18px 40px}
.header{
  text-align:center;padding:56px 24px 36px;position:relative;overflow:hidden;
  background:var(--bg);margin-bottom:24px;
}
[data-theme="dark"] .header{
  background:linear-gradient(160deg,#0a0a1a 0%,#141430 50%,#1a0e40 100%);
}
.header::after{
  content:'';position:absolute;bottom:0;left:5%;right:5%;height:2px;
  background:linear-gradient(90deg,transparent,var(--accent),var(--neon),var(--violet),transparent);
  opacity:.4;border-radius:2px;
}
.header h1{
  font-size:34px;font-weight:800;letter-spacing:-1px;margin-bottom:6px;color:var(--text);
}
[data-theme="dark"] .header h1{
  background:linear-gradient(135deg,#fff 20%,var(--neon) 80%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
}
.header .sub{font-size:13px;color:var(--muted);letter-spacing:.5px}
.header .meta{
  display:inline-block;margin-top:16px;font-family:'JetBrains Mono',monospace;
  font-size:14px;font-weight:700;color:var(--neon);letter-spacing:1.5px;
}
[data-theme="dark"] .header .meta{text-shadow:0 0 12px var(--neon-glow)}
.roles{display:flex;justify-content:center;gap:10px;margin-top:14px;flex-wrap:wrap}
.role-chip{
  display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:999px;
  background:var(--glass);border:1px solid var(--border);font-size:12px;color:var(--text2);
}
.role-dot{width:8px;height:8px;border-radius:50%;box-shadow:0 0 8px currentColor}

/* -- Transcript bubbles -- */
.transcript{padding:6px 0}
.bubble{
  display:flex;flex-direction:column;margin-bottom:14px;padding:14px 16px;
  background:var(--card);border-radius:16px;border:1px solid var(--border);
  backdrop-filter:blur(20px) saturate(1.4);-webkit-backdrop-filter:blur(20px) saturate(1.4);
  cursor:pointer;transition:border-color .2s,background .2s,transform .1s;
  position:relative;overflow:hidden;
  animation:fadeUp .4s ease-out both;
}
.bubble::before{
  content:'';position:absolute;top:0;left:0;bottom:0;width:3px;
  background:var(--role-color,var(--accent));
}
.bubble:hover{background:var(--card-hover);border-color:var(--border2)}
.bubble:active{transform:scale(0.995)}
.bubble.active{
  border-color:var(--role-color,var(--accent));
  box-shadow:0 0 0 1px var(--role-color,var(--accent)),0 4px 24px rgba(0,0,0,.18);
}
.bubble-head{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.bubble-role{
  font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;
  color:var(--role-color,var(--accent));
}
.bubble-ts{font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace}
.bubble-text{font-size:15px;line-height:1.8;color:var(--text);white-space:pre-wrap;word-break:break-word}

/* -- Player -- */
.player{
  position:fixed;bottom:0;left:0;right:0;z-index:999;
  background:var(--player-bg);
  backdrop-filter:blur(30px) saturate(1.8);-webkit-backdrop-filter:blur(30px) saturate(1.8);
  border-top:1px solid var(--border2);padding:0;box-shadow:0 -8px 40px rgba(0,0,0,.3);
}
.player-wrap{max-width:720px;margin:0 auto;padding:14px 20px 16px}
.player-row1{display:flex;align-items:center;gap:16px;margin-bottom:10px}
.player-info{flex:1;min-width:0}
.player-title{font-size:14px;font-weight:700;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.player-sub{font-size:11px;color:var(--muted);margin-top:2px}
.player-controls{display:flex;align-items:center;gap:12px}
.player-btn-sm{
  width:34px;height:34px;border-radius:50%;border:1px solid var(--border);
  background:var(--glass);color:var(--text2);cursor:pointer;
  display:flex;align-items:center;justify-content:center;transition:all .15s;
}
.player-btn-sm:hover{color:var(--text);background:var(--card-hover);border-color:var(--accent)}
.player-btn-play{
  width:56px;height:56px;border-radius:50%;border:none;
  background:linear-gradient(135deg,var(--accent),var(--violet));
  color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;
  flex-shrink:0;
  box-shadow:0 0 24px var(--accent-glow),0 4px 12px rgba(0,0,0,.3);
  transition:transform .12s,box-shadow .2s;
}
.player-btn-play:hover{transform:scale(1.08);box-shadow:0 0 40px var(--accent-glow)}
.player-btn-play:active{transform:scale(.92)}
.player-btn-play svg{width:24px;height:24px}
.player-row2{display:flex;align-items:center;gap:10px}
.player-time{font-size:11px;color:var(--muted);white-space:nowrap;flex-shrink:0;
  font-family:'JetBrains Mono',monospace;min-width:38px}
.player-track{flex:1;position:relative;height:6px}
.player-track input[type=range]{
  width:100%;height:6px;-webkit-appearance:none;appearance:none;
  background:var(--glass);border-radius:3px;outline:none;cursor:pointer;
  position:relative;z-index:2;
}
.player-track input[type=range]::-webkit-slider-runnable-track{height:6px;border-radius:3px}
.player-track input[type=range]::-webkit-slider-thumb{
  -webkit-appearance:none;width:16px;height:16px;border-radius:50%;
  background:#fff;cursor:pointer;margin-top:-5px;
  box-shadow:0 0 10px var(--accent-glow),0 1px 3px rgba(0,0,0,.3);
  transition:transform .1s;
}
.player-track input[type=range]::-webkit-slider-thumb:hover{transform:scale(1.3)}
.player-progress-fill{
  position:absolute;top:0;left:0;height:6px;border-radius:3px;
  background:linear-gradient(90deg,var(--accent),var(--neon));
  pointer-events:none;z-index:1;transition:width .15s linear;
}
.player-extra{display:flex;align-items:center;gap:12px;margin-top:8px;font-size:11px;color:var(--muted)}
.speed-btn{
  background:var(--glass);border:1px solid var(--border);color:var(--text2);
  padding:3px 10px;border-radius:999px;cursor:pointer;font-family:'JetBrains Mono',monospace;
  font-size:11px;transition:all .15s;
}
.speed-btn:hover{color:var(--text);border-color:var(--accent)}

.footer{text-align:center;padding:28px 0 10px;font-size:11px;color:var(--muted);margin-top:24px}
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
@media(max-width:480px){
  body{padding-bottom:150px}
  .container{padding:0 14px 40px}
  .header{padding:44px 16px 28px}
  .header h1{font-size:26px}
  .bubble{padding:12px 14px;border-radius:14px}
  .bubble-text{font-size:14px}
  .player-wrap{padding:12px 14px 14px}
  .player-btn-play{width:48px;height:48px}
  .player-btn-play svg{width:20px;height:20px}
  .theme-toggle{top:12px;right:12px;width:36px;height:36px;font-size:16px}
}
"""


_PLAY_SVG = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>'
_PAUSE_SVG = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>'
_RW_SVG = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M11 18V6l-8.5 6 8.5 6zm.5-6l8.5 6V6l-8.5 6z"/></svg>'
_FF_SVG = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M4 18l8.5-6L4 6v12zm9-12v12l8.5-6L13 6z"/></svg>'


def render_html(
    *,
    title: str,
    subtitle: str,
    segments: list[Segment],
    role_colors: dict[str, str],
    mp3_src: str,
    duration: float,
    storage_key: str,
    total_chars: int,
) -> str:
    # Segment list with estimated timestamps (linear by char count).
    seg_js_items = []
    bubble_parts = []
    cum = 0
    for idx, s in enumerate(segments):
        frac_start = cum / total_chars if total_chars else 0.0
        cum += len(s.text)
        frac_end = cum / total_chars if total_chars else 0.0
        t_start = frac_start * duration if duration else 0.0
        color = role_colors.get(s.role, "var(--accent)")
        role_label = _esc(s.role) if s.role else "—"
        ts_label = format_time(t_start) if duration else ""
        bubble_parts.append(
            f'<div class="bubble" data-idx="{idx}" data-start="{frac_start:.6f}" '
            f'data-end="{frac_end:.6f}" style="--role-color:{_esc(color)}">'
            f'<div class="bubble-head">'
            f'<span class="bubble-role">{role_label}</span>'
            f'<span class="bubble-ts mono">{ts_label}</span>'
            f'</div>'
            f'<div class="bubble-text">{_esc(s.text)}</div>'
            f'</div>'
        )
        seg_js_items.append(f'{{s:{frac_start:.6f},e:{frac_end:.6f}}}')
    transcript_html = "\n".join(bubble_parts)
    segs_js = "[" + ",".join(seg_js_items) + "]"

    role_chips = "".join(
        f'<span class="role-chip"><span class="role-dot" style="background:{_esc(c)};color:{_esc(c)}"></span>{_esc(r)}</span>'
        for r, c in role_colors.items() if r
    )

    duration_label = format_time(duration) if duration else "--:--"

    return f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<button class="theme-toggle" id="themeToggle" aria-label="Toggle theme">&#127769;</button>
<div class="container">
  <div class="header">
    <h1>{_esc(title)}</h1>
    <div class="sub">{_esc(subtitle)}</div>
    <div class="meta mono">{len(segments)} 段 · {duration_label}</div>
    <div class="roles">{role_chips}</div>
  </div>
  <div class="transcript" id="transcript">
    {transcript_html}
  </div>
  <div class="footer">podcast-generator · Qwen3-TTS MLX · Liquid Glass Player</div>
</div>

<div class="player" id="playerBar">
  <div class="player-wrap">
    <div class="player-row1">
      <div class="player-info">
        <div class="player-title">{_esc(title)}</div>
        <div class="player-sub">{_esc(subtitle)}</div>
      </div>
      <div class="player-controls">
        <button class="player-btn-sm" id="rwBtn" aria-label="Rewind 15s">{_RW_SVG}</button>
        <button class="player-btn-play" id="playBtn" aria-label="Play">{_PLAY_SVG}</button>
        <button class="player-btn-sm" id="ffBtn" aria-label="Forward 30s">{_FF_SVG}</button>
      </div>
    </div>
    <div class="player-row2">
      <span class="player-time mono" id="curTime">0:00</span>
      <div class="player-track">
        <div class="player-progress-fill" id="progressFill"></div>
        <input type="range" id="progressBar" min="0" max="100" value="0" step="0.01">
      </div>
      <span class="player-time mono" id="totalTime">{duration_label}</span>
    </div>
    <div class="player-extra">
      <button class="speed-btn" id="speedBtn">1.0x</button>
      <span id="segLabel">—</span>
    </div>
  </div>
  <audio id="podcastAudio" preload="metadata"><source src="{_esc(mp3_src)}" type="audio/mpeg"></audio>
</div>

<script>
(function(){{
  var a=document.getElementById('podcastAudio'),
      pb=document.getElementById('playBtn'),
      p=document.getElementById('progressBar'),
      fill=document.getElementById('progressFill'),
      ct=document.getElementById('curTime'),
      tt=document.getElementById('totalTime'),
      rw=document.getElementById('rwBtn'),
      ff=document.getElementById('ffBtn'),
      sb=document.getElementById('speedBtn'),
      segLabel=document.getElementById('segLabel'),
      transcript=document.getElementById('transcript'),
      bubbles=transcript.querySelectorAll('.bubble'),
      segs={segs_js},
      k='{_esc(storage_key)}',
      speeds=[1,1.25,1.5,1.75,2,0.75],
      speedIdx=0,
      playSvg='{_PLAY_SVG}',
      pauseSvg='{_PAUSE_SVG}';

  function fmt(s){{var m=Math.floor(s/60),c=Math.floor(s%60);return m+':'+(c<10?'0':'')+c;}}

  // restore playback position
  try{{ var sv=parseFloat(localStorage.getItem(k+':t')||'0'); if(sv>1)a.currentTime=sv; }}catch(e){{}}

  pb.onclick=function(){{
    if(a.paused){{ a.play(); pb.innerHTML=pauseSvg; }}
    else{{ a.pause(); pb.innerHTML=playSvg; }}
  }};
  rw.onclick=function(){{ a.currentTime=Math.max(0,a.currentTime-15); }};
  ff.onclick=function(){{ a.currentTime=Math.min(a.duration||0,a.currentTime+30); }};
  sb.onclick=function(){{ speedIdx=(speedIdx+1)%speeds.length; a.playbackRate=speeds[speedIdx]; sb.textContent=speeds[speedIdx].toFixed(2).replace(/0$/,'')+'x'; }};

  var lastActive=-1;
  function syncBubble(frac){{
    var idx=-1;
    for(var i=0;i<segs.length;i++){{ if(frac>=segs[i].s && frac<=segs[i].e){{ idx=i; break; }} }}
    if(idx!==lastActive){{
      if(lastActive>=0 && bubbles[lastActive]) bubbles[lastActive].classList.remove('active');
      if(idx>=0 && bubbles[idx]){{
        bubbles[idx].classList.add('active');
        var rect=bubbles[idx].getBoundingClientRect();
        if(rect.top<80||rect.bottom>window.innerHeight-200) bubbles[idx].scrollIntoView({{behavior:'smooth',block:'center'}});
        segLabel.textContent='Seg '+(idx+1)+' / '+segs.length;
      }}
      lastActive=idx;
    }}
  }}

  a.ontimeupdate=function(){{
    if(!a.duration) return;
    var pct=(a.currentTime/a.duration)*100;
    p.value=pct; fill.style.width=pct+'%';
    ct.textContent=fmt(a.currentTime);
    tt.textContent=fmt(a.duration);
    syncBubble(a.currentTime/a.duration);
    if(Math.floor(a.currentTime)%3===0){{ try{{ localStorage.setItem(k+':t',String(a.currentTime)); }}catch(e){{}} }}
  }};
  a.onloadedmetadata=function(){{ tt.textContent=fmt(a.duration); }};
  a.onplay=function(){{ pb.innerHTML=pauseSvg; }};
  a.onpause=function(){{ pb.innerHTML=playSvg; }};
  a.onended=function(){{ pb.innerHTML=playSvg; fill.style.width='0%'; try{{ localStorage.removeItem(k+':t'); }}catch(e){{}} }};

  p.oninput=function(){{
    if(!a.duration) return;
    a.currentTime=(p.value/100)*a.duration;
    fill.style.width=p.value+'%';
    try{{ localStorage.setItem(k+':t',String(a.currentTime)); }}catch(e){{}}
  }};

  // click bubble to seek
  bubbles.forEach(function(b){{
    b.addEventListener('click',function(){{
      var s=parseFloat(b.getAttribute('data-start'))||0;
      if(a.duration){{
        a.currentTime=s*a.duration;
        if(a.paused) a.play();
      }}
    }});
  }});

  // theme toggle
  var html=document.documentElement,btn=document.getElementById('themeToggle'),tk=k+':theme';
  try{{
    var saved=localStorage.getItem(tk);
    if(saved){{ html.setAttribute('data-theme',saved); btn.textContent=saved==='light'?'🌙':'☀️'; }}
  }}catch(e){{}}
  btn.onclick=function(){{
    var cur=html.getAttribute('data-theme')||'dark';
    var nx=cur==='dark'?'light':'dark';
    html.setAttribute('data-theme',nx);
    btn.textContent=nx==='light'?'🌙':'☀️';
    try{{ localStorage.setItem(tk,nx); }}catch(e){{}}
  }};
}})();
</script>
</body>
</html>
"""


def format_time(sec: float) -> str:
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    return f"{m}:{s:02d}"


def parse_role_color_overrides(items: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not items:
        return out
    for it in items:
        if "=" in it:
            k, v = it.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mp3", type=Path, help="Podcast MP3 file")
    ap.add_argument("script", type=Path, help="Script .txt with 【Role】 tags")
    ap.add_argument("out", type=Path, help="Output .html path")
    ap.add_argument("--title", default="", help="Page title (default: MP3 filename)")
    ap.add_argument("--subtitle", default="Qwen3-TTS · Liquid Glass Player")
    ap.add_argument("--embed", action="store_true",
                    help="Inline MP3 as base64 data URI (truly single-file, larger output)")
    ap.add_argument("--role-color", nargs="*", metavar="Role=#hex",
                    help="Override role colors, e.g. --role-color Host_A=#6366f1 Host_B=#ec4899")
    args = ap.parse_args()

    if not args.mp3.exists():
        print(f"ERROR: MP3 not found: {args.mp3}", file=sys.stderr)
        return 2
    if not args.script.exists():
        print(f"ERROR: script not found: {args.script}", file=sys.stderr)
        return 2

    segments = parse_script(args.script)
    if not segments:
        print("ERROR: no segments parsed from script (expected 【Role】 tags)", file=sys.stderr)
        return 3

    roles_in_order: list[str] = []
    for s in segments:
        if s.role and s.role not in roles_in_order:
            roles_in_order.append(s.role)
    role_colors = assign_colors(roles_in_order, parse_role_color_overrides(args.role_color))

    duration = probe_duration(args.mp3)
    total_chars = sum(len(s.text) for s in segments) or 1
    mp3_hash = file_hash(args.mp3)
    storage_key = f"pgen-{args.mp3.stem}-{mp3_hash}"

    if args.embed:
        data = args.mp3.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        mp3_src = f"data:audio/mpeg;base64,{b64}"
        size_mb = len(data) / (1 << 20)
        print(f"[embed] MP3 inlined as base64 ({size_mb:.1f} MiB)", file=sys.stderr)
    else:
        try:
            mp3_src = str(args.mp3.resolve().relative_to(args.out.resolve().parent))
        except ValueError:
            mp3_src = str(args.mp3.resolve())

    title = args.title or args.mp3.stem

    html = render_html(
        title=title,
        subtitle=args.subtitle,
        segments=segments,
        role_colors=role_colors,
        mp3_src=mp3_src,
        duration=duration,
        storage_key=storage_key,
        total_chars=total_chars,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")

    size_kb = args.out.stat().st_size / 1024
    print(f"[ok] wrote {args.out} ({size_kb:.1f} KiB) — {len(segments)} segments, "
          f"{len(roles_in_order)} roles, {format_time(duration) if duration else 'unknown'} audio",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
