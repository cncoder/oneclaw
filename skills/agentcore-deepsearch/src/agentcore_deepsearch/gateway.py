"""真·Amazon Bedrock AgentCore Web Search Tool 客户端。

这是本 server 搜索能力的默认后端，替代了早期那套 ddgs/DuckDuckGo 包装。
数据源不再是第三方搜索引擎，而是 Amazon 自建、跨数百亿文档、分钟级刷新的 web index，
查询全程不出 AWS（详见 AWS 官方文档 Web Search Tool）。

接入方式（官方架构）：
- 能力以「托管连接器」形式挂在一个 AgentCore Gateway 上（connectorId="web-search"）。
- Gateway 用标准 MCP over HTTP 暴露：先 initialize 建立协议，再 tools/call 调 WebSearch。
- 本机这台 Gateway 的 inbound 授权是 AWS_IAM（SigV4），所以直接用本地 AWS 凭证签名即可，
  不需要 Cognito/JWT。outbound（Gateway→搜索后端）用 Gateway 自己的 IAM service role，
  与调用方无关。
- Web Search 连接器当前只在 us-east-1 提供，故这里的签名/请求 region 固定 us-east-1，
  与云端浏览器所在 region 解耦。

计费：按查询计费（AWS 官方定价 $7 / 1000 次），比维持云端浏览器解析 SERP 便宜且快得多。

输入：query（≤200 字符）+ maxResults（1~25，默认 10）。
输出：每条 web 观测含 title / url / publishedDate / text（语义抽取的相关片段）；
      实体类查询可能附带知识图谱观测（title/url 为 null，text 里是结构化事实）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.session import Session as BotocoreSession

from . import config

logger = logging.getLogger("agentcore_deepsearch.gateway")

# MCP 协议里给这个能力签名用的 AWS service 名
_SIGV4_SERVICE = "bedrock-agentcore"


class GatewayError(RuntimeError):
    """调用 AgentCore Web Search Gateway 失败。"""


@dataclass
class WebObservation:
    """一条搜索观测。web 索引结果与知识图谱结果统一用这个结构承载。"""

    title: str
    url: str
    snippet: str
    published_date: str
    kind: str  # "web" | "knowledge_graph"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "published_date": self.published_date,
            "kind": self.kind,
            "source": "agentcore",
        }


def _sign_and_post(payload: dict, session_id: str | None) -> tuple[dict, str | None]:
    """对单个 JSON-RPC 请求做 SigV4 签名并 POST 到 Gateway，返回 (解析后的 JSON, 新 session id)。

    Gateway 可能以 application/json 或 text/event-stream(SSE) 返回，两种都处理。
    """
    url = config.WEBSEARCH_GATEWAY_URL
    if not url:
        raise GatewayError(
            "AGENTCORE_WEBSEARCH_GATEWAY_URL 未配置，跳过 AgentCore 搜索"
        )
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    creds = BotocoreSession().get_credentials()
    if creds is None:
        raise GatewayError("找不到 AWS 凭证，无法对 Web Search Gateway 做 SigV4 签名")
    frozen = creds.get_frozen_credentials()

    aws_req = AWSRequest(method="POST", url=url, data=body, headers=headers)
    SigV4Auth(frozen, _SIGV4_SERVICE, config.WEBSEARCH_GATEWAY_REGION).add_auth(aws_req)

    req = urllib.request.Request(
        url, data=body, headers=dict(aws_req.headers), method="POST"
    )
    try:
        resp = urllib.request.urlopen(req, timeout=config.WEBSEARCH_TIMEOUT)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise GatewayError(f"Gateway HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GatewayError(f"Gateway 连接失败: {exc.reason}") from exc

    new_sid = resp.headers.get("Mcp-Session-Id")
    raw = resp.read().decode()
    if "text/event-stream" in resp.headers.get("Content-Type", ""):
        # SSE：取第一行 data: 载荷
        raw = next(
            (
                ln[len("data:") :].strip()
                for ln in raw.splitlines()
                if ln.startswith("data:")
            ),
            "",
        )
    if not raw:
        raise GatewayError("Gateway 返回空响应")
    doc = json.loads(raw)
    if "error" in doc:
        raise GatewayError(f"JSON-RPC error: {doc['error']}")
    return doc, new_sid


def _search_sync(query: str, max_results: int) -> list[WebObservation]:
    """同步执行一次完整的 MCP 调用（initialize → tools/call）。跑在 to_thread 里。"""
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "agentcore-deepsearch", "version": "1.0"},
        },
    }
    _, session_id = _sign_and_post(init, None)

    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": config.WEBSEARCH_TOOL_NAME,
            "arguments": {
                "query": query[:200],
                "maxResults": max(1, min(max_results, 25)),
            },
        },
    }
    doc, _ = _sign_and_post(call, session_id)

    result = doc.get("result", {})
    if result.get("isError"):
        raise GatewayError(f"WebSearch 返回 isError: {result.get('content')}")

    # 结果是「一个 text 内容块，里面是序列化 JSON」
    blocks = result.get("content", [])
    text = next((b.get("text", "") for b in blocks if b.get("type") == "text"), "")
    if not text:
        return []
    inner = json.loads(text)

    out: list[WebObservation] = []
    for obs in inner.get("results", []):
        title = obs.get("title")
        url = obs.get("url")
        is_kg = title is None and url is None
        out.append(
            WebObservation(
                title=(title or "").strip(),
                url=(url or "").strip(),
                snippet=(obs.get("text") or "").strip(),
                published_date=(obs.get("publishedDate") or "").strip(),
                kind="knowledge_graph" if is_kg else "web",
            )
        )
    return out


async def web_search(query: str, max_results: int = 10) -> list[WebObservation]:
    """异步入口：调用真 AgentCore Web Search Tool，返回观测列表。

    失败时抛 GatewayError，由调用方决定是否回退到其它引擎。
    """
    return await asyncio.to_thread(_search_sync, query, max_results)
