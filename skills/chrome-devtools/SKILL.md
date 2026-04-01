---
name: chrome-devtools
description: "Browser automation via Chrome DevTools Protocol (CDP). Use for UI automation, form filling, data scraping, E2E testing, screenshot capture, and interacting with logged-in platforms. Connected to localhost:9222. Use this instead of the browser tool when you are in Claude Code context."
metadata:
  openclaw:
    emoji: "🌐"
---

# Skill: chrome-devtools

Control Chrome via CDP at `127.0.0.1:9222`. Use your Chrome profile with logged-in sessions for seamless automation.

> **Always take a snapshot before clicking.** UIDs change after page navigation.

---

## Quick Start

```
# Open a NEW tab for your work (never navigate in the user's current tab!)
mcp__chrome-devtools__new_page  url="https://example.com"

# Take snapshot of current page (returns a11y tree with uid for each element)
mcp__chrome-devtools__take_snapshot

# Take screenshot (visual verification)
mcp__chrome-devtools__take_screenshot
```

---

## When to Use CDP vs Other Tools

| Task | Tool | Why |
|------|------|-----|
| Claude Code UI automation | **CDP** (this skill) | Direct browser control via MCP |
| OpenClaw browsing / research | `browser` tool (built-in) | Managed by OpenClaw |
| Verify UI layout / visual quality | **CDP screenshot** | See what the user sees |
| Scrape dynamic / JS-rendered pages | **CDP** | web_fetch can't execute JS |
| Sites that block bots (Reddit, X, etc.) | **CDP** | web_fetch gets 403 |
| Read static documentation pages | web_fetch | Faster, no browser needed |
| Python script scraping | CDP WebSocket directly | See Python fallback below |

---

## Core Tools

### Navigation
```
# ⚠️ Always open new tab first — never navigate in user's current tab!
mcp__chrome-devtools__new_page  url="https://..."

# Only use navigate_page within YOUR OWN tab (after new_page or select_page)
mcp__chrome-devtools__navigate_page  type="url"  url="https://..."
mcp__chrome-devtools__navigate_page  type="reload"
mcp__chrome-devtools__navigate_page  type="back"
```

### Page Reading
```
# Snapshot — returns a11y tree with uid for each element (preferred for interaction)
mcp__chrome-devtools__take_snapshot

# Screenshot — use when visual layout matters
mcp__chrome-devtools__take_screenshot
mcp__chrome-devtools__take_screenshot  fullPage=true
```

### Interaction
```
# Click (get uid from snapshot first)
mcp__chrome-devtools__click  uid="<uid>"

# Fill input / select dropdown
mcp__chrome-devtools__fill  uid="<uid>"  value="text"

# Fill multiple fields at once
mcp__chrome-devtools__fill_form  elements=[{"uid":"<uid1>","value":"val1"},{"uid":"<uid2>","value":"val2"}]

# Type into focused element
mcp__chrome-devtools__type_text  text="hello"
mcp__chrome-devtools__type_text  text="search term"  submitKey="Enter"

# Press key / shortcut
mcp__chrome-devtools__press_key  key="Enter"
mcp__chrome-devtools__press_key  key="Control+A"
```

### Wait & Verify
```
mcp__chrome-devtools__wait_for  text=["Login successful", "Dashboard"]
mcp__chrome-devtools__wait_for  text=["loaded"]  timeout=10000
```

### Tab Management
```
mcp__chrome-devtools__list_pages
mcp__chrome-devtools__select_page  pageId=1
mcp__chrome-devtools__new_page  url="https://..."
mcp__chrome-devtools__close_page  pageId=2
```

### JavaScript Execution
```
mcp__chrome-devtools__evaluate_script  function="() => document.title"
mcp__chrome-devtools__evaluate_script  function="() => document.querySelector('h1').innerText"
```

### Network & Console
```
mcp__chrome-devtools__list_network_requests
mcp__chrome-devtools__list_network_requests  resourceTypes=["fetch","xhr"]
mcp__chrome-devtools__get_network_request  reqid=42
mcp__chrome-devtools__list_console_messages
mcp__chrome-devtools__list_console_messages  types=["error","warn"]
```

---

## Standard Workflow

```
1. new_page         — open NEW tab (never use user's current tab!)
2. wait_for         — confirm page loaded
3. take_snapshot    — get element tree + uids
4. click / fill     — interact using uid from snapshot
5. wait_for         — confirm result
6. take_snapshot    — verify final state
```

**Screenshot + AI 分析模式**（复杂页面推荐）：
```
1. new_page → 目标 URL
2. take_screenshot → 全页截图
3. 用 AI 分析截图内容（比 DOM 解析更准、更稳定）
4. 翻页/滚动 → 再截图 → 再分析
```
> 复杂网页别用正则硬抠 DOM — 多页截图给 AI 分析，更准更稳更好维护。

---

## Dialog & File Upload

### Dialog Handling
```
mcp__chrome-devtools__handle_dialog  action="accept"
mcp__chrome-devtools__handle_dialog  action="dismiss"
mcp__chrome-devtools__handle_dialog  action="accept"  promptText="input text"
```

### File Upload
```
mcp__chrome-devtools__upload_file  uid="<file-input-uid>"  filePath="/path/to/file"
```

---

## Python CDP (fallback)

When connecting via Python websockets, SOCKS5 proxy may break the connection. Always clear proxy:

```python
import os
for k in list(os.environ):
    if 'proxy' in k.lower(): del os.environ[k]
os.environ['NO_PROXY'] = '*'
ws = await websockets.connect(uri, proxy=None)
```

---

## Hard Rules

1. **Never close Chrome** — CDP port must stay open
2. **Never navigate in the current/focused tab** — user may be working in it. Always open a new tab first (`new_page`), then navigate in the new tab. Overwriting the user's active page = data loss
3. **Snapshot before interact** — always get fresh uids before clicking/filling
4. **Python + proxy** — always clear proxy env vars when connecting from Python
5. **Don't use logged-in accounts for scraping** — risk of account ban. Use separate profiles for bulk data collection
6. **Scroll the page** — don't only look at the first screen. Scroll down, click tabs, paginate to get complete data

---

## Prerequisites

Chrome must be running with CDP enabled (typically port 9222). Set up via launch agent or manual start:

```bash
# Verify Chrome CDP is running
curl -s http://127.0.0.1:9222/json | head -5

# If no response, start Chrome with CDP
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.openclaw/browser/chrome-cdp/user-data"
```
