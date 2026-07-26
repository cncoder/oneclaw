# AgentCore DeepSearch MCP

基于 AWS Bedrock AgentCore 云端浏览器的网页搜索 + 抓取 MCP server，专为 deep research 设计。

## 它解决什么

联网深度调研时，需要"搜索 → 抓正文 → 提炼 → 递归追问"。普通 web fetch 抓不了 JS 动态页、
过不了反爬。这个 server 用 AWS 全托管、隔离 Firecracker microVM 里的云端 Chromium 来抓，
能跑 JS、过反爬、真实浏览器指纹，且 session 隔离、可并发。

**智能混合策略**：默认先用本地 HTTP（快、免费、不占云端 session），遇到动态页/反爬/正文过短
时自动升级到云端浏览器。大多数页面走 HTTP，少数难抓的才用云端，省钱。

## 部署（只有搜索需要一次性建 Gateway）

搜索走真 AgentCore Web Search Tool 需要你账号里有一台 Gateway：`python3 infra/provision.py`
一键创建（建 IAM 角色 + MCP Gateway + web-search target，幂等可重跑，只在 us-east-1）。
输出的 GATEWAY_URL 设进环境变量 `AGENTCORE_WEBSEARCH_GATEWAY_URL`。不设则搜索自动回退 DuckDuckGo。

## 抓取不需要部署

us-west-2 已有 AWS 托管的默认 browser 实例 `aws.browser.v1`（状态 READY），开箱即用。
本机已实测：用 IAM user `invokemodule` 能启动 session、拿到 CDP 端点、Playwright 连上抓页面。

## 工具

| 工具 | 用途 |
|------|------|
| `web_search` | 搜索，返回标题/URL/摘要（不抓正文）。engine: duckduckgo（默认）/ google |
| `fetch_page` | 抓单个 URL 正文 → markdown。force_browser / force_http / wait_selector |
| `fetch_batch` | 并发抓多个 URL |
| `deep_search` | 一步：搜索 + 抓 top-K 正文 |
| `deep_search_multi` | 并发跑多个子查询（deep research breadth 展开）|
| `browser_status` | 看配置/region，排查连接 |

## 已注册到 Claude Code

项目级 `.mcp.json`（在 `aitools/` 目录）。首次需在交互式 `claude` 会话里批准一次
（项目级 MCP 的安全机制），之后即可用。

```bash
# 查看状态
cd /Users/baizhenx/Downloads/Bybit-acct/aitools
claude mcp get agentcore-deepsearch
```

## 本地开发 / 调试

```bash
cd /Users/baizhenx/Downloads/Bybit-acct/aitools/agentcore-deepsearch
source .venv/bin/activate
python -m agentcore_deepsearch.server   # 直接跑（stdio）
```

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `AGENTCORE_REGION` | us-west-2 | 云端浏览器 region |
| `AGENTCORE_BROWSER_ID` | aws.browser.v1 | AWS 托管默认 browser |
| `AGENTCORE_SESSION_TIMEOUT` | 600 | session 存活上限（秒，最大 28800）|
| `DEEPSEARCH_MAX_CHARS` | 50000 | 单页正文上限，防爆上下文 |
| `DEEPSEARCH_FETCH_CONCURRENCY` | 4 | 批量抓取并发 |
| `DEEPSEARCH_HTTP_MIN_GOOD` | 600 | HTTP 正文短于此则升级云端浏览器 |

AWS 凭证走 `~/.aws/credentials` 的 default profile（boto3 自动读）。

## 架构

```
server.py        FastMCP 入口，暴露 6 个工具
 ├ research.py   deep_search 编排（搜索+批量抓取打包）
 ├ search.py     web_search（DDG / Google-via-browser）
 ├ fetch.py      智能混合抓取（HTTP 优先，弱则升级云端）
 │   └ browser.py  云端浏览器 session 管理（复用+空闲回收+收尾）
 ├ extract.py    trafilatura 提炼正文 → markdown + 元数据
 └ config.py     全部可调参数（环境变量覆盖）
```

## 成本注意

- 云端 session 按时长计费。本 server 全局复用单 session + 空闲自动回收 + 进程退出收尾。
- 能 HTTP 就别 force_browser（默认策略已处理）。
- 单账号最多 500 并发 session。不自动解 CAPTCHA。
