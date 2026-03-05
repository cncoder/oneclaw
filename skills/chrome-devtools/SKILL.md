---
name: chrome-devtools
description: "Browser automation via Chrome DevTools Protocol (CDP). Use for UI verification, web scraping, screenshot-based debugging, and frontend testing through the chrome-devtools MCP server on port 9222."
metadata:
  openclaw:
    emoji: "🌐"
---

# Skill: chrome-devtools

Control a local Chrome instance via Chrome DevTools Protocol (CDP) on port 9222. Used for UI verification, web content extraction, frontend debugging, and visual testing.

---

## When to Use CDP vs Other Tools

| Task | Tool | Why |
|------|------|-----|
| Verify UI layout / visual quality | **CDP screenshot** | See what the user sees |
| Scrape dynamic / JS-rendered pages | **CDP navigate + snapshot** | WebFetch can't execute JS |
| Sites that block bots (Reddit, X, etc.) | **CDP** | WebFetch gets 403 |
| Read static documentation pages | WebFetch / MCP docs | Faster, no browser needed |
| Test API endpoints | curl / Bash | No browser needed |
| Fill forms, click buttons, test flows | **CDP** | Full browser interaction |

**Rule of thumb**: If WebFetch returns 403 or the page needs JavaScript, switch to CDP immediately.

---

## Prerequisites

Chrome must be running with CDP enabled on port 9222. OneClaw sets this up automatically via LaunchAgent (`ai.openclaw.chrome.plist`).

### Verify Chrome is Running

```bash
curl -s http://127.0.0.1:9222/json | head -5
```

If no response:
1. Check LaunchAgent: `launchctl list | grep openclaw.chrome`
2. Restart: `launchctl kickstart -k gui/$(id -u)/ai.openclaw.chrome`
3. If still down, tell the user — don't retry MCP calls blindly

---

## Core Workflow: Navigate → Wait → Act → Verify

Every CDP task follows the same pattern:

```
1. navigate_page(url)        → Load the page
2. wait_for(selector/text)   → Wait for content to render
3. take_screenshot()         → Capture current state (for verification)
4. [action: click/fill/etc]  → Interact if needed
5. take_screenshot()         → Verify result
```

**Never skip the wait step** — pages need time to render JS content.

---

## Common Operations

### Screenshot for UI Verification

```
1. navigate_page → target URL
2. wait_for → key element visible
3. take_screenshot → capture full page
4. Analyze screenshot: layout, colors, spacing, responsiveness
5. If issues found → fix code → rebuild → screenshot again
```

Iterate until the UI meets quality standards. Compare side-by-side with design references when available.

### Web Content Extraction

```
1. navigate_page → target URL
2. wait_for → content loaded
3. take_snapshot → get DOM text content
4. Parse the returned text for needed information
```

Use `take_snapshot` (DOM text) for data extraction, `take_screenshot` (image) for visual verification.

### Form Interaction

```
1. navigate_page → form URL
2. wait_for → form elements visible
3. fill(selector, value) → fill each field
4. click(submit_selector) → submit
5. wait_for → success indicator
6. take_screenshot → verify result
```

### Web Search (Google/Bing)

When you need to look up information, search the web directly via CDP:

```
1. navigate_page → https://www.google.com/search?q=your+search+query
2. wait_for → search results loaded (e.g., selector "#search" or text on page)
3. take_snapshot → extract search result titles, URLs, and snippets
4. navigate_page → click through to the most relevant result URL
5. wait_for → page content loaded
6. take_snapshot → extract the actual content
```

**Tips:**
- URL-encode the query string (`+` for spaces, `%22` for quotes)
- For specific site search: `q=site:docs.aws.amazon.com+lambda+timeout`
- If Google shows CAPTCHA, switch to Bing: `https://www.bing.com/search?q=...`
- Prefer `take_snapshot` (text) over `take_screenshot` (image) for extracting search results

### Multi-Page Navigation

```
1. list_pages → see all open tabs
2. select_page(id) → switch to target tab
3. navigate_page → go to new URL
4. Or: new_page → open in new tab
```

---

## Error Handling

### Timeout Errors (`Network.enable timed out` / `protocolTimeout`)

Most common CDP error. Solutions:

1. Set `protocolTimeout: 60000` (60 seconds) for slow pages
2. Retry once after timeout
3. If still failing → Chrome may be overloaded → restart Chrome:
   ```bash
   launchctl kickstart -k gui/$(id -u)/ai.openclaw.chrome
   sleep 3
   ```

### Chrome Not Running

```bash
# Quick check
curl -s http://127.0.0.1:9222/json >/dev/null 2>&1 && echo "UP" || echo "DOWN"
```

If DOWN:
- Don't retry MCP calls — they'll all timeout
- Tell the user Chrome CDP is down
- Suggest: `launchctl kickstart -k gui/$(id -u)/ai.openclaw.chrome`

### Page Load Failures

- `net::ERR_CONNECTION_REFUSED` → target server is down
- `net::ERR_NAME_NOT_RESOLVED` → DNS issue (check proxy settings)
- `net::ERR_CERT_*` → SSL issue (Stash proxy may interfere)

---

## UI Verification Loop (for frontend development)

After making frontend changes, always verify visually:

```
1. Build the project (npm run build / dev server)
2. navigate_page → localhost:PORT
3. take_screenshot → capture current state
4. Compare with expected design
5. If not matching:
   a. Identify specific CSS/layout issues from screenshot
   b. Fix code
   c. Rebuild
   d. Screenshot again
6. Repeat until pixel-perfect
```

**Quality checklist per screenshot:**
- Layout alignment and spacing
- Color scheme consistency
- Typography (font size, weight, line height)
- Responsive behavior (resize_page to test breakpoints)
- Interactive states (hover, focus, active)

---

## Performance & Best Practices

- **One action at a time** — don't batch CDP calls that depend on each other
- **Always wait after navigation** — `wait_for` a specific element, not a fixed sleep
- **Screenshot strategically** — before and after changes, not every micro-step
- **Close unused tabs** — `close_page` when done to free memory
- **Don't open too many tabs** — Chrome on 16GB Mac handles ~10 tabs comfortably

---

## Integration with Other Skills

| Combined with | Use case |
|---------------|----------|
| `claude-code` | Screenshot → analyze UI issue → fix code → rebuild → screenshot again |
| `aws-infra` | Navigate AWS Console pages to verify resource state visually |
| WebFetch fallback | WebFetch 403 → immediately switch to CDP |
