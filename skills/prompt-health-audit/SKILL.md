---
name: prompt-health-audit
description: "Audit Hermes Agent prompt health: detect logic conflicts between SOUL.md/skills/system-prompt, verify observability config (runtime_footer, verbose, show_cost), tune compression for skill retention, and diagnose skill invocation failures. Use when skills stop triggering, model ignores loaded skill steps, context grows unexpectedly, or after editing any prompt/skill/config file."
---

# Prompt Health Audit

Full-stack diagnostic for Hermes Agent prompt health — covers logic consistency, observability, compression tuning, and skill invocation debugging.

## When to Use

- Skills stop triggering after extended conversation
- Model "laziness" — loads skill but ignores steps
- Context window grows unexpectedly or compression fires too early
- After editing SOUL.md, skills, or config.yaml
- Periodic health check (monthly recommended)
- Helping teammates diagnose their Hermes setup

## Quick Start

Run the 4-phase audit in order. Each phase is independent — skip phases you've recently verified.

---

## Phase 1: Observability Config

Ensure all diagnostic signals are visible before debugging anything else.

### Required Config (`~/.hermes/config.yaml`)

```yaml
display:
  tool_progress_command: true    # show tool calls in real-time
  show_cost: true                # show token spend per turn
  runtime_footer:
    enabled: true
    fields: [model, context_pct, tokens, cost, cwd]
```

### Verify

```bash
grep -A8 "runtime_footer:" ~/.hermes/config.yaml
grep "show_cost:" ~/.hermes/config.yaml
grep "tool_progress_command:" ~/.hermes/config.yaml
```

### Key Insight: Gateway vs CLI

- `agent.verbose: true` only works in **CLI mode**
- Gateway mode hardcodes `verbose_logging=False` (check `gateway/run.py`)
- For gateway DEBUG logs: restart with `hermes gateway run -vv`
- `runtime_footer` works in **both** modes — it appends metadata to final message
- Feishu/Discord/Telegram all render the footer as trailing text

### Env Var for Full Payload Dump

```bash
HERMES_DUMP_REQUEST_STDOUT=1 hermes chat
```

Dumps complete API request (system prompt + tools + messages) to stdout. Use for one-off deep inspection.

---

## Phase 2: Compression Tuning

Compression is the #1 cause of "skill stops working after chatting".

### Root Cause

1. `skill_view()` loads skill content as a **tool result message** in conversation history
2. When context hits threshold → compression summarizes old messages
3. `protect_last_n` determines how many recent messages survive intact
4. Skill content loaded 30+ messages ago gets summarized → detailed steps lost
5. Model can no longer see exact instructions → "laziness"

### Recommended Config (for large-context models like Opus)

```yaml
compression:
  enabled: true
  threshold: 0.75          # trigger at 75% (150K for 200K window)
  target_ratio: 0.2        # compress down to 20% of current
  protect_last_n: 40       # keep last 40 messages intact
  protect_first_n: 3       # keep first 3 messages (system context)
  hygiene_hard_message_limit: 400
```

### Tuning Logic

| Parameter | Conservative | Aggressive | When to Use |
|-----------|-------------|------------|-------------|
| threshold | 0.6 | 0.8 | Higher = more context before compression fires |
| protect_last_n | 20 | 60 | Higher = skills survive longer in conversation |
| protect_first_n | 3 | 5 | Higher = early context preserved |

### Cost-Free Environments (Bedrock/employee)

Set threshold=0.75+ and protect_last_n=40+. No reason to compress early when tokens are free.

### Verify Current State

```bash
# Check compression config
grep -A6 "^compression:" ~/.hermes/config.yaml

# Check current session token usage from SQLite
sqlite3 ~/.hermes/state.db "SELECT session_id, input_tokens, cache_read_tokens, message_count FROM sessions ORDER BY updated_at DESC LIMIT 1;"
```

---

## Phase 3: Prompt Consistency Audit

Detect logic conflicts that confuse the model.

### 3.1 System Prompt Inspection

```bash
# Export current system prompt from active session
sqlite3 ~/.hermes/state.db "SELECT system_prompt FROM sessions ORDER BY updated_at DESC LIMIT 1;" > /tmp/current_system_prompt.txt
wc -c /tmp/current_system_prompt.txt  # size in chars
```

Break down by section:

```bash
# Approximate token cost of system prompt
chars=$(wc -c < /tmp/current_system_prompt.txt)
echo "≈ $((chars / 4)) tokens ($(( chars * 100 / 800000 ))% of 200K)"
```

### 3.2 Conflict Detection Matrix

| Conflict Type | Detection Method | Impact |
|--------------|-----------------|--------|
| Skill A vs Skill B | grep contradicting verbs (ALWAYS vs NEVER on same topic) | Model picks randomly |
| Skill vs SOUL.md | Compare output format / communication style directives | Style oscillation |
| Skill internal contradiction | Steps that undo each other within same file | Partial execution |
| Stale cross-references | Skill references deleted/renamed skill | Wasted tool calls |
| Instruction saturation | 5+ loaded skills with imperative directives | Attention dilution |

### 3.3 Automated Checks

```bash
# 1. Find contradictions — ALWAYS/NEVER/MUST on same topics across skills
grep -rn "ALWAYS\|NEVER\|MUST\|禁止\|必须" ~/.hermes/skills/*/SKILL.md | \
  sort -t: -k3 | head -40

# 2. Cross-reference integrity — skills referencing other skills
grep -rn "skill_view\|skill:" ~/.hermes/skills/*/SKILL.md | \
  grep -oP "(?<=skill_view\(name=')[^']+|(?<=skill:)\s*\S+" | \
  sort -u > /tmp/referenced_skills.txt
ls ~/.hermes/skills/ > /tmp/existing_skills.txt
comm -23 <(sort /tmp/referenced_skills.txt) <(sort /tmp/existing_skills.txt)
# Output = broken references

# 3. Description quality — too short or too vague
for d in ~/.hermes/skills/*/SKILL.md; do
  desc=$(grep -A1 "^description:" "$d" | tail -1)
  chars=${#desc}
  if [ $chars -lt 50 ]; then
    echo "SHORT: $d ($chars chars)"
  fi
done

# 4. Oversized skills (>300 lines = attention risk)
for d in ~/.hermes/skills/*/SKILL.md; do
  lines=$(wc -l < "$d")
  if [ $lines -gt 300 ]; then
    echo "LARGE: $d ($lines lines)"
  fi
done

# 5. SOUL.md vs skill style conflicts
# Extract communication directives from SOUL.md
grep -n "结论先行\|一句话\|简洁\|展开\|详细\|step-by-step\|完整" ~/.hermes/SOUL.md 2>/dev/null
# Compare with skill output format requirements
grep -rn "输出格式\|output format\|详细\|step.by.step\|完整报告" ~/.hermes/skills/*/SKILL.md
```

### 3.4 Naming & Description Quality

Per Anthropic best practices:

- **Name**: gerund form preferred ("Processing PDFs" not "pdf-helper")
- **Description**: third person, includes WHAT + WHEN, 50-200 chars
- **No vague names**: "helper", "utils", "tools" are anti-patterns
- **Pushy triggers**: description should slightly over-claim when to activate

```bash
# Flag problematic names
for d in ~/.hermes/skills/*/; do
  name=$(basename "$d")
  if echo "$name" | grep -qiE "^(helper|util|tool|misc|common)"; then
    echo "VAGUE NAME: $name"
  fi
  if [ ${#name} -gt 40 ]; then
    echo "TOO LONG: $name (${#name} chars)"
  fi
done
```

---

## Phase 4: Skill Invocation Diagnosis

When a specific skill isn't triggering or is being ignored.

### 4.1 Check if Skill is in Available List

```bash
# Verify skill appears in system prompt's <available_skills> section
grep "skill-name-here" /tmp/current_system_prompt.txt
```

If missing → skill directory may be malformed (no SKILL.md or bad frontmatter).

### 4.2 Check Session JSON for Load Events

```bash
# Find latest session file
ls -t ~/.hermes/sessions/session_*.json | head -1

# Check if skill_view was called
cat $(ls -t ~/.hermes/sessions/session_*.json | head -1) | \
  python3 -c "import json,sys; d=json.load(sys.stdin); [print(m.get('content','')[:100]) for m in d.get('messages',[]) if 'skill_view' in str(m)]"
```

### 4.3 Common Failure Modes

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| Skill never triggers | Description too narrow / vague | Rewrite description with explicit trigger phrases |
| Skill loads but steps skipped | Skill too long (>500 lines) | Split into SKILL.md + references/ |
| Skill works initially, fails later | Compression ate the tool result | Increase protect_last_n or re-invoke skill_view |
| Wrong skill triggers | Overlapping descriptions | Differentiate with negative examples in description |
| Skill partially followed | Internal contradictions | Audit for conflicting MUST/NEVER directives |

### 4.4 The Re-injection Pattern

For critical skills in long sessions, add this to SOUL.md or skill guidance:

```
When executing a task that relies on a previously-loaded skill and more than
20 messages have passed since skill_view() was called, re-invoke skill_view()
to refresh the skill content into recent context.
```

---

## Output Format

After running all phases, produce a report:

```
# Prompt Health Report — [date]

## Observability: ✅/⚠️
- runtime_footer: [enabled/disabled]
- show_cost: [yes/no]
- tool_progress: [yes/no]

## Compression: ✅/⚠️
- threshold: [value] (recommended: ≥0.75 for free-tier)
- protect_last_n: [value] (recommended: ≥40)
- current context: [X]% of [Y]K window

## Consistency: ✅/⚠️
- Contradictions found: [N]
- Broken references: [N]
- Oversized skills (>300 lines): [N]
- Vague descriptions: [N]

## Skill Health: ✅/⚠️
- Skills in available_list: [N]/[total]
- Recently compressed skill_view results: [N]
- Recommended re-injections: [list]

## Actions Taken
- [what was fixed]

## Remaining Issues
- [what needs manual decision]
```

---

## Scheduling

Run as monthly cron or after any config/skill edit:

```bash
# Example: monthly audit reminder
hermes cron create --schedule "0 10 1 * *" --prompt "Run prompt-health-audit skill, output report to feishu"
```
