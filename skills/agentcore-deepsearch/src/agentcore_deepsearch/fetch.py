"""页面抓取编排：智能混合策略。

默认先用本地 HTTP（快、免费、不占云端 session）抓；当 HTTP 失败、被拦、或抓到的
正文过短（疑似 JS 动态页）时，自动升级到 AgentCore 云端浏览器重抓。

策略可逐次覆盖：force_browser=True 直接走云端，force_http=True 只用 HTTP。
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from . import config
from .browser import get_cloud_browser
from .extract import PageContent, extract_markdown

logger = logging.getLogger("agentcore_deepsearch.fetch")

# HTTP 抓到这些信号，判定为需要真实浏览器
_BROWSER_HINTS = (
    "enable javascript",
    "captcha",
    "cf-browser-verification",
    "just a moment",
    "checking your browser",
)


async def _http_fetch(url: str) -> PageContent:
    headers = {"User-Agent": config.HTTP_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=config.HTTP_TIMEOUT, headers=headers
        ) as cli:
            resp = await cli.get(url)
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            if "html" not in ctype and "xml" not in ctype and "text" not in ctype:
                return PageContent(url=url, fetched_via="http", error=f"unsupported_content_type: {ctype}")
            return extract_markdown(resp.text, url, fetched_via="http")
    except Exception as exc:
        return PageContent(url=url, fetched_via="http", error=f"http_error: {exc}")


def _http_result_is_weak(pc: PageContent) -> bool:
    """判断 HTTP 抓取结果是否“不够好”，需要升级到浏览器。"""
    if pc.error:
        return True
    if pc.char_count < config.HTTP_MIN_GOOD_CHARS:
        return True
    low = pc.markdown.lower()
    return any(h in low for h in _BROWSER_HINTS)


async def fetch_page(
    url: str,
    force_browser: bool = False,
    force_http: bool = False,
    wait_selector: str | None = None,
) -> PageContent:
    """抓取单个 URL，返回正文 markdown。

    - 默认：HTTP 优先，结果弱则自动升级云端浏览器。
    - force_browser：直接走云端浏览器（动态页/反爬站）。
    - force_http：只用 HTTP，不升级（最快最省，明知是静态页时用）。
    """
    if force_browser and not force_http:
        return await get_cloud_browser().fetch(url, wait_selector=wait_selector)

    http_pc = await _http_fetch(url)
    if force_http or not _http_result_is_weak(http_pc):
        return http_pc

    # HTTP 结果弱 → 升级云端浏览器；若云端也失败，回退给出 HTTP 的错误信息
    logger.info("HTTP weak for %s (err=%s, chars=%s), upgrading to cloud browser",
                url, http_pc.error, http_pc.char_count)
    browser_pc = await get_cloud_browser().fetch(url, wait_selector=wait_selector)
    if browser_pc.error and not browser_pc.markdown:
        # 两条路都失败，返回信息更全的那个
        return http_pc if http_pc.char_count >= browser_pc.char_count else browser_pc
    return browser_pc


async def fetch_batch(
    urls: list[str],
    force_browser: bool = False,
    force_http: bool = False,
) -> list[PageContent]:
    """并发抓取多个 URL，限制并发数。失败的 URL 也会返回（带 error）。"""
    sem = asyncio.Semaphore(config.FETCH_CONCURRENCY)

    async def _one(u: str) -> PageContent:
        async with sem:
            return await fetch_page(u, force_browser=force_browser, force_http=force_http)

    return await asyncio.gather(*(_one(u) for u in urls))
