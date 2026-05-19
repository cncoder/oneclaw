---
name: browser-automation
description: "Abel 的浏览器自动化决策与执行指南。在 CDP MCP（精确单步）、browser-use Agent（多步探索）、WebFetch（静态读）、本地 grep（文档调研）之间做选择，并内置失败 fallback 链。"
metadata:
  version: "1.0"
  author: "Abel + Claude Code"
  base_on: "transcripts audit of 24 projects, 360MB of history"
---

# Skill: browser-automation

Abel 的浏览器栈决策树。**先看决策表，再看 Quick Start，最后看红线**。

---

## 🌲 决策树（先读这个）

**核心原则：能不用浏览器就不用，能不多步就不多步。每上升一层成本 × 5-10 倍。**

```
需要获取 / 操作 Web 内容？
│
├─ 【Level -1 - 不走浏览器】有原生 API / CLI 吗？
│   ├─ AWS 操作 → aws CLI（aws s3 mb、aws ec2 run-instances...）
│   ├─ 飞书/Lark 操作 → lark-im / lark-doc / lark-calendar 等官方 skill
│   ├─ GitHub → gh CLI（gh pr view、gh api）
│   ├─ 查库文档 → Context7 MCP（query-docs）
│   ├─ 查 AWS 文档 → aws-documentation MCP（search_documentation）
│   └─ K8s/EKS → eks MCP（禁用 kubectl/eksctl）
│   ⚠️ 铁律："能不点界面就不点界面"，API 比操纵 DOM 稳 100 倍
│
├─ 【Level 0 - 零成本】目标是开源项目/已克隆代码？
│   └─ ✅ Grep / Read 本地文件
│       - git clone --depth 1 一次，以后随便 grep
│       - 查 GitHub release / CHANGELOG / pyproject.toml 版本号 → 本地读
│
├─ 【Level 1 - 最便宜】目标是静态 HTML 页面，一次能拿完?
│   └─ ✅ WebFetch
│       - HN 首页、博客、SSR 的 GitHub 页面、SEO 优化的产品页
│       - 判断依据：view-source 能直接看到内容 = 静态
│       - 403 → 下一层 fallback
│
├─ 【Level 2 - 中等】需要登录态 / JS 渲染的 SPA？
│   └─ ✅ Chrome DevTools MCP（附加 abel-chrome profile）
│       - Lark / AWS 控制台 / Gmail / 微信后台 / Notion / Figma
│       - ⚠️ 一定 new_page 开新 tab（铁律：Tab 保护）
│       - 先 take_snapshot 拿 UID 再 click
│       - SPA 页面操作超过 3 步 → 每步重新 snapshot
│
├─ 【Level 3 - 贵】多步条件分支任务（步骤数事先未知）？
│   └─ ✅ browser-use Agent（高层 API）
│       ⚠️ 判断标准很严格：
│       - 下一步要做什么依赖上一步的页面内容
│       - 步骤数 ≥ 5，且分支多
│       - 手写 CDP snapshot→click 状态机太冗长
│       例如：
│       - "去某电商站找最便宜的 X 牌子蓝牙耳机" ✅
│       - "查 HN 前 20 个帖子" ❌（静态 HTML 一次拿完）
│       - "在 Lark 搜 X" ❌（2 步就完成，上 CDP 就够）
│
├─ 【特殊】性能分析 / Lighthouse / trace
│   └─ Chrome DevTools MCP — performance_start_trace + lighthouse_audit
│
├─ 【特殊】反爬严重（Yahoo Finance / Reddit / X / Nitter）
│   ├─ 已登录：CDP MCP 走 abel-chrome
│   └─ 未登录：browser-use stealth（BROWSER_USE_STEALTH=true）
│
├─ 【特殊】E2E 测试（可重复跑固定流程）
│   └─ Playwright（只在 CI/测试场景）
│
└─ 【特殊】每天跑的 RPA 脚本
    └─ LaVague 生成 Playwright 脚本 或 手写
```

### 🧠 自检问题（选择工具前问自己）
0. **有 API / CLI / 官方 skill 吗？** → 有就**根本别开浏览器**（AWS CLI、gh CLI、lark-*、Context7、aws-documentation MCP）
1. 本地 / 缓存里有这份数据吗？ → 有就别走网络
2. `curl -s URL | grep 关键词` 能拿到吗？ → 能就 WebFetch
3. 必须登录才能看吗？ → 必须 → CDP MCP（abel-chrome）
4. 步骤数 ≥ 5 且事先不知道怎么走吗？ → 是 → browser-use Agent
5. 否则 → CDP MCP 手动编排

---

## 📋 Quick Start — 按场景

### 场景 A：读一个文档页（最常见）

```python
# 1. 先试 WebFetch
WebFetch(url="https://...", prompt="提取 X Y Z")

# 2. 403 / JS-only → Chrome CDP
#    ⚠️ 绝对不要 navigate 当前 tab，开新 tab
mcp__chrome-devtools__new_page(url="https://...")
mcp__chrome-devtools__wait_for(text=["关键词"])
mcp__chrome-devtools__take_snapshot()
```

### 场景 B：操作已登录站点（Lark 发消息、AWS 建 EC2）

```python
# 附加到 abel-chrome profile，用户已登录态
mcp__chrome-devtools__new_page(url="https://...")
mcp__chrome-devtools__take_snapshot()   # 拿 UID

# ⚠️ UID 在 SPA 页面可能刷新后失效，失败一次立即重新 snapshot
mcp__chrome-devtools__click(uid="24_7")
```

### 场景 C：多步探索任务（browser-use Agent）

```bash
# 第一次用先安装
uv tool install browser-use
uvx browser-use install    # 安装 chromium

# .env
echo 'BROWSER_USE_API_KEY=' >> ~/.config/browseruse/.env
# 或配 Bedrock:
# export AWS_REGION=us-west-2
# export BROWSER_USE_LLM_MODEL=bedrock/us.anthropic.claude-sonnet-4-6
```

```python
from browser_use import Agent, Browser, ChatAWSBedrock

browser = Browser(
    user_data_dir="/Users/abel/Library/Application Support/Google/Chrome/abel-chrome",
    # ⚠️ 不能和日常 Chrome 同时跑！先 Cmd+Q 退出 Chrome
)
agent = Agent(
    task="Go to https://cloud.browser-use.com, find today's pricing for bu-2-0, return as JSON",
    llm=ChatAWSBedrock(model="us.anthropic.claude-sonnet-4-6"),
    browser=browser,
    max_steps=15,
)
result = await agent.run()
```

### 场景 D：作为 MCP 工具用（推荐，最省事）

```jsonc
// ~/.claude/settings.json
{
  "mcpServers": {
    "browser-use": {
      "command": "uvx",
      "args": ["browser-use[cli]", "--mcp"],
      "env": {
        "AWS_REGION": "us-west-2",
        "BROWSER_USE_LLM_MODEL": "bedrock/us.anthropic.claude-sonnet-4-6",
        "BROWSER_USE_USER_DATA_DIR": "${HOME}/.config/browseruse/profiles/claude"
      }
    }
  }
}
```

然后直接在 Claude Code 里调 `mcp__browser-use__retry_with_browser_use_agent`。

---

## 🚨 红线（Abel 铁律扩展）

1. **永不 navigate 当前 tab**  
   Abel 可能正在用，覆盖 = 数据丢失。永远 `new_page`。

2. **CDP 9222 端口同时只能有一个 Chrome 进程**  
   想跑 browser-use 就 `Cmd+Q` 退出日常 Chrome，或用独立 profile（`~/.config/browseruse/profiles/claude`）

3. **UID 是易碎的**  
   - Snapshot 后页面 navigate / reload / SPA 切换 → UID 全部失效
   - 规则：**连续操作超过 3 步，每步重新 snapshot**
   - `Element uid "X_Y" not found` 报错时：重新 snapshot，不要重试原 UID

4. **失败 fallback 链**  
   ```
   WebFetch 403 → CDP MCP（登录态）→ browser-use stealth → 放弃改手工
   CDP 超时 → 不要 pkill Chrome！先 cdp-status.sh 看状态
   CDP 连接失败 → ~/.claude/scripts/cdp-start.sh（脚本会处理 pkill）
   browser-use 卡住 → 检查 profile 是否被 Chrome 占用
   ```

5. **不在 Mac 本地跑 browser-use 的推理**  
   browser-use 的 LLM 调用必须走 Bedrock / API，**不要启用本地 Ollama/MLX**
   （和 Abel 全局"本地禁跑 TTS 模型推理"是一类铁律：Mac 资源宝贵）

6. **browser-use 任务失败重试 ≤ 2 次**  
   失败 2 次停下来，输出当前 page state，让人看一眼再决定。不要在错误假设上叠加修复。

---

## 🧪 验证你装对了

```bash
# 1. 检查 CDP MCP（现有）
~/.claude/scripts/cdp-status.sh

# 2. 检查 browser-use CLI
uvx browser-use --version

# 3. 跑一个 smoke test
uvx browser-use --mcp &
# 应该监听 stdio，不报错即可
```

---

## 🔀 和 oneclaw chrome-devtools skill 的关系

| 这个 skill | oneclaw/skills/chrome-devtools |
|-----------|-------------------------------|
| 决策层：什么场景用什么工具 | 执行层：CDP MCP 具体怎么调 |
| 包含 browser-use Agent 场景 | 只讲 CDP |
| 内置 fallback 链 | 单工具使用说明 |

**两个同时存在**，本 skill 先决策，再转 oneclaw 执行。

---

## 历史失败数据（为什么有这些红线）

Abel 24 个项目会话审计（is_error=true）：

| 失败模式 | 次数 | 红线对应 |
|---------|------|---------|
| CDP connect fail | 6 | 红线 #4 |
| WebFetch 403 | 4 | 红线 #4 |
| UID stale | 4 | 红线 #3 |
| Playwright module err | 3 | —（极少用，不重要）|

总失败率 <0.5%，说明现栈已经稳定。引入 browser-use 是**补能力**，不是**替换**。
