"""把原始 HTML 提炼成干净的 markdown 正文 + 元数据。

用 trafilatura：2023 正文提取 benchmark 第一，自带 markdown 输出和元数据抽取，
比 readability/html2text 噪音少。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import trafilatura
from trafilatura.settings import use_config

from . import config

# 关掉 trafilatura 的信号超时（它默认用 SIGALRM，在子线程里会崩），并禁用磁盘缓存
_TRAFILATURA_CFG = use_config()
_TRAFILATURA_CFG.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")


@dataclass
class PageContent:
    """一次抓取的结构化结果。失败时 error 非空，markdown 为空。"""

    url: str
    title: str = ""
    markdown: str = ""
    author: str = ""
    date: str = ""
    sitename: str = ""
    fetched_via: str = ""  # "http" | "browser"
    char_count: int = 0
    truncated: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def extract_markdown(html: str, url: str, fetched_via: str) -> PageContent:
    """从 HTML 提炼正文 markdown。提取不到正文时返回带 error 的 PageContent。"""
    if not html or not html.strip():
        return PageContent(url=url, fetched_via=fetched_via, error="empty_html")

    body = trafilatura.extract(
        html,
        url=url,
        include_links=True,
        include_tables=True,
        favor_precision=True,
        output_format="markdown",
        config=_TRAFILATURA_CFG,
    )

    meta_title = meta_author = meta_date = meta_site = ""
    try:
        meta = trafilatura.extract_metadata(html)
        if meta:
            meta_title = meta.title or ""
            meta_author = meta.author or ""
            meta_date = meta.date or ""
            meta_site = meta.sitename or ""
    except Exception:  # 元数据抽取失败不影响正文
        pass

    if not body:
        return PageContent(
            url=url,
            title=meta_title,
            sitename=meta_site,
            fetched_via=fetched_via,
            error="no_main_content",
        )

    truncated = False
    if len(body) > config.MAX_CONTENT_CHARS:
        body = body[: config.MAX_CONTENT_CHARS]
        truncated = True

    return PageContent(
        url=url,
        title=meta_title,
        markdown=body,
        author=meta_author,
        date=meta_date,
        sitename=meta_site,
        fetched_via=fetched_via,
        char_count=len(body),
        truncated=truncated,
    )
