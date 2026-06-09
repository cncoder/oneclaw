#!/usr/bin/env python3
"""混合抓取核心：先本地 HTTP（快、免费），遇到反爬/JS 页/正文过短时升级到 AWS Bedrock AgentCore 云端浏览器。

设计原则：能用 HTTP 就别开云端浏览器（省钱）。云端 session 按 CPU/内存秒计费。
"""

import os
import re
import html2text

# ── 可调参数（环境变量覆盖）──────────────────────────────────────────
REGION = os.environ.get("AGENTCORE_REGION", "us-west-2")


def _default_browser_id() -> str:
    """优先用 SDK 自带的系统默认 browser 常量，AWS 升级默认实例时跟着 SDK 自动拿最新。
    取不到再回退到当前已知值。环境变量 AGENTCORE_BROWSER_ID 可强制覆盖。"""
    env = os.environ.get("AGENTCORE_BROWSER_ID")
    if env:
        return env
    try:
        from bedrock_agentcore.tools.browser_client import DEFAULT_IDENTIFIER
        return DEFAULT_IDENTIFIER
    except Exception:
        return "aws.browser.v1"


BROWSER_ID = _default_browser_id()
SESSION_TIMEOUT = int(os.environ.get("AGENTCORE_SESSION_TIMEOUT", "900"))
MAX_CHARS = int(os.environ.get("DEEPSEARCH_MAX_CHARS", "50000"))
# 正文短于这个阈值，判定本地 HTTP 没抓到真内容（多半是 JS 渲染/反爬），升级云端
MIN_BODY_CHARS = int(os.environ.get("DEEPSEARCH_MIN_BODY_CHARS", "500"))
HTTP_TIMEOUT = float(os.environ.get("DEEPSEARCH_HTTP_TIMEOUT", "15"))

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

# 反爬常见信号：命中就直接升级云端浏览器，不浪费一次本地 HTTP
_ANTIBOT_MARKERS = (
    "cf-browser-verification", "cloudflare", "just a moment",
    "captcha", "are you a robot", "enable javascript", "px-captcha",
    "access denied", "request unsuccessful",
)


def _html_to_markdown(html: str) -> str:
    h = html2text.HTML2Text()
    h.ignore_images = True
    h.ignore_emphasis = False
    h.body_width = 0  # 不硬折行
    md = h.handle(html or "")
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md


def _truncate(text: str):
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS], True
    return text, False


def _looks_blocked(html: str, markdown: str) -> bool:
    low = (html or "").lower()
    if any(m in low for m in _ANTIBOT_MARKERS):
        return True
    if len(markdown) < MIN_BODY_CHARS:
        return True
    return False


def fetch_http(url: str):
    """本地 HTTP 抓取。返回 (markdown, html, error)。"""
    import httpx
    try:
        with httpx.Client(
            follow_redirects=True, timeout=HTTP_TIMEOUT,
            headers={"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml"},
        ) as c:
            r = c.get(url)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "text/html" not in ctype and "text" not in ctype:
                return (f"[non-html content-type: {ctype}]", "", None)
            md = _html_to_markdown(r.text)
            return (md, r.text, None)
    except Exception as e:
        return ("", "", f"http_error: {e}")


def fetch_browser(url: str, wait_selector: str | None = None):
    """AWS AgentCore 云端浏览器抓取（能跑 JS、过反爬）。返回 (markdown, error)。"""
    try:
        from bedrock_agentcore.tools.browser_client import browser_session
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return ("", f"import_error: {e}")

    try:
        with browser_session(REGION, identifier=BROWSER_ID) as client:
            ws_url, headers = client.generate_ws_headers()
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(ws_url, headers=headers)
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=10000)
                    except Exception:
                        pass
                else:
                    page.wait_for_timeout(1500)  # 给 JS 一点渲染时间
                html = page.content()
                browser.close()
        return (_html_to_markdown(html), None)
    except Exception as e:
        return ("", f"browser_error: {e}")


def fetch_page(url: str, force_browser: bool = False, force_http: bool = False,
               wait_selector: str | None = None) -> dict:
    """智能混合抓单页。

    force_http=True  → 只用本地 HTTP（最快最省）
    force_browser=True → 直接用云端浏览器
    默认 → 先 HTTP，被反爬/正文过短再升级云端
    """
    result = {"url": url, "markdown": "", "via": None, "truncated": False, "error": None}

    if force_browser:
        md, err = fetch_browser(url, wait_selector)
        result.update(via="browser", error=err)
        result["markdown"], result["truncated"] = _truncate(md)
        return result

    md, html, err = fetch_http(url)
    if not force_http and (err or _looks_blocked(html, md)):
        bmd, berr = fetch_browser(url, wait_selector)
        if bmd and not berr:
            result.update(via="browser", error=None)
            result["markdown"], result["truncated"] = _truncate(bmd)
            return result
        # 云端也失败，回退到 HTTP 拿到的（哪怕短），把两个错都带上
        result["error"] = f"http:[{err}] browser:[{berr}]" if (err or berr) else None

    result.update(via="http" if not result.get("via") else result["via"])
    result["markdown"], result["truncated"] = _truncate(md)
    if err and not result["markdown"]:
        result["error"] = err
    return result


def web_search(query: str, num_results: int = 8, engine: str = "duckduckgo",
               freshness: str | None = None) -> list[dict]:
    """搜索，返回 [{title, url, body}]，不抓正文。"""
    from ddgs import DDGS
    timelimit = None
    if freshness:
        timelimit = {"day": "d", "week": "w", "month": "m", "year": "y"}.get(freshness)
    backend = "google" if engine in ("google", "g") else "auto"
    out = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=num_results, timelimit=timelimit, backend=backend):
            out.append({
                "title": r.get("title", ""),
                "url": r.get("href", r.get("url", "")),
                "body": r.get("body", ""),
            })
    return out
