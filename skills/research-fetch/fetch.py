#!/usr/bin/env python3
"""fetch.py — Research-Fetch：三路并行提取 + LLM 校准的最准确网页抓取

架构：
  Playwright attach abel-chrome (或 launch headless) 渲染页面
    ↓
  3 路并行提取：
    A. Trafilatura（HTML 主文提取，学术冠军 F1>0.94）
    B. Readability.js（Mozilla 阅读模式，JS 注入）
    C. VLM 看全页截图（Sonnet 4.6 看图理解）
    ↓
  LLM 合并校准（Claude 对齐三路输出）
    ↓
  精修 markdown + structured metadata + confidence

输出 JSON：
  {
    "url": ...,
    "final_url": ...,        # 跳转后
    "title": ...,
    "author": ...,
    "published_at": ...,
    "language": ...,
    "markdown": ...,         # 主文 markdown（标题层级/列表/表格保留）
    "excerpt": ...,          # 150 字摘要
    "images": [...],
    "links_outbound": [...],
    "confidence": 0.95,      # 三路一致性（0-1）
    "sources": {             # 三路各自的输出摘要（debug）
      "trafilatura_chars": 4830,
      "readability_chars": 4721,
      "vlm_chars": 4920,
    },
    "elapsed_s": 18.3,
    "tokens_used": {...}
  }

用法：
  python fetch.py <url> [--no-vlm] [--headless] [--full-page-screenshot]

依赖：trafilatura, playwright, openai, lxml_html_clean
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import trafilatura
from openai import OpenAI

# ─── 配置 ─────────────────────────────────────────────────────────────────
SKILL_DIR = Path(__file__).parent.resolve()
READABILITY_JS = (SKILL_DIR / "Readability.js").read_text()
# Output dir for per-run artifacts (raw html, screenshot, debug logs).
# Override with RF_OUT_DIR; default keeps it tucked under the user workspace.
_default_out = Path.home() / ".openclaw/workspace/data/tmp/research-fetch"
if not _default_out.parent.parent.exists():
    _default_out = Path.home() / ".cache/research-fetch"
OUT_DIR = Path(os.getenv("RF_OUT_DIR", str(_default_out)))
OUT_DIR.mkdir(parents=True, exist_ok=True)

CDP_URL = os.getenv("RF_CDP_URL", "http://127.0.0.1:9222")
LITELLM_BASE = os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1")
LITELLM_KEY = os.getenv("LITELLM_KEY", "sk-litellm-local")
VLM_MODEL = os.getenv("RF_VLM_MODEL", "claude-sonnet-4-6")

for v in ("http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","all_proxy"):
    os.environ.pop(v, None)


# ─── 1. Playwright 抓页 ─────────────────────────────────────────────────────

async def fetch_page(url: str, *, use_cdp=True, full_page=True, wait_ms=2500):
    """渲染页面，返回 (html, screenshot_bytes, final_url, title)。"""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        if use_cdp:
            try:
                browser = await p.chromium.connect_over_cdp(CDP_URL)
                ctx = browser.contexts[0]
                owns_browser = False
            except Exception as e:
                print(f"[fetch] CDP 连接失败 fallback launch: {e}", file=sys.stderr)
                browser = await p.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    viewport={"width": 1400, "height": 1000},
                    locale="zh-CN",
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                )
                owns_browser = True
        else:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1400, "height": 1000},
                locale="zh-CN",
            )
            owns_browser = True

        page = await ctx.new_page()
        page.on("dialog", lambda d: asyncio.create_task(d.accept()))

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            await page.wait_for_timeout(wait_ms)

            final_url = page.url
            title = await page.title()
            html = await page.content()

            # 滚到底触发懒加载（可选）
            try:
                await page.evaluate("""
                    async () => {
                        const step = window.innerHeight * 0.8;
                        const max = document.body.scrollHeight;
                        for (let y=0; y<max; y+=step) {
                            window.scrollTo(0, y);
                            await new Promise(r => setTimeout(r, 200));
                        }
                        window.scrollTo(0, 0);
                    }
                """)
                await page.wait_for_timeout(500)
            except Exception:
                pass

            # 再抓一次 HTML（懒加载之后）
            try:
                html = await page.content()
            except Exception:
                pass

            screenshot = await page.screenshot(
                type="jpeg", quality=80, full_page=full_page
            )

            # Readability.js 提取（在页面内 eval）
            readability_data = None
            try:
                readability_data = await page.evaluate(
                    f"""() => {{
                        {READABILITY_JS};
                        try {{
                            const doc = document.cloneNode(true);
                            const reader = new Readability(doc);
                            const article = reader.parse();
                            if (!article) return null;
                            return {{
                                title: article.title,
                                byline: article.byline,
                                content: article.content,
                                textContent: article.textContent,
                                length: article.length,
                                excerpt: article.excerpt,
                                siteName: article.siteName,
                                lang: article.lang,
                                publishedTime: article.publishedTime,
                            }};
                        }} catch (e) {{
                            return {{_error: e.message}};
                        }}
                    }}"""
                )
            except Exception as e:
                readability_data = {"_error": str(e)[:120]}

        finally:
            try:
                await page.close()
            except Exception:
                pass
            if owns_browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    return html, screenshot, final_url, title, readability_data


# ─── 2. Trafilatura 提取 ────────────────────────────────────────────────────

def extract_trafilatura(html: str) -> dict:
    """Trafilatura 主文提取（markdown + 元数据）。"""
    try:
        md = trafilatura.extract(
            html,
            output_format="markdown",
            include_images=True,
            include_links=True,
            include_tables=True,
            favor_precision=True,
            include_comments=False,
        ) or ""
        meta = trafilatura.extract_metadata(html)
        return {
            "markdown": md,
            "title": getattr(meta, "title", None) if meta else None,
            "author": getattr(meta, "author", None) if meta else None,
            "date": getattr(meta, "date", None) if meta else None,
            "description": getattr(meta, "description", None) if meta else None,
            "language": getattr(meta, "language", None) if meta else None,
            "tags": getattr(meta, "tags", None) if meta else None,
            "sitename": getattr(meta, "sitename", None) if meta else None,
            "char_count": len(md),
        }
    except Exception as e:
        return {"_error": str(e)[:200], "markdown": "", "char_count": 0}


# ─── 3. 三路合并 LLM 校准 ──────────────────────────────────────────────────

SYSTEM_PROMPT = """你是网页内容提取校准专家。任务是把给定网页的三路信息合并为**最准确**的结构化输出：
- 来源 A: Trafilatura markdown（学术冗许率 F1>0.94）
- 来源 B: Readability HTML（Mozilla 阅读模式已清理导航/广告，保留结构）
- 来源 C: 页面全页截图（视觉真相判据）

核心原则（严格执行）：
1. **以 Readability HTML 为主体转 markdown**，这是三者中保留结构最完整且已去噪的源
2. 用 Trafilatura 交叉验证主文内容准确性（版本不同时以 Readability 为准）
3. 用截图验证是否有遗漏（截图看到但两路都没捕获的内容）
4. markdown 要**完整**，不断点、不截断、不摘要
5. 保留所有结构：# 标题层级 / 列表 / 表格 / 代码块投 ``` / 图片 ![alt](url) / 引用 >
6. 中英混排保持原文语言
7. 不翻译、不改写、不扩充

严格返回 JSON（包在 ```json 代码块）：
{
  "title": "...",
  "author": "...",
  "published_at": "YYYY-MM-DD 或 ISO",
  "language": "zh|en|...",
  "markdown": "主文完整 markdown（建议 3000-10000 字，不要刪减）",
  "excerpt": "150-200 字摘要",
  "confidence": 0.95,
  "rejected_noise": ["导航栏","侧边栏广告",...],
  "notable_media": [{"type":"image|video|table|code","description":"..."}],
  "source_used": "readability|trafilatura|hybrid"
}

缺字段用 null，没的不要编造。"""


def calibrate_with_llm(
    url: str, trafilatura_out: dict, readability_out: dict | None,
    screenshot: bytes, final_title: str
) -> dict:
    llm = OpenAI(api_key=LITELLM_KEY, base_url=LITELLM_BASE)

    traf_md = trafilatura_out.get("markdown") or ""
    read_html = ""
    read_meta = {}
    if readability_out and not readability_out.get("_error"):
        # **用 HTML**（完整结构）而不是 textContent（纯文）
        read_html = readability_out.get("content") or ""
        read_meta = {
            "title": readability_out.get("title"),
            "byline": readability_out.get("byline"),
            "siteName": readability_out.get("siteName"),
            "publishedTime": readability_out.get("publishedTime"),
            "lang": readability_out.get("lang"),
        }

    # 截图 base64
    shot_b64 = base64.b64encode(screenshot).decode()

    # 如果主文太长（>120k），Trafilatura/Readability 各截 120k，告知 LLM 截断
    def trim(s, n=120000):
        if len(s) <= n:
            return s, False
        return s[:n] + f"\n\n[...主文过长已截 {len(s)-n} 字]", True

    traf_md_t, traf_truncated = trim(traf_md)
    read_html_t, read_truncated = trim(read_html)

    content = [
        {"type": "text", "text": f"""URL: {url}
页面 title: {final_title}

=== 来源 A: Trafilatura (markdown) {'[截断]' if traf_truncated else ''} ===
标题: {trafilatura_out.get('title')}
作者: {trafilatura_out.get('author')}
日期: {trafilatura_out.get('date')}
语言: {trafilatura_out.get('language')}
站点: {trafilatura_out.get('sitename')}
字符数: {trafilatura_out.get('char_count')}
主文:
{traf_md_t or '(空)'}

=== 来源 B: Readability.js (HTML, **你的主要参考**) {'[截断]' if read_truncated else ''} ===
标题: {read_meta.get('title')}
作者: {read_meta.get('byline')}
发布时间: {read_meta.get('publishedTime')}
语言: {read_meta.get('lang')}
站点: {read_meta.get('siteName')}
HTML 字符数: {len(read_html)}
HTML 内容（你的任务就是把这个转成 markdown，保留完整结构）:
{read_html_t or '(空)'}

=== 来源 C: 页面全页截图（验证用）===

执行任务：以 Readability HTML 为主体转为 markdown，用 Trafilatura 和截图交叉验证。markdown 必须完整，返回 JSON。"""},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{shot_b64}"}},
    ]

    resp = llm.chat.completions.create(
        model=VLM_MODEL,
        max_tokens=16000,  # 支持长文完整重写
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    )
    raw = resp.choices[0].message.content or ""
    usage = resp.usage

    # Debug: 存 LLM 原始输入输出
    try:
        import tempfile
        log_dir = OUT_DIR / "_llm_debug"
        log_dir.mkdir(exist_ok=True)
        ts_str = str(int(time.time()))
        (log_dir / f"{ts_str}_raw_response.txt").write_text(raw, encoding="utf-8")
    except Exception:
        pass

    m = re.search(r"```json\s*([\s\S]*?)```", raw) or re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {
            "_error": "LLM 无 JSON",
            "_raw": raw[:500],
            "tokens_used": {"in": usage.prompt_tokens, "out": usage.completion_tokens} if usage else None,
        }
    json_str = m.group(1) if m.lastindex else m.group(0)

    # 先试标准 JSON parse
    data = None
    try:
        data = json.loads(json_str)
    except Exception:
        # 失败就用 json-repair（专门修 LLM 常见 JSON 错误：未转义引号、尾逗号、缺引号等）
        try:
            from json_repair import repair_json
            repaired = repair_json(json_str, return_objects=True)
            if isinstance(repaired, dict):
                data = repaired
        except Exception as e:
            pass

    if not data:
        return {
            "_error": "JSON parse 失败（包括 json-repair）",
            "_raw": json_str[:500],
            "tokens_used": {"in": usage.prompt_tokens, "out": usage.completion_tokens} if usage else None,
        }

    data["tokens_used"] = {"in": usage.prompt_tokens, "out": usage.completion_tokens} if usage else None
    return data


# ─── 主流程 ─────────────────────────────────────────────────────────────────

def extract_link_domains(markdown: str) -> list[str]:
    urls = re.findall(r"https?://[^\s)]+", markdown)
    from urllib.parse import urlparse
    domains = set()
    for u in urls:
        try:
            domains.add(urlparse(u).netloc)
        except Exception:
            pass
    return sorted(domains)[:20]


async def main_async(url: str, use_cdp=True, use_vlm=True, full_page=True):
    t0 = time.time()
    result = {"url": url, "_timings": {}}

    # 1. 抓页
    ts = time.time()
    html, screenshot, final_url, title, readability = await fetch_page(
        url, use_cdp=use_cdp, full_page=full_page,
    )
    result["_timings"]["fetch_s"] = round(time.time() - ts, 1)
    result["final_url"] = final_url

    # 存 raw 用于 debug
    raw_dir = OUT_DIR / f"raw_{int(time.time())}"
    raw_dir.mkdir(exist_ok=True)
    (raw_dir / "page.html").write_text(html, encoding="utf-8", errors="replace")
    (raw_dir / "page.jpg").write_bytes(screenshot)
    if readability:
        (raw_dir / "readability.json").write_text(json.dumps(readability, ensure_ascii=False, indent=2))

    # 2. Trafilatura
    ts = time.time()
    traf = extract_trafilatura(html)
    result["_timings"]["trafilatura_s"] = round(time.time() - ts, 2)
    (raw_dir / "trafilatura.md").write_text(traf.get("markdown") or "", encoding="utf-8")

    # 3. LLM 校准（vlm 可关）
    if use_vlm:
        ts = time.time()
        calibrated = calibrate_with_llm(url, traf, readability, screenshot, title)
        result["_timings"]["llm_s"] = round(time.time() - ts, 1)

        # 防 LLM 输出 markdown 缩水：如果 LLM 的 markdown 长度 < Trafilatura，用 Trafilatura 原版兼顾 LLM 的 metadata
        llm_md = calibrated.get("markdown") or ""
        traf_md_str = traf.get("markdown") or ""
        read_txt = (readability or {}).get("textContent") or ""
        # 选最长且应该保留结构的
        if len(llm_md) < 0.8 * max(len(traf_md_str), len(read_txt) * 0.5):
            final_md = traf_md_str if traf_md_str else llm_md
            result["_fallback_to_trafilatura"] = True
        else:
            final_md = llm_md

        result.update({
            "title": calibrated.get("title") or traf.get("title") or title,
            "author": calibrated.get("author") or traf.get("author"),
            "published_at": calibrated.get("published_at") or traf.get("date"),
            "language": calibrated.get("language") or traf.get("language"),
            "markdown": final_md,
            "excerpt": calibrated.get("excerpt") or traf.get("description"),
            "confidence": calibrated.get("confidence"),
            "rejected_noise": calibrated.get("rejected_noise"),
            "notable_media": calibrated.get("notable_media"),
            "tokens_used": calibrated.get("tokens_used"),
        })
        if calibrated.get("_error"):
            result["_llm_error"] = calibrated["_error"]
    else:
        result.update({
            "title": traf.get("title") or title,
            "author": traf.get("author"),
            "published_at": traf.get("date"),
            "language": traf.get("language"),
            "markdown": traf.get("markdown") or "",
            "excerpt": traf.get("description"),
            "confidence": None,
        })

    result["links_outbound"] = extract_link_domains(result.get("markdown", ""))
    result["sources"] = {
        "trafilatura_chars": traf.get("char_count"),
        "readability_chars": len((readability or {}).get("textContent") or ""),
        "html_chars": len(html),
        "screenshot_kb": len(screenshot) // 1024,
    }
    result["_raw_dir"] = str(raw_dir)
    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--no-cdp", action="store_true", help="独立 Chromium 而非 attach abel-chrome")
    p.add_argument("--no-vlm", action="store_true", help="跳过 LLM 校准（只用 Trafilatura 快速）")
    p.add_argument("--viewport-only", action="store_true", help="只截当前 viewport 不全页")
    p.add_argument("--md-only", action="store_true", help="只输出 markdown，不输出 JSON")
    args = p.parse_args()

    res = asyncio.run(main_async(
        args.url, use_cdp=not args.no_cdp, use_vlm=not args.no_vlm,
        full_page=not args.viewport_only,
    ))

    if args.md_only:
        print(res.get("markdown", ""))
    else:
        # stdout: JSON
        print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
