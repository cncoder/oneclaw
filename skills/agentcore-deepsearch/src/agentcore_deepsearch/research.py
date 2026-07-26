"""DeepSearch 编排：把"搜索 + 批量抓取"打包成一步，喂给 LLM 做提炼。

这里不替 LLM 做归纳总结（那是调用方/主 agent 的活），只负责高效地把"一个问题
对应的多个来源的正文"取回来，结构化返回。LLM 拿到后自己提炼 learnings、决定要不要
再追一轮（breadth/depth 递归在 LLM 侧编排）。
"""

from __future__ import annotations

import asyncio
import logging

from .fetch import fetch_batch
from .search import web_search

logger = logging.getLogger("agentcore_deepsearch.research")


async def gather_sources(
    query: str,
    num_results: int = 6,
    top_k_fetch: int = 4,
    engine: str = "agentcore",
    force_browser: bool = False,
    freshness: str | None = None,
) -> dict:
    """对一个 query：搜索 → 抓取前 top_k 个结果的正文 → 结构化返回。

    返回结构：
      {
        "query": ...,
        "engine": ...,
        "results": [ {title,url,snippet,source}, ... ],   # 全部搜索结果
        "sources": [ PageContent.to_dict(), ... ],        # 抓到正文的前 top_k 个
      }
    """
    results = await web_search(
        query, num_results=num_results, engine=engine, freshness=freshness
    )
    if not results:
        return {
            "query": query,
            "engine": engine,
            "results": [],
            "sources": [],
            "note": "no search results",
        }

    urls = [r.url for r in results[:top_k_fetch]]
    pages = await fetch_batch(urls, force_browser=force_browser)

    sources = []
    for r, pc in zip(results[:top_k_fetch], pages):
        d = pc.to_dict()
        d.setdefault("title", r.title)
        if not d.get("title"):
            d["title"] = r.title
        d["search_snippet"] = r.snippet
        sources.append(d)

    return {
        "query": query,
        "engine": engine,
        "results": [r.to_dict() for r in results],
        "sources": sources,
    }


async def gather_multi(
    queries: list[str],
    num_results: int = 6,
    top_k_fetch: int = 3,
    engine: str = "agentcore",
    force_browser: bool = False,
) -> list[dict]:
    """并发跑多个 query（deep research 一层 breadth 的展开）。"""
    return await asyncio.gather(
        *(
            gather_sources(
                q,
                num_results=num_results,
                top_k_fetch=top_k_fetch,
                engine=engine,
                force_browser=force_browser,
            )
            for q in queries
        )
    )
