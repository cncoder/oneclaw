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

```bash
openclaw daemon install --force
openclaw node install --force
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

# 3. Plist points at new version
grep "openclaw@" ~/Library/LaunchAgents/ai.openclaw.gateway.plist

# 4. launchd status
launchctl list | grep openclaw    # exit codes 0, PIDs present

# 5. Daemon status
openclaw daemon status            # Runtime: running, RPC probe: ok

# 6. Error log scan
tail -20 ~/.openclaw/logs/gateway.err.log | grep -iE "error|fatal|api key|bedrock"

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

---

## Design note

Much of this runbook exists because upgrade today is not atomic. The long-term direction is to collapse it into:

- `openclaw upgrade` — one-shot install + `daemon install --force` + smoke test
- `openclaw doctor --deep` — agent smoke test and pnpm store health check built in
- `doctor --fix` — covers all known config migrations

When those land, this skill will get much shorter.
