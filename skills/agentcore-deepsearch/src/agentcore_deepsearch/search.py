"""网页搜索：返回结果列表（标题/URL/摘要/发布日期），不抓正文。

三条引擎，默认走真 AgentCore：
- agentcore（默认，推荐）：Amazon Bedrock AgentCore Web Search Tool。数据来自 Amazon
  自建、跨数百亿文档、分钟级刷新的 web index，查询不出 AWS，附带知识图谱实体事实与语义
  抽取的相关片段。走 Gateway + MCP + SigV4，详见 gateway.py。
- google（可选）：用 AgentCore 云端浏览器打开 Google 结果页解析渲染后的 HTML。
  真正需要 Google 排序时才用，慢、占 session、有云端浏览器费用。
- duckduckgo（兜底）：ddgs 库，免 key、零配置。仅在 AgentCore 不可用或显式指定时使用。
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from dataclasses import dataclass

from . import gateway
from .browser import get_cloud_browser

logger = logging.getLogger("agentcore_deepsearch.search")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str  # "agentcore" | "google" | "duckduckgo"
    published_date: str = ""
    kind: str = "web"  # "web" | "knowledge_graph"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


async def _agentcore_search(query: str, num_results: int) -> list[SearchResult]:
    """默认引擎：调真 AgentCore Web Search Tool。"""
    observations = await gateway.web_search(query, max_results=num_results)
    out: list[SearchResult] = []
    for o in observations:
        out.append(
            SearchResult(
                title=o.title,
                url=o.url,
                snippet=o.snippet,
                source="agentcore",
                published_date=o.published_date,
                kind=o.kind,
            )
        )
    return out[:num_results]


async def _ddg_search(
    query: str, num_results: int, freshness: str | None
) -> list[SearchResult]:
    """兜底引擎：DuckDuckGo（ddgs 库）。"""
    from ddgs import DDGS  # 延迟导入：只有真正用到兜底时才加载

    timelimit = {"day": "d", "week": "w", "month": "m", "year": "y"}.get(
        (freshness or "").lower()
    )

    def _run() -> list[dict]:
        with DDGS() as ddgs:
            kwargs = {"query": query, "max_results": num_results}
            if timelimit:
                kwargs["timelimit"] = timelimit
            return list(ddgs.text(**kwargs))

    rows = await asyncio.to_thread(_run)
    out: list[SearchResult] = []
    for r in rows:
        url = r.get("href") or r.get("url") or ""
        if not url:
            continue
        out.append(
            SearchResult(
                title=r.get("title", "").strip(),
                url=url,
                snippet=r.get("body", "").strip(),
                source="duckduckgo",
            )
        )
    return out[:num_results]


# Google 结果页里真实落地页链接形如 /url?q=<real>&sa=...，需还原
_TITLE_NEAR = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)


def _clean_google_url(href: str) -> str | None:
    if href.startswith("/url?"):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        real = qs.get("q", [""])[0]
        href = real
    if not href.startswith("http"):
        return None
    # 过滤 Google 自家域
    host = urllib.parse.urlparse(href).netloc
    if any(b in host for b in ("google.", "gstatic.", "googleusercontent.")):
        return None
    return href


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


async def _google_search(query: str, num_results: int) -> list[SearchResult]:
    q = urllib.parse.quote_plus(query)
    serp_url = (
        f"https://www.google.com/search?q={q}&num={min(num_results + 5, 20)}&hl=en"
    )
    html, err = await get_cloud_browser().get_rendered_html(serp_url)
    if err or not html:
        logger.warning("google search failed: %s", err)
        return []

    # 用 h3 标题块定位结果，向后就近找链接，做简单去重
    results: list[SearchResult] = []
    seen: set[str] = set()
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href_raw, inner = m.group(1), m.group(2)
        if "<h3" not in inner:
            continue
        url = _clean_google_url(href_raw)
        if not url or url in seen:
            continue
        title_m = _TITLE_NEAR.search(inner)
        title = _strip_tags(title_m.group(1)) if title_m else url
        seen.add(url)
        results.append(SearchResult(title=title, url=url, snippet="", source="google"))
        if len(results) >= num_results:
            break
    return results


async def web_search(
    query: str,
    num_results: int = 6,
    engine: str = "agentcore",
    freshness: str | None = None,
) -> list[SearchResult]:
    """搜索网页。engine ∈ {"agentcore"(默认), "google", "duckduckgo"}。

    agentcore 调用失败时自动兜底到 duckduckgo，保证搜索始终可用（会记 warning）。
    """
    engine = (engine or "agentcore").lower()

    if engine == "google":
        res = await _google_search(query, num_results)
        if res:
            return res
        logger.info("google empty, falling back to duckduckgo")
        return await _ddg_search(query, num_results, freshness)

    if engine == "duckduckgo":
        return await _ddg_search(query, num_results, freshness)

    # 默认：agentcore；失败兜底 duckduckgo
    try:
        res = await _agentcore_search(query, num_results)
        if res:
            return res
        logger.info("agentcore empty, falling back to duckduckgo")
    except gateway.GatewayError as exc:
        logger.warning(
            "agentcore web search failed (%s), falling back to duckduckgo", exc
        )
    return await _ddg_search(query, num_results, freshness)
