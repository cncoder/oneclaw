---
name: qmd-for-openclaw
description: "Install and operate qmd (Quick Markdown) as OpenClaw's memory backend. Replaces the default SQLite memory with plain-Markdown files you can grep, diff, and version control, backed by a local better-sqlite3 vector index. Covers install, multi-agent XDG isolation, launchd auto-sync (15-min cadence), index rot detection, and native-module rebuild after Node upgrades."
---

# qmd for OpenClaw — memory-backend setup & ops

Why qmd: your long-term memory is plain `.md` files you can grep, diff, and commit. Everything else is a side effect. The default SQLite memory is fast but opaque.

All paths assume `~/.openclaw/` as OpenClaw's data dir and `~/.cache/qmd/` as qmd's index. Adjust freely.

---

## Phase 1 — Install qmd

```bash
# macOS
brew install tobilu/tap/qmd

# Verify
qmd --version      # expect: qmd 1.0.x
qmd status         # first run: index is empty, Total=0
```

qmd is a single Go binary + a better-sqlite3 native module. Linux: grab the release binary from GitHub and place `better-sqlite3` via `npm i -g better-sqlite3` matched to your Node.

---

## Phase 2 — Switch OpenClaw's memory backend

Edit `~/.openclaw/openclaw.json`:

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

Back up first: `cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak-before-qmd-$(date +%Y%m%d-%H%M%S)`.

`searchMode: "search"` means agent calls go through `qmd search` (BM25 + vector). The alternative `read` only returns exact file hits — use `search` unless you have a reason not to.

---

## Phase 3 — Per-agent XDG isolation (multi-agent installs)

If you run more than one OpenClaw agent (e.g. `main`, `researcher`, `ops`), each needs its own qmd config dir so their collection lists don't collide. Share the **index** (`~/.cache/qmd/index.sqlite`) but split the **config** via XDG env vars.

Directory layout:

```
~/.openclaw/agents/
  main/qmd/
    xdg-config/qmd/index.yml     <- collections for main
    xdg-cache/                   <- scratch / embedding cache
  researcher/qmd/
    xdg-config/qmd/index.yml
    xdg-cache/
```

Each `index.yml` lists the Markdown sources this agent should see:

```yaml
collections:
  memory-root:
    path: /path/to/agent/workspace
    pattern: MEMORY.md
  memory-dir:
    path: /path/to/agent/workspace/memory
    pattern: "**/*.md"
  skills:
    path: /path/to/agent/workspace/skills
    pattern: "**/SKILL.md"
  core-docs:
    path: /path/to/agent/workspace
    pattern: "{AGENTS,SOUL,TOOLS,USER,PROJECTS,HEARTBEAT,IDENTITY,CLAUDE}.md"
  tasks:
    path: /path/to/agent/workspace/tasks
    pattern: "*.md"
```

Tune `pattern` with standard globs. Keep it lean — qmd re-walks everything on each `qmd update`, so 1 M markdown files cost real time.

Invocation pattern:

```bash
HOME="$HOME" \
XDG_CONFIG_HOME="$HOME/.openclaw/agents/main/qmd/xdg-config" \
XDG_DATA_HOME="$HOME/.openclaw/agents/main/qmd/xdg-cache" \
qmd update
```

Every agent points at the same `~/.cache/qmd/index.sqlite`, so a single `qmd embed` (Phase 5) covers everyone.

---

## Phase 4 — launchd auto-sync every 15 min (macOS)

The #1 qmd failure mode is "index rot" — users run `qmd update` once, never again, and 64 days later `qmd search` returns nothing. Fix it before it happens.

### 4a — the sync script

`~/.openclaw/scripts/qmd-sync-all.sh`:

```bash
#!/bin/bash
# Sync qmd index for every OpenClaw agent. Runs every 15 min via launchd.
set -u

LOG="$HOME/.openclaw/logs/qmd-sync.log"
mkdir -p "$(dirname "$LOG")"
echo "[$(date +%Y-%m-%dT%H:%M:%S%z)] sync start" >> "$LOG"

# Walk each agent's config and update
for ag in main researcher ops; do
  DIR="$HOME/.openclaw/agents/$ag/qmd"
  [ -d "$DIR/xdg-config" ] || continue
  OUT=$(HOME="$HOME" \
        XDG_CONFIG_HOME="$DIR/xdg-config" \
        XDG_DATA_HOME="$DIR/xdg-cache" \
        /opt/homebrew/bin/qmd update 2>&1 | grep -E 'Indexed:' | tail -1)
  echo "  [$ag] $OUT" >> "$LOG"
done

# Embed pending vectors once (all agents share the same index).
EMBED=$(HOME="$HOME" \
        XDG_CONFIG_HOME="$HOME/.openclaw/agents/main/qmd/xdg-config" \
        XDG_DATA_HOME="$HOME/.openclaw/agents/main/qmd/xdg-cache" \
        /opt/homebrew/bin/qmd embed 2>&1 | grep -E 'Done|Embedded|pending' | tail -1)
echo "  [embed] $EMBED" >> "$LOG"

echo "[$(date +%Y-%m-%dT%H:%M:%S%z)] sync done" >> "$LOG"
```

```bash
chmod +x ~/.openclaw/scripts/qmd-sync-all.sh
```

### 4b — launchd plist

`~/Library/LaunchAgents/com.<you>.qmd-sync.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>         <string>com.YOU.qmd-sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/YOU/.openclaw/scripts/qmd-sync-all.sh</string>
  </array>
  <key>StartInterval</key> <integer>900</integer>
  <key>RunAtLoad</key>     <true/>
  <key>StandardOutPath</key> <string>/Users/YOU/.openclaw/logs/qmd-sync.stdout.log</string>
  <key>StandardErrorPath</key> <string>/Users/YOU/.openclaw/logs/qmd-sync.stderr.log</string>
</dict>
</plist>
```

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.YOU.qmd-sync.plist
launchctl kickstart  gui/$UID/com.YOU.qmd-sync       # run once now
launchctl list | grep qmd-sync                       # expect exit code 0
```

Linux (systemd-user) equivalent: a `.timer` unit with `OnUnitActiveSec=15min` calling the same script.

---

## Phase 5 — Embeddings (optional but recommended)

`qmd update` rebuilds BM25 metadata only. Vector search needs `qmd embed`. The default embedder uses a local model (e.g. `embeddinggemma`) — free, ~46 s for 80 docs, no API cost, no data leaves the box.

Done once inside `qmd-sync-all.sh` per cycle; no extra setup needed after Phase 4.

First-time bulk embed of an existing corpus can take 10-30 min — let it finish before you judge performance.

---

## Phase 6 — Health checks (run these when memory "feels off")

```bash
# 1. Index fresh?
qmd status | grep -E "Total:|Updated:"
# Target: Updated < 1h; Total matches your Markdown file count
# Red flag: Updated > 24h (launchd stopped) or Total = 0 (first run / index corrupt)

# 2. Search actually returns hits?
qmd search "<a term you KNOW is in your notes>" | head
# 0 results for a known term = re-index (qmd update) or re-embed (qmd embed)

# 3. launchd still alive?
launchctl list | grep qmd-sync
# Missing = plist unloaded; bootstrap it again
# Exit code != 0 = tail the stderr log

# 4. Collections recognized?
qmd status | grep -A2 Collections
# If a collection shows "Files: 0 (updated 67d ago)", the path in index.yml is stale or empty
```

---

## Phase 7 — After Node upgrades: rebuild the native module

After `brew upgrade node` (or any Node major bump), `qmd search` starts failing with `MODULE_VERSION mismatch` or `better_sqlite3.node` ABI errors. The qmd binary itself is fine; only the native sqlite addon needs a rebuild.

```bash
cd "$(brew --prefix)/lib/node_modules/@tobilu/qmd" && npm rebuild better-sqlite3
# Verify
qmd status   # should respond without the ABI error
```

If `@tobilu/qmd` was installed via brew (not npm), the native module lives under brew's Cellar path instead — follow the error message or `brew reinstall tobilu/tap/qmd`.

---

## Common Pitfalls

1. **Running `qmd update` without `XDG_CONFIG_HOME`** — qmd silently uses `$HOME/.config/qmd/` which isn't where OpenClaw agents wrote their `index.yml`. Result: "nothing was indexed" and no error message. **Fix**: always invoke qmd with the XDG envs from Phase 3.
2. **Index rot** — launchd plist unloaded after macOS upgrade (Sequoia+ sometimes drops user agents). Symptom: `qmd status` shows `Updated: 67d ago`. **Fix**: `launchctl bootstrap` the plist again and check `launchctl list` every few weeks, or run a weekly cron that pages you if `Updated > 24h`.
3. **Shared index, per-agent config** — it's tempting to give each agent its own `~/.cache/qmd/index.sqlite` too. Don't. You'll rebuild the same vectors N times. Share the index; separate only the config.
4. **`rm -rf ~/.cache/qmd/`** — takes out your entire long-term memory. Use `mv` to a trash dir; a fresh `qmd update && qmd embed` regenerates from the Markdown sources, but backups are cheap insurance.
5. **`pattern: "**/*.md"` across `~`** — indexes your entire home directory. Minutes per `qmd update`, gigabytes of index. Scope every collection to a specific subtree.
6. **Node 22 → 23 upgrade** — ABI break; `qmd search` exits 1 silently. **Fix**: Phase 7 rebuild. Consider pinning Node with `brew pin node@22` if your stack requires it.
7. **OpenClaw doesn't see the backend change** — after editing `openclaw.json`, restart the agent (some builds don't hot-reload `memory.backend`). `launchctl kickstart -k gui/$UID/ai.openclaw.gateway` and `...node`.
8. **Agents' IDENTITY.md missing** — many `index.yml` templates include an `IDENTITY.md` collection. If the file isn't there, qmd just logs "Files: 0" and moves on. Easy to miss; fill in IDENTITY.md or remove the collection.

---

## Verification checklist (end-to-end)

```bash
# Fresh install sanity — all should succeed
command -v qmd && qmd --version
test -f ~/.openclaw/openclaw.json && python3 -m json.tool ~/.openclaw/openclaw.json > /dev/null
test -x ~/.openclaw/scripts/qmd-sync-all.sh
launchctl list | grep -q qmd-sync
qmd status | grep -q "Total: [1-9]"
qmd search "<known term>" | head -1 | grep -q qmd://

# Then inside OpenClaw, ask the agent:
#   "从你的记忆里找一下关于 <known fact> 的内容"
# It should cite a qmd:// URI.
```

When all seven lines pass, memory is live.

---

## See also

- [`qmd-openclaw-patterns`](../qmd-openclaw-patterns/SKILL.md) — broader 9-pattern production guide (Pattern 1 summarizes this skill)
- [`openclaw-upgrade`](../openclaw-upgrade/SKILL.md) — upgrade runbook notes when qmd's native module breaks after Node bump
