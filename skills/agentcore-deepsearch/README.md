# agentcore-deepsearch

A deployable MCP server for deep web research, backed by **AWS Bedrock AgentCore**'s managed cloud browser. Works with Hermes Agent and Claude Code (any stdio-MCP host).

## What it does

- **Hybrid fetch:** local HTTP first (free, fast). Auto-upgrades to a cloud headless Chromium when a page is anti-bot / JS-rendered / SPA / too-short.
- Cloud Chromium runs in an isolated AWS-managed microVM (CDP over WebSocket) — real browser fingerprint, beats Cloudflare, no local Chrome needed.
- Bare stdio JSON-RPC — **no `mcp` SDK dependency**.

**6 tools:** `web_search` · `fetch_page` · `fetch_batch` · `deep_search` · `deep_search_multi` · `browser_status`.

## Files

| File | Role |
|---|---|
| `server.py` | JSON-RPC MCP shell — tool registry + dispatch |
| `fetcher.py` | hybrid fetch core (HTTP → cloud browser) + ddgs search |
| `requirements.txt` | pinned-floor deps (verified versions) |

## Setup

```bash
# 1. Put the code somewhere, e.g. ~/.claude/skills/agentcore-deepsearch
cp -r skills/agentcore-deepsearch ~/.claude/skills/agentcore-deepsearch
cd ~/.claude/skills/agentcore-deepsearch

# 2. Isolated venv (Python >= 3.10)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Smoke test (no AWS, no cost) — should print serverInfo + 6 tools
printf '%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | .venv/bin/python server.py
```

### AWS prerequisites (only for the cloud-browser path)

- Credentials resolvable by boto3 (`~/.aws/credentials` default profile, or env vars).
- A region with AgentCore Browser (e.g. `us-west-2`).
- IAM permissions:
  ```
  bedrock-agentcore:StartBrowserSession
  bedrock-agentcore:GetBrowserSession
  bedrock-agentcore:StopBrowserSession
  bedrock-agentcore:ConnectBrowserAutomationStream
  ```
- System browser `aws.browser.v1` needs no creation — the code reads the SDK's `DEFAULT_IDENTIFIER`, so it tracks AWS's latest default automatically.
- `web_search` (ddgs) and the local-HTTP path need **no AWS** — the server is useful even without Bedrock access.

## Mount it

**Hermes Agent** — `~/.hermes/config.yaml` under `mcp_servers`:
```yaml
mcp_servers:
  agentcore-deepsearch:
    command: ~/.claude/skills/agentcore-deepsearch/.venv/bin/python
    args: [~/.claude/skills/agentcore-deepsearch/server.py]
    cwd: ~/.claude/skills/agentcore-deepsearch
    env:
      AGENTCORE_REGION: us-west-2
      DEEPSEARCH_FETCH_CONCURRENCY: '4'
      DEEPSEARCH_MAX_CHARS: '50000'
    enabled: true
```

**Claude Code** — `~/.mcp.json` under `mcpServers`:
```json
{
  "mcpServers": {
    "agentcore-deepsearch": {
      "command": "~/.claude/skills/agentcore-deepsearch/.venv/bin/python",
      "args": ["~/.claude/skills/agentcore-deepsearch/server.py"],
      "cwd": "~/.claude/skills/agentcore-deepsearch",
      "env": { "AGENTCORE_REGION": "us-west-2" }
    }
  }
}
```

Restart the host, then confirm the child process is alive:
```bash
ps aux | grep "agentcore-deepsearch/server.py" | grep -v grep
```

## Env knobs

| Var | Default | Meaning |
|---|---|---|
| `AGENTCORE_REGION` | us-west-2 | AgentCore region |
| `AGENTCORE_BROWSER_ID` | (SDK default) | override system browser id |
| `DEEPSEARCH_FETCH_CONCURRENCY` | 4 | parallel fetches |
| `DEEPSEARCH_MAX_CHARS` | 50000 | per-page body cap (anti context-blowup) |
| `DEEPSEARCH_MIN_BODY_CHARS` | 500 | below this, an HTTP result is deemed blocked → upgrade to browser |

## Cost

Cloud sessions bill per CPU/memory-second (~$0.01 for a 10-min session). The hybrid strategy keeps you on free HTTP whenever possible — don't `force_browser` a static page. `web_search` and HTTP fetch are free.
