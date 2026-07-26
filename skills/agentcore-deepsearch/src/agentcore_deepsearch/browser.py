"""Amazon Bedrock AgentCore Browser Tool 会话管理。

AgentCore Browser 是一个安全隔离的托管浏览器：运行在容器化环境里，与本机隔离，
按会话计费，会话有 TTL（默认 15 分钟，最长 8 小时）到期自动终止。这里通过 Automation
端点（WebSocket 流式）用 Playwright 驱动它导航、渲染、取正文，用于抓 SPA / 需 JS 渲染 /
反爬严格的页面（普通静态页由 fetch.py 走本地 HTTP，更快更省）。

设计要点：
- session 复用。启动一个云端 session 要 5~10s 且按会话计费，所以全局只维持一个
  共享 session + 一个已连上的 Playwright browser，多次抓取复用它。
- 空闲自动回收。超过 IDLE 阈值没人用就 stop，避免空跑烧钱。
- 线程/协程安全。用一把 asyncio.Lock 串行化 start/stop，避免并发抓取时重复建 session。

云端 browser 用 AWS 托管的默认实例 aws.browser.v1（实测 READY、无需自建）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from bedrock_agentcore.tools.browser_client import BrowserClient
from playwright.async_api import Browser, async_playwright

from . import config
from .extract import PageContent, extract_markdown

logger = logging.getLogger("agentcore_deepsearch.browser")

# 空闲多久（秒）自动回收 session。比 SESSION_TIMEOUT 略短，让我们主动 stop 而不是等服务端超时。
_IDLE_RECYCLE_SECONDS = max(60, config.SESSION_TIMEOUT_SECONDS - 60)


class CloudBrowser:
    """单例式的云端浏览器，封装 session 生命周期 + 抓取。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._client: Optional[BrowserClient] = None
        self._pw_ctx = None  # async_playwright() 上下文
        self._browser: Optional[Browser] = None
        self._session_id: Optional[str] = None
        self._last_used: float = 0.0

    async def _ensure_session(self) -> Browser:
        """确保有一个可用的已连接 browser；过期或没有则新建。调用方需持有 _lock。"""
        now = time.monotonic()
        # 已有连接且未空闲过久 → 直接复用
        if self._browser is not None and self._browser.is_connected():
            if now - self._last_used < _IDLE_RECYCLE_SECONDS:
                self._last_used = now
                return self._browser
            # 空闲过久，回收重建
            logger.info("cloud browser idle too long, recycling session")
            await self._teardown_locked()

        # 新建：start session → 取 SigV4 CDP headers → Playwright 连上
        client = BrowserClient(config.AWS_REGION)
        session_id = client.start(
            identifier=config.BROWSER_IDENTIFIER,
            session_timeout_seconds=config.SESSION_TIMEOUT_SECONDS,
            viewport={"width": config.VIEWPORT_WIDTH, "height": config.VIEWPORT_HEIGHT},
        )
        ws_url, headers = client.generate_ws_headers()
        pw_ctx = async_playwright()
        pw = await pw_ctx.__aenter__()
        browser = await pw.chromium.connect_over_cdp(ws_url, headers=headers)

        self._client = client
        self._pw_ctx = pw_ctx
        self._browser = browser
        self._session_id = session_id
        self._last_used = now
        logger.info("cloud browser session started: %s", session_id)
        return browser

    async def _teardown_locked(self) -> None:
        """关闭 Playwright 连接并 stop 云端 session。调用方需持有 _lock。"""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw_ctx is not None:
            try:
                await self._pw_ctx.__aexit__(None, None, None)
            except Exception:
                pass
        if self._client is not None:
            try:
                self._client.stop()
                logger.info("cloud browser session stopped: %s", self._session_id)
            except Exception:
                pass
        self._browser = None
        self._pw_ctx = None
        self._client = None
        self._session_id = None

    async def fetch(
        self,
        url: str,
        wait_selector: Optional[str] = None,
        settle_ms: Optional[int] = None,
    ) -> PageContent:
        """用云端浏览器抓取一个 URL，返回提炼后的 markdown 正文。"""
        async with self._lock:
            browser = await self._ensure_session()
            ctx = (
                browser.contexts[0] if browser.contexts else await browser.new_context()
            )
            page = await ctx.new_page()
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=config.BROWSER_NAV_TIMEOUT_MS,
                )
                if wait_selector:
                    try:
                        await page.wait_for_selector(wait_selector, timeout=8000)
                    except Exception:
                        pass
                else:
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                await page.wait_for_timeout(
                    settle_ms if settle_ms is not None else config.BROWSER_SETTLE_MS
                )
                html = await page.content()
                self._last_used = time.monotonic()
                return extract_markdown(html, url, fetched_via="browser")
            except Exception as exc:
                return PageContent(
                    url=url, fetched_via="browser", error=f"browser_error: {exc}"
                )
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

    async def get_rendered_html(
        self, url: str, settle_ms: Optional[int] = None
    ) -> tuple[str, Optional[str]]:
        """抓取并返回 (html, error)。给搜索模块解析 SERP 用，不做正文提炼。"""
        async with self._lock:
            browser = await self._ensure_session()
            ctx = (
                browser.contexts[0] if browser.contexts else await browser.new_context()
            )
            page = await ctx.new_page()
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=config.BROWSER_NAV_TIMEOUT_MS,
                )
                await page.wait_for_timeout(
                    settle_ms if settle_ms is not None else config.BROWSER_SETTLE_MS
                )
                html = await page.content()
                self._last_used = time.monotonic()
                return html, None
            except Exception as exc:
                return "", f"browser_error: {exc}"
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

    async def shutdown(self) -> None:
        """进程退出时主动收尾，确保云端 session 被 stop。"""
        async with self._lock:
            await self._teardown_locked()


# 进程级单例
_cloud_browser: Optional[CloudBrowser] = None


def get_cloud_browser() -> CloudBrowser:
    global _cloud_browser
    if _cloud_browser is None:
        _cloud_browser = CloudBrowser()
    return _cloud_browser
