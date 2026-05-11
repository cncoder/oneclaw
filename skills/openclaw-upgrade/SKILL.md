---
name: openclaw-upgrade
description: "Upgrade OpenClaw to a specified version on macOS. Covers version check, proxy/network, pnpm install, config migration, launchd re-registration, and end-to-end verification. Triggered by: upgrade openclaw, update openclaw, openclaw update, openclaw upgrade."
---

# OpenClaw Upgrade Skill

Runbook for upgrading OpenClaw cleanly. Most steps are just safety nets — read Phase 0 → 7 in order, don't skip.

## Prerequisites

| Item | Notes |
|------|-------|
| Package manager | `pnpm` (global install) |
| `PNPM_HOME` | e.g. `$HOME/Library/pnpm` — export before any pnpm command |
| Network | If you're behind a firewall or fake-ip proxy, set `https_proxy` / `http_proxy` — pnpm does **not** inherit system proxy |
| Node | Homebrew `node@22` or later |
| Config file | `~/.openclaw/openclaw.json` |
| Gateway plist | `~/Library/LaunchAgents/ai.openclaw.gateway.plist` |
| Node plist | `~/Library/LaunchAgents/ai.openclaw.node.plist` |

> **Proxy tip**: on Clash / Stash fake-ip mode, pnpm direct-connect times out. Export the proxy in the same shell:
> `export https_proxy=http://127.0.0.1:<your-port> http_proxy=http://127.0.0.1:<your-port>`

---

## Phase 0: Pre-flight

```bash
# Current version
openclaw --version

# Latest published
https_proxy=$https_proxy npm view openclaw dist-tags --json
```

Decide the target version (usually `latest`).

## Phase 1: Read the Changelog

Check https://github.com/openclaw/openclaw/releases for the target version. Look for:

- **Security fixes** → must upgrade
- **Breaking changes** → verify your config is compatible (see Phase 4)
- **New features only** → optional

## Phase 2: Install

```bash
export PNPM_HOME="$HOME/Library/pnpm"
export PATH="$PNPM_HOME:$PATH"

https_proxy=$https_proxy http_proxy=$http_proxy \
  pnpm add -g openclaw@<TARGET_VERSION>
```

Gotchas:

- `pnpm update -g` does **not** cross major versions — always `pnpm add -g openclaw@<version>`
- Don't run multiple `pnpm add openclaw` in parallel — they deadlock each other
- Use a 10-minute timeout; postinstall (bundled plugins) is slow
- If `postinstall @discordjs/opus` fails but the command ends with `Done`, continue — verify in Phase 3

## Phase 2.5: Clean pnpm store (only when Phase 3 fails)

If `openclaw --version` reports `ERR_MODULE_NOT_FOUND` (e.g. `tslog`), the pnpm store is corrupt from a failed postinstall:

```bash
# 1) Roll back to a known-good version first
pnpm add -g openclaw@<LAST_KNOWN_GOOD>

# 2) Prune the store
pnpm store prune

# 3) Move any leftover broken dirs (don't rm — use trash)
mv "$PNPM_HOME/global/5/.pnpm/openclaw@<BROKEN>"* ~/.Trash/ 2>/dev/null || true

# 4) Re-try Phase 2
```

## Phase 3: Verify install

```bash
openclaw --version
```

Failure modes:

- `ERR_MODULE_NOT_FOUND` → pnpm store dirty, go to Phase 2.5
- `Invalid config ... Unrecognized key` → config migration needed, see Phase 4

## Phase 4: Config migration

```bash
openclaw doctor 2>&1
# Many issues can be auto-fixed
openclaw doctor --fix
```

Common breaking changes across versions:

| Area | What changed | How to fix |
|------|--------------|-----------|
| `agents.defaults.cliBackends` | Removed | Delete the key from `openclaw.json` |
| `talk.voiceId` | Moved | `openclaw doctor --fix` |
| `agents.*.sandbox.perSession` | Removed | `openclaw doctor --fix` |
| Telegram/Discord `streaming: "block"` | Schema changed | Change to `streaming: { mode: "block" }` |
| Feishu `streaming` / `footer` / `threadSession` / `groups` | Removed | Remove or `doctor --fix` |
| Bedrock inference profile (old IDs like `claude-opus-4-6-v1`) | May be deprecated | Update `agents.defaults.model.primary`, `imageModel.primary`, and each sub-agent's `model` |

### Bedrock authentication

Newer releases run the embedded agent via `pi-coding-agent` (`@mariozechner/pi-ai`), which reads **process environment variables only** — not `openclaw.json > env.vars`. The auth chain looks for one of:

- `AWS_PROFILE`
- `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`
- `AWS_BEARER_TOKEN_BEDROCK`
- `AWS_CONTAINER_CREDENTIALS_*` / `AWS_WEB_IDENTITY_TOKEN_FILE`

You must set these in **both** places:

1. `~/.openclaw/openclaw.json > env.vars` (for OpenClaw itself)
2. `~/Library/LaunchAgents/ai.openclaw.gateway.plist > EnvironmentVariables` (for the gateway child process that spawns pi-ai)

```xml
<key>AWS_REGION</key><string>us-west-2</string>
<key>AWS_ACCESS_KEY_ID</key><string>AKIA...</string>
<key>AWS_SECRET_ACCESS_KEY</key><string>...</string>
```

After editing the plist you **must** `launchctl bootout` + `launchctl bootstrap` (not `kickstart -k` — that doesn't reload env).

### Node native modules

If you also ran `brew upgrade node`, `@tobilu/qmd`'s `better-sqlite3` binding can break with `ERR_DLOPEN_FAILED NODE_MODULE_VERSION mismatch`:

```bash
cd "$(brew --prefix)/lib/node_modules/@tobilu/qmd" && npm rebuild better-sqlite3
```

## Phase 5: Re-register launchd services

**Do not skip this.** plists hardcode the OpenClaw version path — without re-registering, the daemon keeps running the old version.

> ⚠️ **Gateway and node are two independent launchd services.** Both commands below are required — missing either one leaves that plist pointing at a deleted version path, and the corresponding service crash-loops silently (see Pitfall #11).

```bash
openclaw daemon install --force   # refreshes ai.openclaw.gateway.plist
openclaw node install --force     # refreshes ai.openclaw.node.plist

# Immediately verify BOTH plists point at the new version
grep "openclaw@" \
  ~/Library/LaunchAgents/ai.openclaw.gateway.plist \
  ~/Library/LaunchAgents/ai.openclaw.node.plist

# Check node isn't already crash-looping on a stale path
tail -5 ~/.openclaw/logs/node.err.log
```

## Phase 5.5: Agent smoke test

`doctor ok` only tests channel config. It does **not** test the embedded-agent → Bedrock chain. Run a real agent call:

```bash
openclaw agent --agent main -m "say hi in 3 words" --timeout 60
```

Failure matrix:

| Error | Root cause |
|-------|-----------|
| `No API key found for amazon-bedrock` | Plist missing `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` |
| `reason=auth candidate=...claude-opus-4-6-v1` | Old Bedrock inference profile deprecated — update `model.primary` |
| `ERR_DLOPEN_FAILED better_sqlite3` | Node upgraded, rebuild qmd |

## Phase 6: End-to-end verification

All must pass:

```bash
# 1. CLI version
openclaw --version

# 2. Gateway process running
sleep 5 && pgrep -fl openclaw-gateway

# 3. BOTH plists point at the new version (gateway + node)
grep "openclaw@" \
  ~/Library/LaunchAgents/ai.openclaw.gateway.plist \
  ~/Library/LaunchAgents/ai.openclaw.node.plist
# If either line still shows the old version, Phase 5 was incomplete

# 4. launchd status
launchctl list | grep openclaw    # both gateway AND node: exit codes 0, PIDs present

# 5. Daemon status
openclaw daemon status            # Runtime: running, RPC probe: ok

# 6. Error log scan — check BOTH logs (gateway ok ≠ node ok)
tail -20 ~/.openclaw/logs/gateway.err.log | grep -iE "error|fatal|api key|bedrock"
tail -20 ~/.openclaw/logs/node.err.log    | grep -iE "cannot find module|error|fatal"
# A `Cannot find module '.../openclaw@<OLD_VERSION>/...'` line means the node plist
# is still stale — re-run `openclaw node install --force`

# 7. Channel connectivity
openclaw doctor 2>&1 | grep -E "Discord|Telegram|Feishu"
```

## Phase 7: Rollback

If anything above fails and can't be fixed quickly:

```bash
https_proxy=$https_proxy http_proxy=$http_proxy \
  pnpm add -g openclaw@<LAST_KNOWN_GOOD_VERSION>

openclaw daemon install --force
openclaw node install --force
openclaw --version
```

---

## Phase 5.6: Channel plugin verification (post-5.x external plugins)

From OpenClaw 5.x onward, **Lark/Telegram/Discord are external plugins** — separately resolved under `~/.openclaw/plugins/` or the pnpm store and are not automatically reinstalled by `pnpm add -g openclaw@<ver>`. After every upgrade, verify each enabled channel actually loaded:

```bash
# Enabled channels in config
python3 -c "import json; d=json.load(open('$HOME/.openclaw/openclaw.json')); \
  print([c for c in ('discord','feishu','telegram','qqbot') if c in d and d[c].get('enabled',True)])"

# Each enabled channel must show up in doctor output
openclaw doctor 2>&1 | grep -iE "discord|feishu|telegram|qqbot"

# And in the channel account list (should list at least one account per enabled channel)
openclaw message list-accounts 2>&1 || openclaw channel list 2>&1

# Send a real message to each channel (bypasses agent turn, tests pure channel path)
openclaw message send --account <accountId> --channel <channel> --to <chatId> --text "post-upgrade ping"
```

If a channel is **enabled but not loaded**, you'll see `plugin not found` / `unknown channel` in `doctor`. Fix:

```bash
pnpm add -g @openclaw/channel-feishu@latest   # or whichever plugin is missing
# then restart gateway+node
launchctl kickstart -k gui/$UID/ai.openclaw.gateway
launchctl kickstart -k gui/$UID/ai.openclaw.node
```

## Phase 5.7: Cron & delivery sanity (long-running jobs)

If you have cron jobs with `payload.kind: agentTurn` that call long pipelines, re-check after upgrade:

- Agent turn driven by `Bash` tool has a **hard 1800s cap** — any synchronous wait past that is SIGKILL'd regardless of `timeoutSeconds`. Any pipeline > 25 min **must** run in async-fork mode (see `qmd-openclaw-patterns` skill).
- `delivery.mode: "announce"` publishes **every** agent output to the channel — including `started` / `idle` stubs. This is a common source of channel spam after upgrades rewire delivery. Prefer `on-content` (if supported by your version) or have the wrapper self-push via `openclaw message send` with `delivery.mode: "none"`.

```bash
# List all cron jobs and scan for risky long sync turns
openclaw cron list --json | python3 -c "
import json,sys
for j in json.load(sys.stdin).get('jobs',[]):
    t = j.get('payload',{}).get('timeoutSeconds',0)
    m = j.get('delivery',{}).get('mode')
    if t > 1500 or m == 'announce':
        print(f\"⚠️  {j['name']}  timeout={t}s  delivery={m}\")"
```

---

## Common Pitfalls (the 30-second list)

1. **Proxy not exported** → `pnpm add` hangs / `ECONNRESET`. Always export `https_proxy` / `http_proxy` inline.
2. **`pnpm update -g` used** → won't cross major versions. Use `pnpm add -g openclaw@<version>`.
3. **Parallel `pnpm add`** → deadlock. Kill other `pnpm add.*openclaw` processes first.
4. **Plist not re-registered** → daemon keeps running the old version. `daemon install --force` + `node install --force` are mandatory.
5. **Bedrock env only in `openclaw.json`** → embedded agent (pi-ai) ignores it. Credentials must be in the gateway plist `EnvironmentVariables`.
6. **Unknown config keys** → blocks startup. Run `doctor --fix` or remove removed fields (e.g. `cliBackends`).
7. **pnpm store poisoned by failed postinstall** → same-version reinstall reuses bad cache. Run `pnpm store prune` + clear the broken version dir.
8. **`postinstall @discordjs/opus` error** → can roll back the whole bundled-plugins install, breaking `tslog` and friends. See Phase 2.5.
9. **Old Bedrock inference profiles** → `claude-opus-4-6-v1` etc. may be deprecated. Update every `model.primary` reference.
10. **`doctor ok` ≠ agent ok** → Phase 5.5 smoke test is non-optional.
11. **Gateway alive ≠ node alive** → `ai.openclaw.gateway` and `ai.openclaw.node` are two independent launchd services with independent plists. Running only `daemon install --force` (and skipping `node install --force`) leaves the node plist pointing at a deleted version path; the node host then `MODULE_NOT_FOUND` crash-loops forever. Symptoms: `openclaw --version` ok, `doctor` ok, but `node.err.log` explodes, launchd relaunches the process continuously, memory pressure builds until Jetsam starts killing apps or the kernel panics. Always re-register both services, always grep both plists, always tail `node.err.log` after upgrade.
12. **Channel plugins not upgraded with core** — from 5.x channels are external plugins. `pnpm add -g openclaw@<v>` does **not** touch `@openclaw/channel-*`. If doctor shows `plugin not found` for an enabled channel, `pnpm add -g @openclaw/channel-<name>@latest` and restart.
13. **Bash tool 1800s hard cap on cron `agentTurn`** — any sync pipeline > 25 min gets SIGKILL'd regardless of `timeoutSeconds`. Symptom: pipeline appears to "disappear" at exactly 30 min, no log tail, no delivery. Fix: async-fork wrapper (see `qmd-openclaw-patterns` skill); the agent turn returns `{status:"started"}` in <2s and the forked child calls `openclaw message send` on completion.
14. **Async-fork lock inheritance bug** — if parent acquires lockfile → forks child → child re-enters `stage 0` → child trips on parent's lock and fails + sends false "fail" message. Fix: child reads `DIGEST_CHILD=1` env and skips stage-0 lock acquisition, inheriting parent's lock.
15. **`delivery.mode: announce` spams channels** — every agent output (including `"started"` / `"idle"`) is published. For async cron jobs where the wrapper does its own final push, set `delivery.mode: "none"` and self-push via `openclaw message send`.
16. **Bash heredoc × Python f-string quote hell** — `$(python3 -c "... f\"...{d['key']}...\" ...")` silently SyntaxError's in wrappers. Only the success path hits the f-string, so failures in fail-path code go unnoticed until success day comes and silently drops the notification. Use single-quoted heredoc `python3 <<'PY' ... PY` or hand-off via JSON files.
17. **Cross-profile URL context pollution** — when one cron/agent session processes multiple profiles (e.g. `primary` then `secondary`), the agent's context keeps both CloudFront URLs; a later "fail" summary can grab the wrong one. Mitigation: hard rule in payload `"forbid cloudfront URL on status != ok"`, and/or put each profile in a separate `sessionTarget: isolated` job.

---

## Design note

Much of this runbook exists because upgrade today is not atomic. The long-term direction is to collapse it into:

- `openclaw upgrade` — one-shot install + `daemon install --force` + smoke test
- `openclaw doctor --deep` — agent smoke test and pnpm store health check built in
- `doctor --fix` — covers all known config migrations

When those land, this skill will get much shorter.
