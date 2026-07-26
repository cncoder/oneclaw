"""DeepSearch MCP server —— 基于 AWS Bedrock AgentCore 云端浏览器的搜索 + 抓取工具集。

工具一览：
- web_search   : 搜索网页，返回标题/URL/摘要（不抓正文）
- fetch_page   : 抓单个 URL 正文（智能混合：HTTP 优先，动态页自动升级云端浏览器）
- fetch_batch  : 并发抓多个 URL 正文
- deep_search  : 一个 query 走完“搜索→抓取 top-K 正文”，给 LLM 做提炼
- deep_search_multi : 并发跑多个 query（deep research 的一层 breadth 展开）

传输：stdio（本地 MCP 默认）。云端浏览器 session 全局复用、空闲自动回收，进程退出时收尾。
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from . import config
from .browser import get_cloud_browser
from .fetch import fetch_batch as _fetch_batch
from .fetch import fetch_page as _fetch_page
from .research import gather_multi, gather_sources
from .search import web_search as _web_search

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger("agentcore_deepsearch.server")

mcp = FastMCP(
    "agentcore-deepsearch",
    instructions=(
        "基于 Amazon Bedrock AgentCore 的网页搜索与抓取工具，专为 deep research 设计。"
        "web_search 默认走 AgentCore Web Search Tool：数据来自 Amazon 自建、跨数百亿文档、"
        "分钟级刷新的 web index，查询不出 AWS，附带知识图谱事实与语义抽取片段。抓取正文走智能混合"
        "策略：本地 HTTP 优先（快、免费），遇到动态页/反爬时自动升级到 AgentCore 云端隔离浏览器。"
        "deep research 编排建议：先 web_search 看有哪些来源，再 fetch_batch/deep_search 取正文，"
        "LLM 提炼 learnings 后用 follow-up 问题递归。需要 Google 排序时 search 用 engine='google'，"
        "抓需 JS 渲染的页面时 fetch 用 force_browser=true。"
    ),
)


@mcp.tool()
async def web_search(
    query: str,
    num_results: int = 6,
    engine: str = "agentcore",
    freshness: str | None = None,
) -> dict:
    """搜索网页，返回结果列表（标题/URL/摘要/发布日期），不抓取正文。

    适合：先摸清一个话题有哪些来源、筛选值得深读的 URL。
    engine:
      - "agentcore"（默认，推荐）：Amazon Bedrock AgentCore Web Search Tool，Amazon 自建索引、
        分钟级刷新、查询不出 AWS，结果含 published_date，实体类查询附带知识图谱事实。
      - "google"：AgentCore 云端浏览器解析 Google 结果页，需要 Google 排序时用，慢且有费用。
      - "duckduckgo"：ddgs 兜底，免 key。agentcore 不可用时也会自动回退到它。
    freshness: 可选 "day"/"week"/"month"/"year"，仅对 duckduckgo 引擎生效。
    """
    results = await _web_search(
        query, num_results=num_results, engine=engine, freshness=freshness
    )
    # 实际生效的 source 从结果取：agentcore 失败会自动回退，engine 参数可能与真实来源不同
    effective = results[0].source if results else engine
    return {
        "query": query,
        "engine_requested": engine,
        "engine_used": effective,
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }


@mcp.tool()
async def fetch_page(
    url: str,
    force_browser: bool = False,
    force_http: bool = False,
    wait_selector: str | None = None,
) -> dict:
    """抓取单个 URL 的正文，返回干净的 markdown + 元数据。

    默认智能混合：本地 HTTP 优先，结果为空/过短/被反爬拦截时自动升级到云端浏览器。
    force_browser=True：直接用云端浏览器（SPA、需 JS 渲染、反爬严格的站点）。
    force_http=True：只用 HTTP 不升级（明知是静态页，要最快最省时）。
    wait_selector：云端浏览器抓取时等待某个 CSS 选择器出现再取内容。
    """
    pc = await _fetch_page(
        url,
        force_browser=force_browser,
        force_http=force_http,
        wait_selector=wait_selector,
    )
    return pc.to_dict()


@mcp.tool()
async def fetch_batch(
    urls: list[str],
    force_browser: bool = False,
    force_http: bool = False,
) -> dict:
    """并发抓取多个 URL 的正文。失败的 URL 也会返回（带 error 字段）。

    适合：web_search 之后，批量获取 top-N 来源的正文。
    """
    pages = await _fetch_batch(urls, force_browser=force_browser, force_http=force_http)
    return {"count": len(pages), "sources": [p.to_dict() for p in pages]}


@mcp.tool()
async def deep_search(
    query: str,
    num_results: int = 6,
    top_k_fetch: int = 4,
    engine: str = "agentcore",
    force_browser: bool = False,
    freshness: str | None = None,
) -> dict:
    """一步到位：对一个 query 先搜索，再抓取前 top_k_fetch 个结果的正文。

    返回 {query, results（全部搜索结果）, sources（抓到正文的前 K 个）}。
    适合：deep research 单层探索。LLM 拿到 sources 后自己提炼 learnings、生成 follow-up
    问题，再对 follow-up 调用本工具递归深入。
    """
    return await gather_sources(
        query,
        num_results=num_results,
        top_k_fetch=top_k_fetch,
        engine=engine,
        force_browser=force_browser,
        freshness=freshness,
    )


@mcp.tool()
async def deep_search_multi(
    queries: list[str],
    num_results: int = 6,
    top_k_fetch: int = 3,
    engine: str = "agentcore",
    force_browser: bool = False,
) -> dict:
    """并发跑多个 query（deep research 一层 breadth 展开）。

    适合：LLM 把一个大问题拆成多个子查询后，一次性把多组来源都取回来。
    """
    bundles = await gather_multi(
        queries,
        num_results=num_results,
        top_k_fetch=top_k_fetch,
        engine=engine,
        force_browser=force_browser,
    )
    return {"query_count": len(bundles), "bundles": bundles}


@mcp.tool()
async def browser_status() -> dict:
    """查看当前配置：Web Search Gateway、云端浏览器 region / browser id。用于排查连接问题。"""
    return {
        "web_search_engine_default": "agentcore",
        "web_search_gateway_url": config.WEBSEARCH_GATEWAY_URL,
        "web_search_gateway_region": config.WEBSEARCH_GATEWAY_REGION,
        "web_search_tool_name": config.WEBSEARCH_TOOL_NAME,
        "browser_region": config.AWS_REGION,
        "browser_identifier": config.BROWSER_IDENTIFIER,
        "session_timeout_seconds": config.SESSION_TIMEOUT_SECONDS,
        "max_content_chars": config.MAX_CONTENT_CHARS,
        "fetch_concurrency": config.FETCH_CONCURRENCY,
    }


def main() -> None:
    try:
        mcp.run(transport="stdio")
    finally:
        # 进程退出时确保云端 session 被 stop（避免空跑计费）
        import asyncio

        try:
            asyncio.run(get_cloud_browser().shutdown())
        except Exception:
            pass


if __name__ == "__main__":
    main()
