"""集中管理可调参数。全部可用环境变量覆盖，方便不改代码就调行为。"""

from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- AWS / AgentCore 云端浏览器 ---
# 云端浏览器所在 region 与 AWS 托管的默认 browser id（实测 READY、开箱即用）
AWS_REGION: str = os.environ.get(
    "AGENTCORE_REGION", os.environ.get("AWS_REGION", "us-west-2")
)
BROWSER_IDENTIFIER: str = os.environ.get("AGENTCORE_BROWSER_ID", "aws.browser.v1")

# --- AgentCore Web Search Tool（默认搜索后端）---
# 挂着 web-search 连接器的 AgentCore Gateway 的 MCP 端点。Web Search 连接器目前只在
# us-east-1 提供，故 region 独立于云端浏览器的 AWS_REGION。inbound 授权为 AWS_IAM(SigV4)，
# 用本地 AWS 凭证直接签名调用。
# 你自己账号的 Gateway MCP 端点（infra/provision.py 一键创建后设环境变量指向它）。
# 不设置时搜索自动回退 DuckDuckGo（云端浏览器抓取功能不受影响）。
WEBSEARCH_GATEWAY_URL: str = os.environ.get("AGENTCORE_WEBSEARCH_GATEWAY_URL", "")
WEBSEARCH_GATEWAY_REGION: str = os.environ.get(
    "AGENTCORE_WEBSEARCH_REGION", "us-east-1"
)
# Gateway 把 target 名拼进工具名后暴露；换 Gateway/target 时可用环境变量覆盖。
WEBSEARCH_TOOL_NAME: str = os.environ.get(
    "AGENTCORE_WEBSEARCH_TOOL_NAME", "web-search-tool___WebSearch"
)
# 单次搜索请求超时（秒）
WEBSEARCH_TIMEOUT: int = _int("AGENTCORE_WEBSEARCH_TIMEOUT", 60)
# 单个云端 session 的存活上限（秒）。范围 1~28800（8 小时）。
SESSION_TIMEOUT_SECONDS: int = _int("AGENTCORE_SESSION_TIMEOUT", 600)
# 视口尺寸，影响部分站点的渲染分支
VIEWPORT_WIDTH: int = _int("AGENTCORE_VIEWPORT_W", 1920)
VIEWPORT_HEIGHT: int = _int("AGENTCORE_VIEWPORT_H", 1080)

# --- 抓取策略 ---
# 单次抓取返回的正文最大字符数，防止把超长页面塞爆 LLM 上下文
MAX_CONTENT_CHARS: int = _int("DEEPSEARCH_MAX_CHARS", 50_000)
# 本地 HTTP 抓取超时（秒）
HTTP_TIMEOUT: int = _int("DEEPSEARCH_HTTP_TIMEOUT", 20)
# 云端浏览器导航超时（毫秒）
BROWSER_NAV_TIMEOUT_MS: int = _int("DEEPSEARCH_BROWSER_NAV_TIMEOUT", 35_000)
# 云端浏览器抓取后额外等待动态内容（毫秒）
BROWSER_SETTLE_MS: int = _int("DEEPSEARCH_BROWSER_SETTLE", 1500)
# 本地 HTTP 抓到的正文短于这个长度，判定为“可能是动态页/被拦”，触发升级到云端浏览器
HTTP_MIN_GOOD_CHARS: int = _int("DEEPSEARCH_HTTP_MIN_GOOD", 600)
# 批量抓取的并发数
FETCH_CONCURRENCY: int = _int("DEEPSEARCH_FETCH_CONCURRENCY", 4)

# 伪装成普通浏览器，降低被静态站点拦截的概率
HTTP_USER_AGENT: str = os.environ.get(
    "DEEPSEARCH_UA",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)
