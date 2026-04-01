---
name: claude-code
description: "Use Claude Code as your autonomous coding agent. Covers task dispatch via tmux, interactive/background/loop modes, progressive task delivery, slot-machine recovery, and best practices for getting the most out of Claude Code via OpenClaw."
metadata:
  openclaw:
    emoji: "⚡"
    requires:
      bins: ["tmux", "claude"]
---

# Skill: claude-code

Claude Code is a full autonomous coding agent — not just a code generator. Treat it as a teammate that can explore codebases, write code, run tests, fix errors, and iterate until the job is done.

---

## Mode Selection

Pick the right mode before starting:

| Scenario | Mode | When |
|----------|------|------|
| Multi-file changes, need visibility | **Interactive** | Default choice |
| Single file, <2 min, predictable output | **Background one-shot** | Quick tasks |
| Self-iterating feature development | **loop** | Large autonomous tasks |

**Classify the task first** (from Anthropic internal practices):

| Type | Examples | Strategy |
|------|----------|----------|
| **Peripheral / async** | Prototypes, test generation, refactoring, unfamiliar codebase | loop or auto-accept, let it run |
| **Core / sync** | Core business logic, security changes, config, multi-component coordination | Interactive mode, supervise in real-time |

---

## tmux Session Management

Claude Code uses an Ink TUI framework — it's not a regular shell. OpenClaw dispatches and monitors Claude Code through tmux sessions, which is more reliable than osascript/AppleScript.

### Architecture

Each CC task gets its own tmux session (`cc-{task}`), tracked via `/tmp/cc-active-tab`. Three scripts handle the lifecycle:

| Script | Purpose | Mechanism |
|--------|---------|-----------|
| `cc-start.sh` | Create tmux session + launch CC | Writes `/tmp/cc-active-tab` |
| `cc-send.sh` | Send messages to the right session | 3-level fallback resolution |
| `cc-read.sh` | Read terminal output | `tmux capture-pane` + ANSI strip |

### Starting a Task

```bash
# Standard launch (background, --bare for speed, --max-turns 200)
scripts/cc-start.sh my-feature

# With specific working directory
scripts/cc-start.sh tts-fix ~/projects/my-app

# Foreground (watch in real-time)
scripts/cc-start.sh my-feature --foreground

# Custom max-turns
scripts/cc-start.sh big-refactor ~/project --max-turns 50

# Need MCP/skills/hooks (disable --bare)
scripts/cc-start.sh complex-task ~/project --no-bare

# View / attach to running session
tmux attach -t cc-my-feature   # Ctrl+B, D to detach
tmux ls                         # List all sessions
```

**❌ Never launch CC with raw `tmux new-session`** — always use `cc-start.sh` so the active session tracker stays in sync.

### Sending Messages

```bash
# Auto-locate most recent CC session
scripts/cc-send.sh "implement the auth middleware"

# Target specific session
scripts/cc-send.sh --session cc-auth "add rate limiting"

# Multi-line via heredoc
scripts/cc-send.sh <<'MSG'
Read src/main.py and describe:
1. Data flow
2. Key functions
3. Error handling patterns
MSG
```

**Session resolution** (3-level fallback):
1. `--session <name>` → exact tmux session
2. `/tmp/cc-active-tab` → most recently launched (with validation)
3. Last `cc-*` session found → fallback

### Reading Output

```bash
scripts/cc-read.sh                       # Auto-locate, last 50 lines
scripts/cc-read.sh --session cc-auth     # Specific session
scripts/cc-read.sh --lines 100           # Last 100 lines
scripts/cc-read.sh --full                # Full scrollback
scripts/cc-read.sh --status              # Just the status (idle/working/error)
```

### Detecting CC State

| Terminal shows | State | Action |
|----------------|-------|--------|
| `❯` empty prompt | Done, waiting | Send next sub-task |
| `Bootstrapping…` / `Cogitating…` | Context compaction | **Wait — don't interrupt, don't /clear** |
| `Enter to confirm` | Waiting for approval | `tmux send-keys -t <session> Enter` |
| `Error` / `failed` | Error | Evaluate: retry or reset |
| No change for 5+ min | Possibly stuck | Report to user |

---

## Interactive Mode: Progressive Task Delivery

The key to getting good results from Claude Code: **break work into verifiable steps**.

### Splitting Principles (from Anthropic reports)

- Split by **dependency + verification points**
- Each sub-task has a **clear completion signal**
- Single sub-task < 30 minutes, ≤ 3 files
- Separate: core logic / edge cases / refactoring

### The 5-Step Flow

```
Step 1: Explore — "Read X, describe the architecture"
  → Signal: structure description output
  → Check: Does it understand correctly?

Step 2: Design — "Based on that, propose a plan"
  → Signal: plan text
  → Check: Is the plan reasonable?

Step 3: Small-batch verify — "Implement the core function only"
  → Signal: code compiles, tests pass
  → Check: build + test + sampling ← most critical checkpoint

Step 4: Full execution — "Now handle all cases"
  → git commit checkpoint first
  → Check: spot-check + integration test

Step 5: Polish — "Review and fix remaining issues"
  → Signal: no obvious problems
```

### Three-Layer Verification

| Layer | Method | Purpose |
|-------|--------|---------|
| Syntax | `build` / `compile` passes | No obvious errors |
| Logic | `test` / `lint` passes | Meets spec |
| Effect | Screenshot / logs / sampling | Actually works as expected |

### When to Interrupt

| Signal | Action |
|--------|--------|
| Over-engineering (3+ layers of abstraction) | Interrupt: "find a simpler approach" |
| Same tool call fails 3 times | Interrupt, try different approach |
| Drifting from main goal | Interrupt, refocus |
| 2x over estimated time | **Slot Machine: git reset --hard, start over** |
| Output quality declining | Roll back to last checkpoint |

---

## Slot Machine Protocol

From Anthropic's Data Science team:

> `git commit` → let Claude run → success: merge, failure: `git reset --hard`, start over.
>
> **Starting fresh beats trying to fix a derailed intermediate state.**

This works because Claude Code is stochastic — the same prompt can produce very different results. A fresh attempt often succeeds where debugging a bad attempt would take longer.

---

## Background One-Shot Mode

For simple, predictable single tasks:

```bash
# Note: unset CLAUDECODE inside OpenClaw to avoid nesting error
unset CLAUDECODE && claude --dangerously-skip-permissions -p "describe the task"
```

- No mid-course correction possible
- Only for < 2 minute, well-defined tasks
- Must `unset CLAUDECODE` in OpenClaw agent context

---

## loop Mode (Large Autonomous Tasks)

**Always checkpoint before launching** (Slot Machine):

```bash
# 1. Checkpoint
git add -A && git commit -m "checkpoint: before loop"

# 2. Launch
/loop "Build X. Output <promise>DONE</promise> when tests pass." \
  --completion-promise "DONE" --max-iterations 15
```

- Success → merge
- Failure → `git reset --hard HEAD~1` + revise prompt + retry
- Cancel: `/loop stop`

---

## CLAUDE.md: Teaching CC Your Conventions

Every time CC makes a repeated mistake, add a rule to your project's `CLAUDE.md`. This is reinforcement learning in practice (from Anthropic RL team):

```markdown
# Tool conventions
- pytest: `pytest tests/ -v`, never `python -m pytest`
- Delete files: `mv` to trash dir, never `rm -rf`
- Bash failure → diagnose first, don't blindly retry
- Use absolute paths, avoid unnecessary `cd`
- Long text: use heredoc or write to file, not single-line commands
```

Over time, CLAUDE.md becomes a living rulebook that prevents recurring mistakes.

---

## Two-Phase Workflow (Complex Tasks)

From Anthropic Legal + Growth Marketing teams:

**Phase 1 — Plan** (in conversation):
```markdown
## Goal
[One sentence]
## Constraints
- [Limitation]
## Steps
1. [Specific, verifiable step]
## Acceptance Criteria
- [Conditions verifiable by command]
```

**Phase 2 — Execute**: Feed the structured prompt to Claude Code.

> Don't dump vague requirements into Claude Code. Plan first, execute second.

---

## Session Health Monitoring

Integrate into your heartbeat / monitoring:

```bash
CC_SESSIONS=$(tmux ls -F '#{session_name}' 2>/dev/null | grep '^cc-' || true)
CC_PROC=$(pgrep -f "claude --danger" | head -1)

if [ -z "$CC_SESSIONS" ] && [ -z "$CC_PROC" ]; then
    echo "CC not running"
elif [ -z "$CC_SESSIONS" ] && [ -n "$CC_PROC" ]; then
    echo "⚠️ CC process alive but tmux session lost — may need restart"
elif [ -n "$CC_SESSIONS" ] && [ -z "$CC_PROC" ]; then
    echo "⚠️ tmux session exists but CC process exited"
fi
```

---

## Anti-Patterns

- ❌ Dump 500-word requirement doc in one message (split into steps)
- ❌ Write code yourself instead of delegating to CC
- ❌ Run multiple CC instances on the same repo
- ❌ Use background one-shot for complex tasks
- ❌ Say "done" without verifying
- ❌ Try to fix CC's derailed intermediate state (reset and restart)
- ❌ Wait until CC finishes to evaluate (interrupt early if going wrong)
- ❌ Manual `/clear` (let auto-compact handle context management)
- ❌ Use raw `tmux new-session` (always use cc-start.sh)
- ❌ Send next message before confirming previous was received
- ❌ Let CC read >10K char files in one go (split reads to avoid context overflow)
