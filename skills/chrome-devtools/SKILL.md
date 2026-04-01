---
name: chrome-devtools
description: "Browser automation via Chrome DevTools Protocol (CDP). Use for UI automation, form filling, data scraping, E2E testing, screenshot capture, performance auditing, and interacting with logged-in platforms. Use this instead of the browser tool when you are in Claude Code context."
metadata:
  openclaw:
    emoji: "🌐"
---

# Skill: chrome-devtools

Browser automation via Chrome DevTools Protocol. When Claude Code needs to interact with web pages — scrape data, verify UI, fill forms, test flows, audit performance — use CDP through the `chrome-devtools` MCP server.

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
mcp__chrome-devtools__wait_for  text=["Example Domain"]

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
mcp__chrome-devtools__navigate_page  type="forward"
```

### Reading Pages
```
# Accessibility tree with UIDs — primary tool for interaction
mcp__chrome-devtools__take_snapshot

# Visual screenshot — use for layout verification or AI analysis
mcp__chrome-devtools__take_screenshot
mcp__chrome-devtools__take_screenshot  fullPage=true
mcp__chrome-devtools__take_screenshot  uid="<uid>"              # Screenshot specific element
mcp__chrome-devtools__take_screenshot  filePath="/tmp/page.png" # Save to file
```

### Interaction
```
mcp__chrome-devtools__click      uid="<uid>"
mcp__chrome-devtools__click      uid="<uid>"  dblClick=true     # Double-click
mcp__chrome-devtools__hover      uid="<uid>"                    # Hover (reveal tooltips/menus)
mcp__chrome-devtools__fill       uid="<uid>"  value="text"      # Input / textarea / select
mcp__chrome-devtools__fill_form  elements=[{"uid":"<uid1>","value":"val1"}, ...]
mcp__chrome-devtools__type_text  text="search term"  submitKey="Enter"
mcp__chrome-devtools__press_key  key="Enter"
mcp__chrome-devtools__press_key  key="Control+A"
mcp__chrome-devtools__drag       from_uid="<uid1>"  to_uid="<uid2>"
```

### Wait & Verify
```
mcp__chrome-devtools__wait_for  text=["Dashboard", "Welcome"]   # Resolves when ANY appears
mcp__chrome-devtools__wait_for  text=["loaded"]  timeout=10000  # Custom timeout (ms)
```

### Tab Management
```
mcp__chrome-devtools__list_pages
mcp__chrome-devtools__select_page  pageId=1
mcp__chrome-devtools__close_page   pageId=2
mcp__chrome-devtools__resize_page  width=1280  height=720
```

### JavaScript & Network
```
mcp__chrome-devtools__evaluate_script       function="() => document.title"
mcp__chrome-devtools__evaluate_script       function="(el) => el.innerText"  args=["<uid>"]
mcp__chrome-devtools__list_network_requests resourceTypes=["fetch","xhr"]
mcp__chrome-devtools__get_network_request   reqid=42
mcp__chrome-devtools__list_console_messages types=["error","warn"]
mcp__chrome-devtools__get_console_message   msgid=5
```

### Dialogs & File Upload
```
mcp__chrome-devtools__handle_dialog  action="accept"
mcp__chrome-devtools__handle_dialog  action="dismiss"
mcp__chrome-devtools__handle_dialog  action="accept"  promptText="my input"
mcp__chrome-devtools__upload_file    uid="<file-input-uid>"  filePath="/path/to/file"
```

### Device Emulation
```
# Emulate mobile viewport
mcp__chrome-devtools__emulate  viewport="375x812x3,mobile,touch"

# Dark mode
mcp__chrome-devtools__emulate  colorScheme="dark"

# Geolocation
mcp__chrome-devtools__emulate  geolocation="37.7749x-122.4194"

# Throttle network
mcp__chrome-devtools__emulate  networkConditions="Slow 3G"

# Throttle CPU (2x slowdown)
mcp__chrome-devtools__emulate  cpuThrottlingRate=2
```

### Performance & Memory

```
# Lighthouse audit (accessibility, SEO, best practices)
mcp__chrome-devtools__lighthouse_audit  device="desktop"  mode="navigation"

# Performance trace — navigate to target URL first
mcp__chrome-devtools__performance_start_trace  reload=true  autoStop=true
# If autoStop=false, manually stop:
mcp__chrome-devtools__performance_stop_trace
# Drill into specific insights from the trace results:
mcp__chrome-devtools__performance_analyze_insight  insightSetId="<id>"  insightName="LCPBreakdown"

# Heap snapshot (memory leak debugging)
mcp__chrome-devtools__take_memory_snapshot  filePath="/tmp/heap.heapsnapshot"
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

### Form Filling (Login, Search, etc.)

```
1. new_page → target URL
2. take_snapshot → find form fields
3. fill_form → fill all fields at once (more reliable than individual fill calls)
4. click → submit button
5. wait_for → success indicator
```

### Performance Audit

```
1. new_page → target URL
2. lighthouse_audit → get scores for a11y, SEO, best practices
3. performance_start_trace reload=true → record page load
4. performance_analyze_insight → drill into LCP, CLS, etc.
```

---

## Hard Rules

1. **Never navigate in existing tabs** — Always `new_page` first. The user may have unsaved work in their current tab. Overwriting it = data loss.

2. **Snapshot before every interaction** — UIDs are ephemeral. After any navigation or page change, take a fresh snapshot to get current UIDs.

3. **Scroll for complete data** — First screen ≠ all data. Scroll down, click through tabs, paginate.

4. **Separate scraping from logged-in accounts** — Aggressive scraping on a personal account risks getting it banned. Use dedicated profiles for bulk collection.

5. **Never close the main Chrome process** — CDP connection depends on it.

6. **Don't overwrite user tabs** — Closing or navigating pages you didn't open can destroy user state. Only manage pages you created with `new_page`.

---

## Setup

Chrome must be running with remote debugging enabled for CDP to work.

### Verify CDP is Running

```bash
curl -s http://127.0.0.1:9222/json/version
```

If this returns a JSON response with `webSocketDebuggerUrl`, CDP is ready.

### Start Chrome with CDP

**macOS:**
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.chrome-cdp-profile"
```

**Linux:**
```bash
google-chrome --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.chrome-cdp-profile"
```

**Headless (no GUI, for CI/servers):**
```bash
google-chrome --headless --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.chrome-cdp-profile"
```

The `--user-data-dir` flag creates a separate Chrome profile so CDP sessions don't interfere with your daily browser.

### MCP Server Configuration

Add to your `~/.mcp.json` (or project `.mcp.json`):

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["@anthropic-ai/chrome-devtools-mcp@latest", "--port=9222"]
    }
  }
}
```

### Port Auto-Detection

If port 9222 isn't responding, find which port Chrome is actually using:

```bash
# macOS / Linux
lsof -iTCP -sTCP:LISTEN | grep -i chrome
```

### Proxy Conflicts

If you're running a local proxy (Clash, Stash, Surge, etc.), `curl localhost` may route through the proxy and fail:

```bash
# Fix: bypass proxy for localhost
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:9222/json
```

If the MCP server itself is affected, set `NO_PROXY` in your shell profile:

```bash
# Add to ~/.zshrc or ~/.bashrc
export NO_PROXY="localhost,127.0.0.1"
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| MCP calls hang | CDP port wrong | `lsof -iTCP -sTCP:LISTEN \| grep chrome` to find actual port |
| `curl localhost:9222` hangs | Proxy intercepting localhost | `NO_PROXY=localhost,127.0.0.1 curl ...` |
| "Connection refused" on 9222 | Chrome not started with `--remote-debugging-port` | Restart Chrome with the flag (see Setup) |
| UIDs don't match | Page changed since snapshot | Take fresh snapshot before interacting |
| Screenshot is blank/tiny | Page not loaded yet | Add `wait_for` before screenshot |
| Click does nothing | Wrong UID or element not visible | Take snapshot → verify element exists and is visible |
| `navigate_page` overwrites user tab | Used navigate instead of new_page | Always `new_page` first |
| "No pages found" | Chrome has no open tabs | Open at least one tab in Chrome |
| Snapshot returns empty tree | Page is a PDF or non-HTML content | Use `take_screenshot` instead, or `evaluate_script` |
| `fill` doesn't work on dropdown | Element is a custom `<div>`, not `<select>` | Use `click` to open, then `click` to select option |
| Lighthouse audit times out | Page is very slow or requires auth | Navigate and log in first, then run audit with `mode="snapshot"` |
