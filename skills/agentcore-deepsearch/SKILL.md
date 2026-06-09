---
name: agentcore-deepsearch
description: 用 AWS Bedrock AgentCore 云端浏览器做联网深度调研、搜索、抓网页正文。Use when 要做带引用的多源调研 / 搜资料 / 抓动态页 / 反爬站 / SPA / 需 JS 渲染的页面。本机已部署同名 MCP server，优先用它而非裸 WebFetch。NOT for 抓本机已登录态的页面(用 chrome-cdp 9222)，NOT for 纯本地文件搜索(用 grep/search_files)。
version: 1.0.0
author: oneclaw
---

# AgentCore DeepSearch

基于 AWS Bedrock AgentCore 云端浏览器的搜索+抓取 MCP server。部署后做联网深度调研时优先用它。
**部署步骤（依赖安装 / IAM 权限 / 挂载到 Hermes 或 Claude Code）见同目录 [`README.md`](README.md)。**
约定源码放在 `~/.claude/skills/agentcore-deepsearch/`，venv 在该目录 `.venv/`（路径可自定，挂载配置里改一致即可）。

## 为什么用它

- 抓取走 AWS 全托管、隔离 microVM 里的云端 Chromium（us-west-2，系统默认实例 `aws.browser.v1`，代码动态从 SDK 取最新）。
- **智能混合抓取**：默认先本地 HTTP（快、免费、不占云端），遇到 JS 动态页 / 反爬 / Cloudflare / 正文过短，自动升级到云端浏览器重抓。
- 比裸 WebFetch 强：能跑 JS、过反爬、真实浏览器指纹、session 隔离。
- 比本机 chrome-cdp 强：云端隔离、可并发、不占用 Abel 本地 Chrome。

## 工具清单（MCP 名带前缀 `mcp__agentcore-deepsearch__`）

| 工具 | 用途 | 关键参数 |
|---|---|---|
| `web_search` | 搜索，返回 标题/URL/摘要，不抓正文 | `query`, `num_results`, `engine`(duckduckgo/google), `freshness`(day/week/month/year) |
| `fetch_page` | 抓单 URL 正文 → markdown | `url`, `force_browser`, `force_http`, `wait_selector` |
| `fetch_batch` | 并发抓多个 URL 正文 | `urls[]`, `force_browser`, `force_http` |
| `deep_search` | 一步：搜索 + 抓 top-K 正文 | `query`, `top_k_fetch`, `engine`, `force_browser` |
| `deep_search_multi` | 并发跑多个子查询 | `queries[]`, `top_k_fetch`, `engine` |
| `browser_status` | 看 region/配置，排查连接 | — |

## 标准 deep research 编排（递归在 LLM 侧，工具只取数）

1. **拆解**：大问题拆成 3~5 个子查询（不同角度 / 同义词 / 专有名词）。
2. **广撒网**：`deep_search_multi(queries=[...], top_k_fetch=3)` 一次并发把多组来源正文取回。还不确定读哪篇时先 `web_search` 看标题。
3. **提炼**：从 markdown 提炼 learnings（短句、高信息密度），每条记来源 URL。
4. **追问**：基于 learnings 生成 follow-up，对没查清的点再调一轮 `deep_search`。
5. **收敛**：信息饱和后写带引用总结，每个结论标 `[来源]`。URL 只能来自工具返回，绝不自己编。

## 什么时候加 force_browser / engine=google

- `engine="google"`：要 Google 质量、DDG 结果太少时。慢且占 session，按需。
- `force_browser=True`：明确是 SPA / 需登录 / JS 渲染 / 反爬严格的站。
- `force_http=True`：明知是爬虫友好的静态长页（Wikipedia、文档站），最快最省。
- 默认（都不传）：智能混合，大多数情况直接用默认。

## 省钱 / 注意

- 云端 session 按 CPU/内存秒计费（一个 10 分钟 session 约 $0.01）。能用 HTTP 就别 `force_browser`，别为一个静态页开云端。
- 抓取并发默认 4；不自动解 CAPTCHA，遇验证码页抓到提示文本需换源。
- 正文默认上限 50000 字符（防爆上下文），超长标 `truncated=true`。

## 排查

- 连不上先调 `browser_status` 看 region/凭证。AWS 凭证走 `~/.aws/credentials` default profile。
- 本地直接调试：`cd ~/.claude/skills/agentcore-deepsearch && .venv/bin/python server.py`，喂 JSON-RPC。
