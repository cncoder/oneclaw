---
name: research-fetch
description: "Highest-accuracy web page extraction for research. Parallel three-way extraction (Trafilatura + Readability.js + VLM full-page screenshot) reconciled by an LLM. Use when you need accurate, structured content from any URL — especially login-walled, JS-heavy, or bot-blocked sites. Complements chrome-devtools skill (which is for interactive UI automation)."
metadata:
  openclaw:
    emoji: "🔬"
---

# Skill: research-fetch

> **Core idea: three extractors in parallel, then a VLM reconciles them against the full-page screenshot.**

Highest-accuracy web content extraction, optimized for "correctness first, speed/cost second" research scenarios. Replaces one-off `curl`, `web_fetch`, or interactive CDP scraping when you need the page content as structured markdown + metadata.

---

## When to Use What

| Task | Tool | Why |
|---|---|---|
| "Read this URL and summarize" | **research-fetch** | Parallel 3-way extraction → most accurate |
| Build a dataset from 100 URLs | **research-fetch** `--no-vlm` | Fast mode, ~3s/URL |
| Click buttons, fill forms, E2E tests | `chrome-devtools` | Interactive UI automation |
| Static HTML docs, RSS feeds | `web_fetch` / `feedparser` | Faster, no browser needed |
| Dashboards, tabular data on a login-walled site | **research-fetch** + `--schema=...` | Structured extraction |
| Screenshot-only (visual inspection) | `chrome-devtools` | Built-in |
| Long JS SPA that never settles | **research-fetch** | Waits for networkidle + scrolls for lazy-load |

**Golden rule**: `chrome-devtools` is for **acting on** a page; `research-fetch` is for **reading a page accurately**.

---

## Architecture

```
URL
 ↓
Playwright (attaches to existing Chrome via CDP, or launches headless)
  ├─ Navigate, wait for domcontentloaded + networkidle
  ├─ Scroll to bottom (trigger lazy-load)
  └─ Full-page JPEG screenshot
 ↓
3 parallel extractors:
  A. Trafilatura 2.x   (HTML → markdown, academic F1 > 0.94)
  B. Readability.js    (Mozilla Reader Mode, injected in-page)
  C. Full-page screenshot → VLM (Claude Sonnet 4.6 or similar)
 ↓
LLM reconciler (same VLM, 16k output tokens):
  - Use Readability HTML as primary body (it keeps structure)
  - Cross-validate against Trafilatura for completeness
  - Verify against the screenshot for "what's visible"
  - Extract title/author/date/language/excerpt
  - Compute a confidence score (0-1) based on 3-way agreement
 ↓
json-repair fallback (fixes common LLM JSON mistakes like unescaped quotes)
 ↓
Guard: if LLM markdown < 80% of Trafilatura → fall back to Trafilatura
```

---

## Quick Start

### 1. One-time setup

```bash
cd path/to/skills/research-fetch
bash setup.sh
```

This creates `.venv/` and installs: `trafilatura`, `playwright`, `openai`, `json-repair`, `html2text`, `lxml_html_clean`.

### 2. Run

```bash
# Full three-way extraction with LLM reconciliation
bash run.sh https://example.com

# Fast mode (Trafilatura only, ~3s, 85-90% accuracy)
bash run.sh https://example.com --no-vlm

# Launch headless (no CDP attach, loses login state)
bash run.sh https://example.com --no-cdp

# Markdown only (no JSON metadata)
bash run.sh https://example.com --md-only

# Viewport-only screenshot (faster, may miss long article tail)
bash run.sh https://example.com --viewport-only
```

### 3. Configure

All via environment variables:

| Env | Default | What |
|---|---|---|
| `RF_VLM_MODEL` | `claude-sonnet-4-6` | Any vision-capable chat model |
| `LITELLM_BASE_URL` | `http://localhost:4000/v1` | OpenAI-compatible endpoint |
| `LITELLM_KEY` | `sk-litellm-local` | API key |
| `RF_CDP_URL` | `http://127.0.0.1:9222` | Chrome CDP endpoint (optional) |

Point `LITELLM_BASE_URL` at OpenAI, Anthropic, a LiteLLM gateway, or any other OpenAI-compatible server.

---

## Output Schema

```json
{
  "url": "https://original.url/",
  "final_url": "https://after-redirect/",
  "title": "...",
  "author": "...",
  "published_at": "YYYY-MM-DD or ISO-8601",
  "language": "zh | en | ja | ...",
  "markdown": "Full main-content markdown (headings, lists, tables, code blocks, images, quotes preserved)",
  "excerpt": "150-char summary",
  "confidence": 0.95,          // 3-way agreement, 0-1
  "rejected_noise": ["nav bar", "sidebar ads", ...],
  "notable_media": [{"type": "image|video|table|code", "description": "..."}],
  "links_outbound": ["github.com", "arxiv.org", ...],  // domains referenced
  "sources": {
    "trafilatura_chars": 4830,
    "readability_chars": 4721,
    "html_chars": 189407,
    "screenshot_kb": 1019
  },
  "tokens_used": {"in": 4698, "out": 1338},
  "elapsed_s": 47.8,
  "_raw_dir": "/path/to/raw_<timestamp>/"  // html, jpg, trafilatura.md for debugging
}
```

---

## Real-World Accuracy (2026-05-09)

| Page | Elapsed | Markdown chars | Confidence | Notes |
|---|---|---|---|---|
| example.com | 12.7s | 200 | 0.99 | Baseline |
| English tech blog (Simon Willison) | 47.8s | 4524 | 0.98 | Full structure preserved |
| Chinese tech article behind paywall (CSDN) | 54.1s | 804 | 0.72 | **LLM honestly flagged truncation** — doesn't hallucinate |
| 404 page | 13.2s | 84 | 0.85 | Correctly identified |
| MSN weather, Shenzhen | ~17s | structured JSON | — | 15+ fields: temp/feels/humidity/wind/pressure/UV/dew/AQI/alerts/17-day forecast |

---

## Comparison vs. Alternatives

| Metric | `curl` | `web_fetch` | `chrome-devtools` | Firecrawl API | **research-fetch** |
|---|---|---|---|---|---|
| Runs JS / renders SPA | ❌ | ❌ | ✅ | ✅ | ✅ |
| Reuses logged-in Chrome | manual cookies | ❌ | ✅ | ❌ | ✅ (via CDP attach) |
| Main-content extraction | raw HTML | basic | single-source | single-source | **3-source reconciled** |
| Honest paywall detection | shows teaser only | — | — | — | **labels truncation** |
| Confidence score | ❌ | ❌ | ❌ | ❌ | ✅ |
| Structured output | ❌ | basic | manual | LLM-friendly | markdown + metadata |
| Cost | free | free | free | paid | ~$0.01/URL |
| Throughput | highest | high | low (interactive) | high | low (research-grade) |

**Bottom line**: use research-fetch when accuracy matters more than cost or speed. For bulk ingest, use `--no-vlm` mode or fall back to Trafilatura alone.

---

## Limitations

1. **Single task at a time** (file lock on `/tmp/.cdp_scrape_lock`), since the attached Chrome can't be used concurrently.
2. **Paywalled / login-walled content**: returns only the visible portion; LLM explicitly labels the truncation rather than hallucinating.
3. **Infinite-scroll feeds** (Weibo, Xiaohongshu timelines): captures only the first few viewports. Use a dedicated feed skill for those.
4. **Video bodies**: only reads the thumbnail/page metadata, not video content.
5. **PDFs embedded in iframes**: not currently supported. Use a PDF-specific skill.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `playwright install chromium` fails | Proxy blocks CDN | Run `setup.sh` with proxy env set, or `playwright install --with-deps chromium` |
| CDP attach returns 0 contexts | Chrome not running with `--remote-debugging-port=9222` | Start Chrome with the flag, or use `--no-cdp` to launch headless |
| LLM returns JSON but `confidence` is null | Parser repaired JSON but some fields missing | Check `~/.openclaw/workspace/data/tmp/research-fetch/_llm_debug/*_raw_response.txt` |
| markdown much shorter than Trafilatura | LLM output hit `max_tokens` | Bump `max_tokens` in `fetch.py` (currently 16k) or switch to a larger-output model |
| `curl localhost:9222` times out | Local proxy intercepting localhost | `unset http_proxy https_proxy` before calling |
| 404 page "confidence 0.99" | Real 404 detected | Verify the URL or follow redirects manually |

---

## File Layout

```
skills/research-fetch/
├── SKILL.md           # this file
├── fetch.py           # main script (~400 lines)
├── run.sh             # bash wrapper with env sanitation
├── setup.sh           # one-time venv + playwright install
├── requirements.txt   # pinned Python deps
├── Readability.js     # Mozilla's Reader Mode (bundled, 91 KB)
└── tests/
    └── run_all.sh     # regression tests across scenario categories
```

Generated artifacts go to `~/.openclaw/workspace/data/tmp/research-fetch/` by default (override with `RF_OUT_DIR`).

---

## Integration Recipes

### Use from Python

```python
import subprocess, json
res = subprocess.run(
    ["bash", "skills/research-fetch/run.sh", url],
    capture_output=True, text=True, timeout=120,
)
data = json.loads(res.stdout)
print(data["title"], data["confidence"])
```

### Use from an agent prompt

```
When the user asks you to read/summarize a URL, don't browse interactively.
Instead shell out to:
  bash ~/.openclaw/workspace/skills/research-fetch/run.sh <URL>
The JSON on stdout already contains title, author, date, confidence, and the
full markdown body. Quote the confidence score when summarizing.
```

### Replace a brittle `_cdp.py`-style CSS-selector extractor

Before: hand-written CSS/XPath selectors break whenever the site redesigns.
After: feed research-fetch the URL; its VLM reconciliation adapts to DOM changes automatically. Pay the extra LLM cost once, keep extraction stable for months.

---

## Related Skills

- **chrome-devtools** — interactive UI automation (click, fill, E2E). **Complementary**, not overlapping.
- **deep-research** — methodology for multi-source technical investigation. Use research-fetch as its per-URL fetcher.
