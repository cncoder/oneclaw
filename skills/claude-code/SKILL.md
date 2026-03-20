---
name: claude-code
description: "Use Claude Code as your autonomous coding agent. Covers task dispatch via tmux, debugging workflow, slot-machine recovery, and best practices for getting the most out of Claude Code via OpenClaw."
metadata:
  openclaw:
    emoji: "⚡"
    requires:
      bins: ["tmux", "claude"]
---

# Skill: claude-code

Claude Code is a full autonomous coding agent, not just a code generator. Treat it as a super-powered teammate.

---

## Mode Selection

| Scenario | Mode |
|----------|------|
| Multi-file changes, >5 min, need visibility | **Interactive** (default) |
| Single file, <2 min, predictable output | **Background one-shot** |
| Self-iterating feature development | **ralph-loop** |

**Classify first** (from Anthropic internal report):

| Type | Examples | Strategy |
|------|----------|----------|
| **Peripheral / async** | Prototypes, visualizations, test generation, refactoring, unfamiliar codebase | ralph-loop or auto-accept, let it run |
| **Core / sync** | Core business logic, security changes, config changes, multi-component coordination | Interactive mode, supervise in real-time |

---

## tmux Session Management (OpenClaw ↔ Claude Code)

Claude Code uses an **Ink TUI framework** — it's not a regular shell. OpenClaw dispatches and monitors Claude Code through tmux sessions.

### Architecture

Each CC task gets its own tmux session (`cc-{task}`), tracked via `/tmp/cc-active-tab`. Three scripts handle the lifecycle:

| Script | Purpose | Core mechanism |
|--------|---------|----------------|
| `cc-start.sh` | Create tmux session + launch CC | Writes `/tmp/cc-active-tab` |
| `cc-send.sh` | Send messages to the right session | 3-level fallback resolution |
| `cc-read.sh` | Read terminal output | `tmux capture-pane` |

### Starting a New CC Task

```bash
# Standard launch (uses current directory)
scripts/cc-start.sh daily-digest

# With specific working directory
scripts/cc-start.sh tts-fix ~/projects/my-app

# View / attach to session
tmux attach -t cc-daily-digest
tmux ls  # List all sessions
```

**❌ Never launch CC with raw `tmux new-session`** — always use `cc-start.sh` so the active tab tracker stays in sync.

### Sending Messages

```bash
# Auto-locate most recently launched CC session
scripts/cc-send.sh "your task instruction"

# Target a specific session (when multiple CC sessions exist)
scripts/cc-send.sh --session cc-daily "your task instruction"

# Multi-line via stdin
scripts/cc-send.sh <<'MSG'
Read src/main.py,
describe the data flow and key functions.
MSG
```

**Session resolution priority** (3-level fallback):
1. `--session <name>` → Exact tmux session name
2. `/tmp/cc-active-tab` → Most recently launched session (validated)
3. Last `cc-*` session found → Fallback

### Reading Terminal Output

```bash
scripts/cc-read.sh                       # Auto-locate, last 50 lines
scripts/cc-read.sh --session cc-daily    # Specific session
scripts/cc-read.sh --lines 100           # Last 100 lines
scripts/cc-read.sh --full                # Full scrollback
```

### Judging CC State

| Terminal shows | Status | Action |
|----------------|--------|--------|
| `>` empty prompt | Idle, ready for input | Send next sub-task |
| `Bootstrapping...` / `Cogitating...` | Context compaction | **Wait. Don't interrupt. Don't /clear.** |
| `Enter to confirm` | Waiting for permission | `tmux send-keys -t <session> Enter` |
| `Error` / `failed` | Something broke | Assess: interrupt and restart? |
| No change for 5+ min | Possibly stuck | Escalate to user |

### Heartbeat Integration

Monitor CC health in your OpenClaw heartbeat:

```bash
CC_SESSIONS=$(tmux ls -F '#{session_name}' 2>/dev/null | grep '^cc-' || true)
CC_PROC=$(pgrep -f "claude --danger" | head -1)

if [ -z "$CC_SESSIONS" ] && [ -z "$CC_PROC" ]; then
    echo "CC not running"
elif [ -z "$CC_SESSIONS" ] && [ -n "$CC_PROC" ]; then
    echo "⚠️ CC process alive but tmux session lost"
elif [ -n "$CC_SESSIONS" ] && [ -z "$CC_PROC" ]; then
    echo "⚠️ tmux session exists but CC process exited"
fi
```

---

## Interactive Mode

### Progressive Task Delivery (core workflow)

**Splitting rules:**
- Split by **dependency + verification checkpoints**
- Each sub-task has a **clear completion signal**
- Single sub-task < 30 min, touches no more than 3 files
- Separate core logic / edge features / refactoring

**Progressive flow:**

```
Step 1: Explore — "Read X file, describe the data structure / architecture"
  → Signal: structure description output
  → Check: correct understanding?

Step 2: Design — "Based on the above, propose a plan"
  → Signal: plan text
  → Check: plan makes sense? Human confirms.

Step 3: Small-batch verify — "Process 20 items / implement core function"
  → Signal: code/data is verifiable
  → Check: build + test + sample ← most critical checkpoint

Step 4: Full execution — "Process everything the verified way"
  → git commit checkpoint
  → Check: spot-check + overall verification

Step 5: Polish — "Review and fix issues"
  → Signal: no obvious issues
```

### Three-Layer Verification (per step)

| Layer | Method | Purpose |
|-------|--------|---------|
| Syntax | `build` / `compile` passes | No obvious errors |
| Logic | `test` / `lint` passes | Meets standards |
| Effect | Screenshot / logs / sample comparison | Actually meets expectations |

### Interrupt Signals (don't wait for completion)

| Signal | Action |
|--------|--------|
| Over-engineering (3+ nesting levels) | Interrupt: "try a simpler approach" |
| Same tool call fails 3 times | Interrupt, switch approach |
| Drifting from main goal, fixing side effects | Interrupt, refocus |
| Over 2x estimated time | **Slot Machine: git reset --hard and restart** |
| Output quality declining | Roll back to last checkpoint |

---

## Background One-Shot Mode

For simple, predictable single-shot tasks:

```bash
# If running inside OpenClaw agent environment, unset CLAUDECODE first
unset CLAUDECODE && claude --dangerously-skip-permissions -p "your task description"
```

**Notes:**
- Cannot course-correct mid-execution
- Must `unset CLAUDECODE` inside OpenClaw sessions (otherwise nesting error)
- Only for <2 min tasks with clear outcomes

---

## ralph-loop Mode (large autonomous tasks)

**Must checkpoint before starting** (Slot Machine protocol):

```bash
# 1. Force checkpoint
git add -A && git commit -m "checkpoint: before ralph-loop attempt"

# 2. Start ralph-loop
/ralph-loop "Build X. Output <promise>DONE</promise> when tests pass." --completion-promise "DONE" --max-iterations 15
```

- Success → merge
- Failure → `git reset --hard HEAD~1` + modify prompt + restart
- Cancel: `/cancel-ralph`

---

## Slot Machine Protocol

When task complexity is medium and success isn't guaranteed:

1. `git commit` to save checkpoint
2. Start ralph-loop (max-iterations=5)
3. Success → merge; Failure → `git reset --hard` + change prompt + restart
4. **Restarting has higher success rate than patching a drifted intermediate state**

---

## Systematic Debugging (never guess-fix)

When encountering bugs, test failures, or unexpected behavior — **no fixes without root cause investigation first**.

### Four Phases

1. **Root Cause**: Read full error → stable repro → check recent changes → add diagnostics at component boundaries
2. **Pattern**: Find working example in same codebase → compare every difference
3. **Hypothesis**: Explicit hypothesis ("X is root cause because Y") → minimal change test → change one variable at a time
4. **Fix**: Write failing test → single fix → verify → no side effects

**3-strike rule**: 3 consecutive fix failures = architectural issue, stop and discuss. Don't keep patching.

**Red flags (stop immediately, go back to Phase 1):**
- "Let me just change this and see if it works"
- "I don't fully understand but this might work"
- "Let me try again" (already tried 2+ times)
- Proposing a fix before tracing data flow

---

## Two-Phase Work Method (for complex tasks)

1. **Planning phase**: Brainstorm in conversation, generate structured prompt:
   ```markdown
   ## Goal
   [one sentence]
   ## Constraints
   - [limitations]
   ## Steps
   1. [specific, verifiable steps]
   ## Acceptance Criteria
   - [conditions verifiable by command]
   ```

2. **Execution phase**: Hand structured prompt to Claude Code

**Don't throw informal requirements directly at Claude Code** — plan first, execute second.

---

## Claude Code Capabilities (don't do these yourself)

| Capability | Description |
|------------|-------------|
| **Coding** | Any language — write/edit/debug/refactor/test |
| **Self-correction** | Auto-fixes build failures until passing |
| **Skill plugins** | TDD, code-review, security-review, E2E, frontend-design (50+ skills) |
| **Sub-agent teams** | researcher + coder + reviewer working in parallel |
| **Browser control** | chrome-devtools MCP (CDP) |
| **Doc queries** | context7 MCP (latest API docs) |

---

## Anti-Patterns (learned the hard way)

- ❌ Give 500-word requirement docs at once (split small)
- ❌ Write code yourself instead of delegating to Claude Code
- ❌ Run multiple Claude Code instances on the same repo
- ❌ Use background one-shot for complex tasks
- ❌ Claim "done" without verification evidence
- ❌ Try to fix Claude's drifted intermediate state (reset and restart)
- ❌ Wait until Claude finishes to evaluate (interrupt early if drifting)
- ❌ Manually `/clear` (let auto-compact handle context management)
- ❌ Send new messages while Claude Code is actively working (gets queued, causes confusion)
- ❌ Have Claude Code read files >10K chars at once (split into segments)

---

## CLAUDE.md Tool Correction Rules

When encountering repeated errors, add rules to the project's CLAUDE.md:

```markdown
# Tool usage rules
- pytest: `pytest tests/ -v`, don't `python -m pytest`, don't cd first
- Delete files: `mv ~/.Trash/`, never `rm`
- Bash failure → diagnose cause first, don't retry same command
- Don't cd unnecessarily — use absolute paths
- Long text: use heredoc or write to file, avoid ultra-long single-line commands
```
