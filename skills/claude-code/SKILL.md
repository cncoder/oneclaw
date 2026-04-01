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

| Scenario | Mode | When | Dispatch Method |
|----------|------|------|-----------------|
| Multi-file changes, need visibility | **Interactive** | Default choice | tmux (human typing) |
| Simple one-off, predictable output | **Background one-shot** | Quick tasks | `claude -p` |
| Self-iterating feature development | **`/loop`** | Large autonomous tasks | tmux (human starts `/loop`) |
| cron / script / automated pipeline | **Programmatic** | Automation & scheduling | `claude -p --output-format stream-json` |

**Classify the task first:**

| Type | Examples | Strategy |
|------|----------|----------|
| **Peripheral / async** | Prototypes, test generation, refactoring, unfamiliar codebase | `/loop` or auto-accept, let it run |
| **Core / sync** | Core business logic, security changes, config, multi-component coordination | Interactive mode, supervise in real-time |

---

## Programmatic Dispatch

When you need to invoke Claude Code from scripts, cron jobs, or automated pipelines, **do not use tmux send-keys**. Use `claude -p` (one-shot / print mode) instead.

### Interactive vs Programmatic

| | Interactive (tmux + TUI) | Programmatic (`claude -p`) |
|---|---|---|
| **Who** | Human operator | Script / cron / agent |
| **Visibility** | Real-time TUI, can watch & interrupt | stdout/stderr, parse JSON output |
| **Reliability** | Depends on human typing into tmux | Deterministic, no TUI involvement |
| **Multi-turn** | Yes (send messages back and forth) | No (single prompt → single response) |
| **Use case** | Supervising complex tasks, `/loop` | Automated tasks, CI/CD, scheduled jobs |

### cc-dispatch.sh

A simple wrapper for programmatic dispatch:

```bash
#!/bin/bash
# Dispatch a task to Claude Code programmatically (bypasses Ink TUI)
# Usage: cc-dispatch.sh 'your task description' [working-directory]
TASK="$1"
DIR="${2:-.}"
cd "$DIR" && claude -p --dangerously-skip-permissions "$TASK"
```

For structured output (useful in pipelines):

```bash
cd "$DIR" && claude -p --dangerously-skip-permissions --output-format stream-json "$TASK"
```

### When to Use Programmatic Mode

- Cron-scheduled tasks (nightly code reviews, dependency updates)
- Script-driven pipelines (CI, OpenClaw agent dispatch)
- Any scenario where no human is watching the terminal
- Batch processing multiple tasks sequentially

### When NOT to Use Programmatic Mode

- Tasks requiring mid-course correction or human judgment
- Multi-turn exploration (use interactive mode)
- Tasks needing MCP tools that require interactive auth

---

## tmux Session Management (Human-Interactive Only)

> **Note:** The tmux scripts below (`cc-start.sh`, `cc-send.sh`, `cc-read.sh`) are designed for **human-interactive sessions** where a person is watching and typing. For programmatic/automated dispatch, use `claude -p` instead — see [Programmatic Dispatch](#programmatic-dispatch) above.

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

**Why `--bare`?** It skips loading MCP servers and CLAUDE.md, cutting startup from ~5s to <1s. Disable it (`--no-bare`) when the task needs MCP tools, project-specific instructions, or custom hooks.

**Never launch CC with raw `tmux new-session`** — always use `cc-start.sh` so the active session tracker stays in sync.

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

**Why `load-buffer` instead of `send-keys -l`?** `send-keys -l` breaks on quotes, `$`, backslashes, and text longer than ~500 chars. `load-buffer` writes to a temp file and pastes it, bypassing all terminal escaping issues.

### Reading Output

```bash
scripts/cc-read.sh                       # Auto-locate, last 50 lines
scripts/cc-read.sh --session cc-auth     # Specific session
scripts/cc-read.sh --lines 100           # Last 100 lines
scripts/cc-read.sh --full                # Full scrollback
scripts/cc-read.sh --status              # Just the status (idle/working/error)
```

### Stopping a Session

```bash
# Graceful: send /exit to CC (saves context for --resume)
scripts/cc-send.sh "/exit"

# Force: kill the tmux session
tmux kill-session -t cc-my-feature
```

### Resuming a Session

```bash
# Resume the most recent CC conversation in a new tmux session
scripts/cc-start.sh my-feature
scripts/cc-send.sh "--resume"
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

### Splitting Principles

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

> `git commit` → let Claude run → success: merge, failure: `git reset --hard`, start over.
>
> **Starting fresh beats trying to fix a derailed intermediate state.**

This works because Claude Code is stochastic — the same prompt can produce very different results. A fresh attempt often succeeds where debugging a bad attempt would take longer.

### Practical Example

```bash
# 1. Checkpoint before risky work
git add -A && git commit -m "checkpoint: before auth refactor"

# 2. Let CC work
scripts/cc-send.sh "Refactor the auth module to use JWT tokens"

# 3. If result is bad after 10+ minutes
git reset --hard HEAD
# Revise the prompt and try again
scripts/cc-send.sh "Refactor auth to JWT. Keep the existing session interface, only change the backend."
```

---

## Background One-Shot Mode

For simple, predictable single tasks:

```bash
# Run a self-contained task with no interaction
claude -p "Add type hints to all functions in src/utils.py"

# Inside OpenClaw agent context, unset CLAUDECODE to avoid nesting error
unset CLAUDECODE && claude --dangerously-skip-permissions -p "describe the task"
```

When to use:
- Task is < 2 minutes
- Output is predictable (formatting, type hints, simple generation)
- No mid-course correction needed

When NOT to use:
- Multi-file changes
- Tasks requiring exploration or iteration
- Anything that might need human judgment mid-way

---

## `/loop` Mode (Large Autonomous Tasks)

The `/loop` command tells Claude Code to iterate autonomously until a condition is met. **Always checkpoint before launching** (Slot Machine):

```bash
# 1. Checkpoint
git add -A && git commit -m "checkpoint: before loop"

# 2. Launch loop inside a CC session
scripts/cc-send.sh '/loop "Build the REST API for users CRUD. Run tests after each endpoint. Output DONE when all tests pass." --max-iterations 15'
```

- Success → merge
- Failure → `git reset --hard HEAD~1` + revise prompt + retry
- Cancel: `/loop stop`

---

## CLAUDE.md: Teaching CC Your Conventions

Every time CC makes a repeated mistake, add a rule to your project's `CLAUDE.md`. Over time it becomes a living rulebook that prevents recurring errors.

```markdown
# Tool conventions
- pytest: `pytest tests/ -v`, never `python -m pytest`
- Delete files: `mv` to trash dir, never `rm -rf`
- Bash failure → diagnose first, don't blindly retry
- Use absolute paths, avoid unnecessary `cd`
- Long text: use heredoc or write to file, not single-line commands
```

### CLAUDE.md Hierarchy

Claude Code loads `CLAUDE.md` files from multiple locations (highest priority last):

1. **`~/.claude/CLAUDE.md`** — Global defaults (your personal conventions)
2. **`<project-root>/CLAUDE.md`** — Project-level rules (shared with team via git)
3. **`<project-root>/<subdir>/CLAUDE.md`** — Directory-specific overrides

Use project-level for team standards. Use global for personal preferences.

---

## Two-Phase Workflow (Complex Tasks)

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
    echo "WARNING: CC process alive but tmux session lost — may need restart"
elif [ -n "$CC_SESSIONS" ] && [ -z "$CC_PROC" ]; then
    echo "WARNING: tmux session exists but CC process exited"
fi
```

---

## Hard Rules / Gotchas

- ⚠️ **tmux send-keys cannot reliably send messages to Claude Code** — Ink TUI's raw mode stdin handler intercepts characters sent via `tmux send-keys`. Programmatic dispatch **must** use `claude -p` one-shot mode.
  - **Root cause:** Ink (React for terminals) calls `setRawMode(true)` on stdin at mount time. In raw mode, tmux send-keys simulates keypresses that get consumed by Ink's internal keypress handler but are not forwarded to the Claude Code input prompt. This makes `send-keys` unreliable for automation — characters may be silently dropped or misinterpreted.
  - **Workaround for interactive sessions:** `cc-send.sh` uses `load-buffer` + `paste-buffer` instead of `send-keys -l`, which is more reliable for human-initiated sends. But even this approach is fragile for fully automated scenarios.
- ⚠️ **Do not `tmux send-keys` to start `/loop`** from a script — have a human start it interactively, or use `claude -p` with a self-contained prompt instead.

---

## Anti-Patterns

| Don't | Do instead |
|-------|-----------|
| Dump a 500-word requirement in one message | Split into progressive steps |
| Write code yourself, then ask CC to "fix it" | Delegate the full task to CC |
| Run multiple CC on the same repo | One instance per repo to avoid conflicts |
| Use background one-shot for complex tasks | Use interactive or `/loop` |
| Say "done" without verifying | Run tests, check screenshots, sample output |
| Try to fix CC's derailed intermediate state | `git reset --hard` and start over (Slot Machine) |
| Wait until CC finishes to evaluate | Interrupt early if going wrong |
| Manual `/clear` during compaction | Let auto-compact handle context management |
| Use raw `tmux new-session` | Always use `cc-start.sh` |
| Send next message before confirming delivery | Check with `cc-read.sh --status` first |
| Let CC read >10K char files at once | Split reads to avoid context overflow |
| Use `tmux send-keys` for automated dispatch | Use `claude -p` for programmatic/script dispatch |
| Pipe input to Claude Code's stdin in TUI mode | Use `claude -p` which reads stdin correctly |
