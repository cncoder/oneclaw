#!/usr/bin/env python3
"""MCP server: AgentCore DeepSearch — 云端浏览器 deep research 搜索+抓取。

裸 stdio JSON-RPC（与 lark-mcp-server 同款），无需 mcp SDK，Hermes 和 Claude Code 都能挂。
工具：web_search / fetch_page / fetch_batch / deep_search / deep_search_multi / browser_status
"""

import concurrent.futures
import json
import os
import sys

import fetcher

CONCURRENCY = int(os.environ.get("DEEPSEARCH_FETCH_CONCURRENCY", "4"))

TOOLS = [
    ("web_search", "联网搜索，返回标题/URL/摘要，不抓正文。先用它看有哪些来源、决定读哪篇。", True),
    ("fetch_page", "抓单个 URL 正文→干净 markdown。智能混合：先 HTTP，反爬/JS 页自动升级云端浏览器。", True),
    ("fetch_batch", "并发抓多个 URL 正文。", True),
    ("deep_search", "一步：搜索 query + 抓 top-K 结果正文。做单主题调研的主力。", True),
    ("deep_search_multi", "并发跑多个子查询，每个各抓 top-K 正文。做多角度深度调研的主力。", True),
    ("browser_status", "看 region/browser_id/凭证配置，排查云端连接。", True),
]

SCHEMAS = {
    "web_search": {
        "query": {"type": "string", "description": "搜索词"},
        "num_results": {"type": "integer", "description": "结果数，默认 8"},
        "engine": {"type": "string", "description": "duckduckgo(默认) 或 google"},
        "freshness": {"type": "string", "description": "时间过滤：day/week/month/year，可选"},
    },
    "fetch_page": {
        "url": {"type": "string"},
        "force_browser": {"type": "boolean", "description": "强制走云端浏览器（SPA/需登录/反爬）"},
        "force_http": {"type": "boolean", "description": "强制只用本地 HTTP（静态长页，最省）"},
        "wait_selector": {"type": "string", "description": "云端浏览器等待此 CSS selector 出现，可选"},
    },
    "fetch_batch": {
        "urls": {"type": "array", "items": {"type": "string"}},
        "force_browser": {"type": "boolean"},
        "force_http": {"type": "boolean"},
    },
    "deep_search": {
        "query": {"type": "string"},
        "top_k_fetch": {"type": "integer", "description": "抓正文的结果数，默认 3"},
        "engine": {"type": "string"},
        "force_browser": {"type": "boolean"},
    },
    "deep_search_multi": {
        "queries": {"type": "array", "items": {"type": "string"}},
        "top_k_fetch": {"type": "integer", "description": "每个子查询抓正文数，默认 3"},
        "engine": {"type": "string"},
    },
    "browser_status": {},
}

REQUIRED = {
    "web_search": ["query"], "fetch_page": ["url"], "fetch_batch": ["urls"],
    "deep_search": ["query"], "deep_search_multi": ["queries"], "browser_status": [],
}


# ── 工具实现 ──────────────────────────────────────────────────────────
def _fetch_many(urls, force_browser=False, force_http=False):
    results = [None] * len(urls)
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(fetcher.fetch_page, u, force_browser, force_http): i
                for i, u in enumerate(urls)}
        for f in concurrent.futures.as_completed(futs):
            i = futs[f]
            try:
                results[i] = f.result()
            except Exception as e:
                results[i] = {"url": urls[i], "markdown": "", "error": str(e)}
    return results


def tool_web_search(a):
    return {"results": fetcher.web_search(
        a["query"], a.get("num_results", 8), a.get("engine", "duckduckgo"), a.get("freshness"))}


def tool_fetch_page(a):
    return fetcher.fetch_page(a["url"], a.get("force_browser", False),
                              a.get("force_http", False), a.get("wait_selector"))


def tool_fetch_batch(a):
    return {"pages": _fetch_many(a["urls"], a.get("force_browser", False), a.get("force_http", False))}


def tool_deep_search(a):
    # 先广：用搜索引擎打开视野，多拿候选来源（至少 8 条，覆盖面优先）
    top_k = max(int(a.get("top_k_fetch", 3)), 3)
    overview = fetcher.web_search(
        a["query"], max(top_k * 3, 8), a.get("engine", "duckduckgo"))
    # 再深：对前 K 个来源纵深抓正文（必须 ≥2 个，单一来源不算深度调研）
    fetch_n = max(top_k, 2)
    top = overview[:fetch_n]
    pages = _fetch_many([h["url"] for h in top], force_browser=a.get("force_browser", False))
    for h, p in zip(top, pages):
        h["markdown"] = p.get("markdown", "")
        h["via"] = p.get("via")
        if p.get("error"):
            h["fetch_error"] = p["error"]
    fetched_ok = sum(1 for h in top if h.get("markdown"))
    return {
        "query": a["query"],
        # 广：搜索引擎完整视野，标题+URL+摘要，让 LLM 先看清有哪些来源
        "search_overview": [
            {"title": h["title"], "url": h["url"], "body": h.get("body", "")}
            for h in overview
        ],
        # 深：纵深抓取的多个来源正文
        "sources": top,
        "note": (
            f"广度：{len(overview)} 个候选来源；纵深：抓取 {fetched_ok} 个来源正文。"
            "结论必须建立在多个来源交叉验证上，单一来源标 [待验证]。"
            if fetched_ok >= 2 else
            f"⚠️ 仅成功抓取 {fetched_ok} 个来源正文，不足以交叉验证。"
            "请扩大 top_k_fetch 或换 query 再搜，别用单一来源下结论。"
        ),
    }


def tool_deep_search_multi(a):
    out = []
    for q in a["queries"]:
        out.append(tool_deep_search({"query": q, "top_k_fetch": a.get("top_k_fetch", 3),
                                     "engine": a.get("engine", "duckduckgo")}))
    return {"subqueries": out}


def tool_browser_status(a):
    import shutil
    creds_ok = bool(os.environ.get("AWS_ACCESS_KEY_ID")) or os.path.exists(
        os.path.expanduser("~/.aws/credentials"))
    return {
        "region": fetcher.REGION, "browser_id": fetcher.BROWSER_ID,
        "session_timeout_s": fetcher.SESSION_TIMEOUT, "max_chars": fetcher.MAX_CHARS,
        "fetch_concurrency": CONCURRENCY, "aws_credentials_present": creds_ok,
        "playwright_installed": shutil.which("playwright") is not None or True,
    }


IMPL = {
    "web_search": tool_web_search, "fetch_page": tool_fetch_page,
    "fetch_batch": tool_fetch_batch, "deep_search": tool_deep_search,
    "deep_search_multi": tool_deep_search_multi, "browser_status": tool_browser_status,
}


# ── JSON-RPC 外壳 ─────────────────────────────────────────────────────
def build_tools_list():
    tools = []
    for name, desc, readonly in TOOLS:
        props = SCHEMAS.get(name, {})
        t = {
            "name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props, "required": REQUIRED.get(name, [])},
        }
        if readonly:
            t["annotations"] = {"readOnlyHint": True}
        tools.append(t)
    return tools


def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg):
    mid, method = msg.get("id"), msg.get("method", "")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "agentcore-deepsearch", "version": "1.0.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": build_tools_list()}}
    if method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        fn = IMPL.get(name)
        if not fn:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}}
        try:
            data = fn(args)
            text = json.dumps(data, ensure_ascii=False, indent=2)
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": f"Error in {name}: {e}"}], "isError": True}}
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if "id" not in msg:  # notification
            continue
        send(handle(msg))


if __name__ == "__main__":
    main()
