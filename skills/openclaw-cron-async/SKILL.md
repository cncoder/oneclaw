---
name: openclaw-cron-async
description: "Convert any OpenClaw cron job running > 25 min into the async-fork pattern. Solves the Bash-tool 1800s SIGKILL that silently kills long pipelines. Use whenever a cron job 'mysteriously disappears at 30 min', when adding a new pipeline that can exceed 25 min, or when delivery.mode: announce spams channels with started/idle stubs."
---

# OpenClaw Cron Async-Fork Pattern

A small, battle-tested refactor. Apply it once and any cron pipeline up to 24 h long stops dying.

## The problem in one paragraph

OpenClaw's Bash tool has a hard **1800-second cap per invocation**, independent of `payload.timeoutSeconds`. Any cron `agentTurn` that waits synchronously on a long pipeline is SIGKILL'd at ~30 min with no log tail, no delivery, and sometimes a relaunch on the next heartbeat. `timeoutSeconds: 7200` is a lie in this context.

## The fix in one paragraph

Split the wrapper into two branches via env flag. **Parent**: `flock`, `nohup` + `&` the child, `echo` a JSON status line, exit in < 2 s. **Child**: inherits the parent's lock, runs the pipeline for as long as it needs, and calls `openclaw message send` directly when done. The agent turn never waits. Delivery is by the child's own push.

---

## Phase 1 — Diagnose

```bash
# List jobs whose sync turn can be killed
openclaw cron list --json | python3 -c "
import json,sys
for j in json.load(sys.stdin).get('jobs',[]):
    t = j.get('payload',{}).get('timeoutSeconds',0)
    m = j.get('delivery',{}).get('mode')
    if t > 1500 or m == 'announce':
        print(f\"{j['name']:35s} timeout={t}s delivery={m}\")"
```

Also check cron run history for the footprint:

```bash
ls -lt ~/.openclaw/cron/runs/ | head -20
# look for: pipeline_timeout / SIGKILL @1800s / gap between 'started' and 'exit' ≥ 30 min
```

Every row printed above is a candidate. Keep going.

## Phase 2 — Wrapper skeleton

Drop-in template. Replace `run_pipeline`, the lockfile path, and the `openclaw message send` args for your job. Everything else is load-bearing.

```bash
#!/usr/bin/env bash
# ~/.openclaw/workspace/tools/<job>-run.sh
set -euo pipefail

PROFILE="${1:?profile required}"
LOCK="$HOME/.openclaw/state/<job>-$PROFILE.lock"
LOG="$HOME/.openclaw/logs/<job>-$PROFILE.log"

# Fill these in from your cron job's delivery config
ACCOUNT_ID="<from: openclaw message list-accounts>"
CHANNEL="<feishu|discord|telegram>"
CHAT_ID="<channel-specific chat id>"

# ============================================================
# CHILD branch: inherits parent lock, does the real work
# ============================================================
if [[ "${RUN_CHILD:-0}" == "1" ]]; then
  trap 'openclaw message send --account "$ACCOUNT_ID" --channel "$CHANNEL" \
        --to "$CHAT_ID" --text "⚠️ <job>($PROFILE) crashed at line $LINENO"' ERR

  if url=$(run_pipeline "$PROFILE"); then
    openclaw message send --account "$ACCOUNT_ID" --channel "$CHANNEL" \
      --to "$CHAT_ID" --text "✅ <job>($PROFILE) 完成：$url"
  else
    openclaw message send --account "$ACCOUNT_ID" --channel "$CHANNEL" \
      --to "$CHAT_ID" --text "⚠️ <job>($PROFILE) 失败"
  fi
  exit 0
fi

# ============================================================
# PARENT branch: lock, fork, return fast (< 2 s)
# ============================================================
mkdir -p "$(dirname "$LOCK")" "$(dirname "$LOG")"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo '{"status":"fail","stage":"lock"}'
  exit 0
fi

if [[ "${RUN_ASYNC:-0}" == "1" ]]; then
  RUN_CHILD=1 nohup bash "$0" "$PROFILE" >"$LOG" 2>&1 </dev/null &
  disown
  echo '{"status":"started","pid":'"$!"'}'
  exit 0
fi

# Fallback: run synchronously (dev / debug)
run_pipeline "$PROFILE"
```

Five invariants — **don't touch these**:

| # | Invariant | Why |
|---|-----------|-----|
| 1 | Child checks `RUN_CHILD=1` and **skips lock acquisition** | Re-entering `flock` blocks forever on the parent's lock, then times out and emits a false-fail push |
| 2 | Child calls `openclaw message send` directly | Agent turn is long gone; no other way to deliver |
| 3 | Parent writes status as **one-line JSON** | Agent's output format contract, keeps the "started" message deterministic |
| 4 | `disown` after `nohup ... &` | Without it, child dies when parent exits |
| 5 | `trap ... ERR` in the child | Unhandled errors inside a long async child vanish silently otherwise |

## Phase 3 — Rewrite the cron payload

Before:

```json
{
  "payload": {
    "kind": "agentTurn",
    "message": "run the 90-minute pipeline and tell me how it went",
    "timeoutSeconds": 7200
  },
  "delivery": { "mode": "announce", "channel": "discord", "to": "...", "accountId": "..." }
}
```

After:

```json
{
  "payload": {
    "kind": "agentTurn",
    "message": "RUN_ASYNC=1 bash /Users/you/.openclaw/workspace/tools/<job>-run.sh <profile>\n\nWrapper returns one-line JSON in <2s. Only print one status line:\n- status=started  -> \"⏳ <job>(<profile>) 已启动，完成后自动推送\"\n- status=fail stage=lock -> \"ℹ️ <job>(<profile>) 已在后台运行，本轮跳过\"\n- any other fail -> \"⚠️ <job>(<profile>) 启动失败 stage=<stage>\"\n\nHard rules:\n- Print only one line, no extra commentary\n- Do NOT sleep/poll\n- Do NOT output any cloudfront URL (final delivery happens from the wrapper)",
    "timeoutSeconds": 60
  },
  "delivery": { "mode": "announce", "channel": "discord", "to": "...", "accountId": "..." }
}
```

Notes:

- `timeoutSeconds: 60` — parent must return in < 2 s; 60 is generous headroom.
- Keep `delivery.mode: "announce"` here **only** so the starter stub reaches the channel. If you don't want the "⏳ 已启动" message at all, set `delivery.mode: "none"` and have the parent's `nohup ... &` branch also push a start notice via `openclaw message send`.
- The "forbid cloudfront URL" clause mitigates cross-profile URL context pollution (see Pitfalls #4).

## Phase 4 — Backup & apply

```bash
cp ~/.openclaw/cron/jobs.json \
   ~/.openclaw/cron/jobs.json.bak-before-async-$(date +%Y%m%d-%H%M%S)

# Edit jobs.json (jq inline edit, or hand-edit + JSON validate)
python3 -m json.tool ~/.openclaw/cron/jobs.json > /dev/null

openclaw cron list 2>&1 | grep -i error   # should be empty
```

Cron is re-read on each fire; no service restart needed. If you do want to confirm:

```bash
launchctl kickstart -k gui/$UID/ai.openclaw.gateway
```

## Phase 5 — Verify

Dry-run without waiting for the cron clock:

```bash
# Simulate the agent's Bash tool call
time RUN_ASYNC=1 bash ~/.openclaw/workspace/tools/<job>-run.sh <profile>
# Expect: one-line JSON, total wall time < 2 s

# Child running?
pgrep -fl "<job>-run.sh" | grep -v "RUN_ASYNC=1"

# Lock inherited?
lsof "$HOME/.openclaw/state/<job>-<profile>.lock"
# Should list exactly one process (the child)

# Watch the child complete and self-push
tail -f ~/.openclaw/logs/<job>-<profile>.log
```

Green signals:

- Agent turn wall time < 5 s
- Child process in `ps` for minutes/hours after agent returned
- Exactly one holder on the lockfile
- Channel receives **both** the `⏳ started` (from agent) and the `✅/⚠️ final` (from child)

---

## Common Pitfalls

1. **Child re-acquires lock** — forgot the `RUN_CHILD=1` env flag, or parent used a different lockfile path than child. Child sees the parent's lock, blocks, times out, emits false fail. **Fix**: single source of truth for `LOCK`, and child branch checks `RUN_CHILD` *first thing* — above any `flock` call.
2. **Bash heredoc × Python f-string quote hell** — the classic `$(python3 -c "... f\"...{d['key']}...\" ...")` silently `SyntaxError`s. Usually only the success path hits the f-string, so failures are unnoticed for weeks. **Fix**: single-quoted heredoc `python3 <<'PY' ... PY`, or hand off via JSON file + `json.load`. Never mix `$"..."` around Python inside bash.
3. **Parent `cd`/`exec` into the child** — `exec bash "$0" ...` replaces the parent, so lock is released and the agent's caller dies before printing JSON. **Fix**: `nohup bash "$0" ... &` + `disown`, then `echo` then `exit 0`.
4. **Cross-profile URL context pollution** — one cron job processes multiple profiles in the same agent session; fail-path summary grabs the wrong profile's CloudFront URL because it's still in context. **Fix**: one cron job per profile, each with `sessionTarget: "isolated"`. Plus the "no cloudfront URL on failure" hard rule in the payload.
5. **`delivery.mode: "announce"` spamming channels** — every agent output (including `started` / `idle` / debug strings) is published. With multiple async jobs this quickly becomes 5-10 redundant messages/day per channel. **Fix**: set `delivery.mode: "none"` and have the parent also call `openclaw message send` for the start notice. Or only use `announce` on channels tolerant of status pings (your private pulse channel, not the shared team room).
6. **No `trap ... ERR` in child** — long async pipeline crashes in the middle, child exits with non-zero, and nobody knows. **Fix**: `trap '...' ERR` at the top of the child branch that pushes a crash notice via `openclaw message send`.
7. **Orphaned lockfiles after a crash** — child died hard, `flock` never released (rare on macOS, common on Linux after kernel OOM). Next cron fires, parent sees stale lock, emits `fail stage=lock`, and the job is dead until manual cleanup. **Fix**: use `flock -w 60` for a bounded wait, or have the parent `rm` the lockfile when the PID recorded inside it is no longer alive.
8. **Child inherits an OpenClaw environment you don't want** — `NODE_OPTIONS`, `AWS_PROFILE`, proxy vars propagate into the child and sometimes break `pip install` or native CLI tools. **Fix**: `env -i` the child's `exec`, then re-export only what the pipeline needs.

---

## Reference: `openclaw message send` cheat-sheet

Channel-specific args (run `openclaw message list-accounts` to see valid `accountId`s):

```bash
# Feishu
openclaw message send --account <lark-account-id> --channel feishu \
  --to "<oc_xxx chat id>" --text "..."

# Discord
openclaw message send --account <discord-account-id> --channel discord \
  --to "<numeric channel id>" --text "..."

# Telegram
openclaw message send --account <tg-account-id> --channel telegram \
  --to "<chat id>" --text "..."
```

The wrapper's `ACCOUNT_ID` must match `delivery.accountId` in the cron job — otherwise the starter stub and final push go to different routes.

---

## See also

- [`qmd-openclaw-patterns`](../qmd-openclaw-patterns/SKILL.md) — broader 9-pattern production guide (this skill deep-dives Pattern 5)
- [`openclaw-upgrade`](../openclaw-upgrade/SKILL.md) — Phase 5.7 scans existing cron jobs for this risk after every upgrade
- [`openclaw-verify`](../openclaw-verify/SKILL.md) — end-to-end checks that include cron sanity
