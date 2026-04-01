---
name: chrome-devtools
description: "Browser automation via Chrome DevTools Protocol (CDP). Use for UI automation, form filling, data scraping, E2E testing, screenshot capture, and interacting with logged-in platforms. Use this instead of the browser tool when you are in Claude Code context."
metadata:
  openclaw:
    emoji: "🌐"
---

# Skill: chrome-devtools

Browser automation via Chrome DevTools Protocol. When Claude Code needs to interact with web pages — scrape data, verify UI, fill forms, test flows — use CDP through the `chrome-devtools` MCP server.

> **Golden rule: Always take a snapshot before clicking.** Element UIDs change after every page navigation.

---

## When to Use What

| Task | Tool | Why |
|------|------|-----|
| Claude Code needs browser | **CDP** (this skill) | Direct MCP control |
| OpenClaw agent browsing | `browser` tool (built-in) | Managed by OpenClaw |
| Static docs / simple pages | `web_fetch` | Faster, no browser needed |
| JS-rendered / SPA pages | **CDP** | web_fetch can't execute JS |
| Bot-blocked sites | **CDP** with logged-in profile | Real browser fingerprint |

---

## Quick Start

```
# 1. Open a NEW tab (never navigate in existing tabs!)
mcp__chrome-devtools__new_page  url="https://example.com"

# 2. Wait for content
mcp__chrome-devtools__wait_for  text=["loaded"]

# 3. Take snapshot (get element tree + UIDs)
mcp__chrome-devtools__take_snapshot

# 4. Interact using UIDs from snapshot
mcp__chrome-devtools__click  uid="<uid>"

# 5. Verify result
mcp__chrome-devtools__take_screenshot
```

---

## Core Operations

### Navigation
```
mcp__chrome-devtools__new_page       url="https://..."          # Always start here
mcp__chrome-devtools__navigate_page  type="url" url="https://..." # Within YOUR tab only
mcp__chrome-devtools__navigate_page  type="reload"
mcp__chrome-devtools__navigate_page  type="back"
```

### Reading Pages
```
# Accessibility tree with UIDs — use for interaction
mcp__chrome-devtools__take_snapshot

# Visual screenshot — use for layout verification or AI analysis
mcp__chrome-devtools__take_screenshot
mcp__chrome-devtools__take_screenshot  fullPage=true
```

### Interaction
```
mcp__chrome-devtools__click      uid="<uid>"
mcp__chrome-devtools__fill       uid="<uid>"  value="text"
mcp__chrome-devtools__fill_form  elements=[{"uid":"<uid1>","value":"val1"}, ...]
mcp__chrome-devtools__type_text  text="search term"  submitKey="Enter"
mcp__chrome-devtools__press_key  key="Enter"
mcp__chrome-devtools__press_key  key="Control+A"
```

### Wait & Verify
```
mcp__chrome-devtools__wait_for  text=["Dashboard", "Welcome"]
mcp__chrome-devtools__wait_for  text=["loaded"]  timeout=10000
```

### Tab Management
```
mcp__chrome-devtools__list_pages
mcp__chrome-devtools__select_page  pageId=1
mcp__chrome-devtools__close_page   pageId=2
```

### JavaScript & Network
```
mcp__chrome-devtools__evaluate_script       function="() => document.title"
mcp__chrome-devtools__list_network_requests resourceTypes=["fetch","xhr"]
mcp__chrome-devtools__get_network_request   reqid=42
mcp__chrome-devtools__list_console_messages types=["error","warn"]
```

### Dialogs & File Upload
```
mcp__chrome-devtools__handle_dialog  action="accept"
mcp__chrome-devtools__handle_dialog  action="dismiss"
mcp__chrome-devtools__upload_file    uid="<file-input-uid>"  filePath="/path/to/file"
```

---

## Workflows

### Standard: Navigate → Snapshot → Act → Verify

```
1. new_page      → open fresh tab
2. wait_for      → confirm page loaded
3. take_snapshot → get element tree + UIDs
4. click / fill  → interact using UIDs
5. wait_for      → confirm action result
6. take_snapshot → verify final state
```

### Screenshot + AI Analysis (recommended for complex pages)

For pages with complex layouts, dynamic content, or when DOM parsing is fragile:

```
1. new_page → target URL
2. take_screenshot fullPage=true → capture entire page
3. Analyze screenshot with AI (describe what you see, extract data)
4. Scroll / paginate → screenshot again → analyze again
```

> **Why this beats DOM parsing**: No brittle selectors, works on any layout, handles dynamic content naturally. Multiple screenshots + AI analysis is more robust than regex on HTML.

### Multi-Page Data Collection

Don't just look at the first screen. Complete data requires:

```
1. Scrape page 1
2. Click "Next" / pagination / tabs
3. Scrape page 2
4. Repeat until all pages covered
5. Aggregate results
```

---

## Hard Rules

1. **Never navigate in existing tabs** — Always `new_page` first. The user may have unsaved work in their current tab. Overwriting it = data loss.

2. **Snapshot before every interaction** — UIDs are ephemeral. After any navigation or page change, take a fresh snapshot to get current UIDs.

3. **Scroll for complete data** — First screen ≠ all data. Scroll down, click through tabs, paginate.

4. **Separate scraping from logged-in accounts** — Aggressive scraping on a personal account risks getting it banned. Use dedicated profiles for bulk collection.

5. **Never close the main Chrome process** — CDP connection depends on it.

---

## Setup

Chrome must be running with remote debugging enabled:

```bash
# Verify CDP is available
curl -s http://127.0.0.1:9222/json/version

# If not running, start Chrome with CDP
google-chrome --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.chrome-cdp-profile"

# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.chrome-cdp-profile"
```

### Port Auto-Detection

If port 9222 isn't responding, common alternatives: `9222`, `9223`, `18800`. Check which port Chrome is actually using:

```bash
lsof -iTCP -sTCP:LISTEN | grep -i chrome
```

### Proxy Conflicts

If you're running a local proxy (Clash, Stash, etc.), `curl localhost` may route through the proxy and fail. Fix:

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:9222/json
```

For Python websocket connections:
```python
import os
for k in list(os.environ):
    if 'proxy' in k.lower(): del os.environ[k]
os.environ['NO_PROXY'] = '*'
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| MCP calls hang | CDP port wrong | Check `lsof` for actual port |
| `curl localhost:9222` hangs | Proxy intercepting | Add `NO_PROXY=localhost` |
| UIDs don't match | Page changed since snapshot | Take fresh snapshot |
| Screenshot is blank/tiny | Page not loaded yet | Add `wait_for` before screenshot |
| Click does nothing | Wrong UID or element hidden | Snapshot → verify element is visible |
| `navigate_page` overwrites user's tab | Used navigate instead of new_page | Always `new_page` first |
