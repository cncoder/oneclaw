---
name: qmd-openclaw-patterns
description: "Battle-tested OpenClaw 5.x configuration patterns — qmd memory backend, async-fork long-running cron, isolated sessions, multi-profile delivery routing, channel plugin hygiene. Use when tuning openclaw.json for production stability or when cron jobs mysteriously die at ~30 min."
---

# OpenClaw Production Patterns

Reference configs + rationale for running OpenClaw 5.x with qmd memory, multiple agents, multiple channels, and long-running cron jobs. Based on production use; every pattern here has a scar.

All snippets assume `~/.openclaw/openclaw.json` and `~/.openclaw/workspace/`.

---

## Pattern 1 — qmd as memory backend

`qmd` (Quick Markdown, `brew install tobilu/tap/qmd`) beats the default SQLite memory for one reason: it writes plain Markdown files you can diff, grep, version-control, and edit by hand. Vector search happens in a local better-sqlite3 index.

```json
"memory": {
  "backend": "qmd",
  "qmd": {
    "command": "qmd",
    "searchMode": "search",
    "scope": { "default": "allow" }
  }
}
```

Rules of thumb:

- **Index path** — let qmd own `~/.qmd/`; don't point OpenClaw at a pre-existing dir it didn't create.
- **Routing by filename** — agent compaction prompts should route durable facts to `memory/semantic/*.md`, verified workflows to `memory/procedural/*.md`, and dated decisions to `memory/YYYY-MM-DD.md`, with a concise `MEMORY.md` index.
- **Node upgrades break qmd** — `brew upgrade node` rebuilds the native runtime but not qmd's `better-sqlite3`. After every Node upgrade:
  ```bash
  cd "$(brew --prefix)/lib/node_modules/@tobilu/qmd" && npm rebuild better-sqlite3
  ```
- **Never `rm -rf ~/.qmd/`** — it's your long-term memory. `mv` to `~/Documents/trashllm/` if you really must.

---

## Pattern 2 — Context-window economics

```json
"agents": {
  "defaults": {
    "contextTokens": 600000,
    "bootstrapMaxChars": 40000,
    "bootstrapTotalMaxChars": 200000,
    "contextPruning": { "mode": "cache-ttl", "ttl": "1h" },
    "compaction": {
      "mode": "safeguard",
      "reserveTokensFloor": 30000,
      "memoryFlush": {
        "enabled": true,
        "softThresholdTokens": 470000,
        "forceFlushTranscriptBytes": "2mb"
      }
    },
    "thinkingDefault": "adaptive"
  }
}
```

- `memoryFlush.softThresholdTokens` at ~78% of `contextTokens` gives the agent room to do a clean flush instead of a compaction that loses nuance.
- `reserveTokensFloor` is the safety margin below which `safeguard` forcibly compacts. Keep >= 30k for Opus; smaller and Opus can't even finish a tool call.
- `cache-ttl` pruning with `1h` matches Bedrock prompt-cache TTL — keeps hits warm for heartbeat-driven agents.

Model params — retention per model:

```json
"models": {
  "amazon-bedrock/us.anthropic.claude-opus-4-7":   { "params": { "cacheRetention": "long"  } },
  "amazon-bedrock/us.anthropic.claude-sonnet-4-6": { "params": { "cacheRetention": "long"  } },
  "amazon-bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0": { "params": { "cacheRetention": "short" } }
}
```

Haiku short-retention is intentional — it's the fast IO worker; cache bloat costs more than hits save.

---

## Pattern 3 — Sub-agents with tool denylists

Every sub-agent gets `tools.profile: "full"` minus a targeted `deny` list, not an allowlist.

```json
{
  "id": "researcher",
  "model": "amazon-bedrock/us.anthropic.claude-sonnet-4-6",
  "tools": { "profile": "full", "deny": ["gateway", "cron", "nodes", "tts"] }
},
{
  "id": "ops",
  "model": "amazon-bedrock/us.anthropic.claude-opus-4-7",
  "tools": { "profile": "full", "deny": ["gateway", "browser", "tts"] }
}
```

Why deny not allow: OpenClaw ships new tools on every minor version; an allowlist silently drops capabilities on upgrade, while `deny` naturally narrows only what you explicitly distrust.

---

## Pattern 4 — Isolated workspaces per profile

Running a second profile (e.g. `secondary`) without cross-contaminating memory or cron state:

```json
{
  "id": "secondary",
  "workspace": "/path/to/workspace-secondary",
  "agentDir": "/path/to/agents/secondary/agent",
  "identity": { "name": "Secondary", "emoji": "🔹" }
}
```

And in the corresponding cron job:

```json
"sessionTarget": "isolated"
```

Isolated sessions each get their own transcript and compaction — without this, cross-profile context pollution produces the classic "wrong CloudFront URL in primary's failure message" bug (see upgrade skill pitfall #17).

---

## Pattern 5 — Long-running cron via async-fork

**The 1800-second bash cap is the single biggest failure mode for cron jobs.** Any agent turn that runs a pipeline synchronously past ~25 minutes gets SIGKILL'd, no log, no delivery, and launchd sometimes re-fires the job on next heartbeat.

### Anti-pattern (sync)

```json
"payload": {
  "kind": "agentTurn",
  "message": "run the 90-minute pipeline and tell me how it went",
  "timeoutSeconds": 7200
}
```

Dies at exactly 30 min. `timeoutSeconds: 7200` is a lie.

### Pattern (async-fork wrapper)

Cron payload:

```json
"payload": {
  "kind": "agentTurn",
  "message": "DIGEST_ASYNC=1 bash ~/.openclaw/workspace/tools/morning-digest-run.sh <profile>\n\nWrapper returns a one-line JSON in <2s. Only print a single status line based on it. Forbid any cloudfront URL in fail messages.",
  "timeoutSeconds": 60,
  "model": "amazon-bedrock/us.anthropic.claude-opus-4-7"
},
"delivery": { "mode": "announce", "channel": "discord", "to": "...", "accountId": "..." }
```

Wrapper (`morning-digest-run.sh`) outline:

```bash
#!/usr/bin/env bash
set -euo pipefail
PROFILE="${1:?profile required}"
LOCK="$HOME/.openclaw/state/digest-$PROFILE.lock"

# --- Child branch: does the long work, self-pushes on completion ---
if [[ "${DIGEST_CHILD:-0}" == "1" ]]; then
  # inherits parent's lock; DO NOT re-acquire
  if run_pipeline "$PROFILE"; then
    openclaw message send --account "$ACCOUNT_ID" --channel "$CHANNEL" \
      --to "$CHAT_ID" --text "✅ $PROFILE 早报：$PUBLISHED_URL"
  else
    openclaw message send --account "$ACCOUNT_ID" --channel "$CHANNEL" \
      --to "$CHAT_ID" --text "⚠️ $PROFILE 早报失败 stage=$STAGE"
  fi
  exit 0
fi

# --- Parent branch: lock, fork, return fast ---
exec 9>"$LOCK"
if ! flock -n 9; then
  echo '{"status":"fail","stage":"lock"}'
  exit 0
fi

if [[ "${DIGEST_ASYNC:-0}" == "1" ]]; then
  DIGEST_CHILD=1 nohup bash "$0" "$PROFILE" \
    >"$HOME/.openclaw/logs/digest-$PROFILE.log" 2>&1 </dev/null &
  disown
  echo '{"status":"started","pid":'"$!"'}'
  exit 0
fi
```

Critical invariants:

1. **Child skips stage-0 lock** via `DIGEST_CHILD=1` — otherwise it trips on the parent's lock and emits a false-fail delivery.
2. **Child self-pushes with `openclaw message send`** — don't wait for the agent. The agent turn is long gone.
3. **Parent sets `delivery.mode: "announce"` only to emit the `started` stub**. If you want to suppress that too, set `delivery.mode: "none"` and have the parent also self-push an "started" message.
4. **No f-strings in bash heredocs.** Either use single-quoted heredoc `<<'PY'` or hand JSON through a temp file.
5. **Each profile gets its own lockfile** and its own isolated cron job — never share one agent session across profiles, or you'll hit URL context pollution.

---

## Pattern 6 — Channel plugins are external (5.x+)

From OpenClaw 5.x, `@openclaw/channel-feishu`, `@openclaw/channel-discord`, `@openclaw/channel-telegram` are separate pnpm globals. The enable flags in `plugins.entries` don't install them:

```json
"plugins": {
  "entries": {
    "feishu":  { "enabled": true },
    "discord": { "enabled": true }
  },
  "allow": ["acpx","amazon-bedrock","browser","browser-agent","discord","feishu","litellm","memory-core","searxng","telegram"]
}
```

After every core upgrade, verify and (if needed) install:

```bash
openclaw doctor 2>&1 | grep -iE "feishu|discord|telegram"
# If a plugin is "not found":
pnpm add -g @openclaw/channel-feishu@latest
launchctl kickstart -k gui/$UID/ai.openclaw.gateway
launchctl kickstart -k gui/$UID/ai.openclaw.node
```

---

## Pattern 7 — Direct channel push without agent

For scripts, cron wrappers, monitors — anything that shouldn't spin up an LLM turn just to send a string:

```bash
openclaw message send \
  --account "<accountId>"   \  # e.g. "lark-primary" or "discord-ops"
  --channel "<channel>"     \  # "feishu" | "discord" | "telegram"
  --to "<chatId>"           \  # channel-specific chat id
  --text "hello"
```

`accountId` is the key under the channel plugin config, **not** the channel name. Running `openclaw message list-accounts` prints the valid set.

---

## Pattern 8 — env vars: put them where pi-ai can see them

The embedded `pi-coding-agent` (the thing that actually talks to Bedrock) reads **process env only**, not `openclaw.json > env.vars`. So AWS credentials must live in **both**:

1. `openclaw.json > env.vars` — for openclaw itself.
2. `~/Library/LaunchAgents/ai.openclaw.gateway.plist > EnvironmentVariables` — for the pi-ai child.

Prefer `AWS_PROFILE` + `~/.aws/credentials` over raw `AWS_ACCESS_KEY_ID` in the plist — the plist is plain XML, easily shoulder-surfed or leaked via `scutil --dns`-style accidents.

---

## Pattern 9 — Backup strategy for `openclaw.json`

Every non-trivial edit:

```bash
cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak-before-<what>-$(date +%Y%m%d-%H%M%S)
```

Why: `doctor --fix`, `daemon install --force`, and some plugin installs can and do mutate `openclaw.json`. `openclaw.json.last-good` is written by doctor itself but only captures the *last* good state — no trail of what changed.

Housekeeping: once monthly, trash any `.bak-*` older than 30 days to `~/Documents/trashllm/`, never `rm`.

---

## Verification checklist

After any config change:

```bash
# 1. JSON valid
python3 -m json.tool ~/.openclaw/openclaw.json > /dev/null

# 2. No unknown keys
openclaw doctor 2>&1 | grep -vE "^(ok|info|note)"

# 3. Memory backend working
echo "test memory" | openclaw agent --agent main -m "write a one-line note via memory tool, then search for it" --timeout 120

# 4. Each enabled channel reachable
for ch in discord feishu telegram; do
  openclaw message send --channel "$ch" --account "<your-account>" --to "<test-chat>" --text "cfg test" 2>&1 | head -1
done

# 5. Cron jobs have no >1500s sync turns
openclaw cron list --json | python3 -c "
import json,sys
for j in json.load(sys.stdin).get('jobs',[]):
    t=j.get('payload',{}).get('timeoutSeconds',0); m=j.get('delivery',{}).get('mode')
    if t>1500 or m=='announce': print(f\"⚠️  {j['name']} t={t}s delivery={m}\")"
```

---

## See also

- [`openclaw-upgrade`](../openclaw-upgrade/SKILL.md) — cross-version upgrade runbook
- [`openclaw-verify`](../openclaw-verify/SKILL.md) — end-to-end "is it actually working" check
