---
name: hermes-health-audit
description: "Full-stack Hermes Agent health audit: observability config, compression tuning, prompt/skill consistency, skill invocation diagnosis, system overload detection, and session pattern analysis with subagent recommendations. Use when skills stop triggering, model ignores loaded skill steps, context grows unexpectedly, sessions hit compression too often, long tasks get interrupted, or after editing any prompt/skill/config file."
---

# Hermes Health Audit

6-phase diagnostic covering observability, compression, consistency, invocation, overload detection, and session behavior analysis.

## When to Use

- Skills stop triggering after extended conversation
- Model "laziness" — loads skill but ignores steps
- Context window grows unexpectedly or compression fires too early
- Long tasks keep getting interrupted by user messages
- After editing SOUL.md, skills, or config.yaml
- Periodic health check (monthly recommended)
- Onboarding a new teammate to Hermes

## Quick Start

Run all 6 phases. Each is independent — skip recently verified ones.

---

## Phase 1: Observability Config

Ensure diagnostic signals are visible before debugging anything else.

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

### Gateway vs CLI

- `agent.verbose: true` → **CLI mode only**
- Gateway hardcodes `verbose_logging=False` in `gateway/run.py`
- For gateway DEBUG: `hermes gateway run -vv`
- `runtime_footer` works in **both** modes
- Full payload dump: `HERMES_DUMP_REQUEST_STDOUT=1 hermes chat`

---

## Phase 2: Compression Tuning

Compression = #1 cause of "skill stops working after chatting".

### Root Cause Chain

1. `skill_view()` loads content as **tool result message** in history
2. Context hits threshold → compression summarizes old messages
3. `protect_last_n` determines how many recent messages survive
4. Skill loaded 30+ messages ago → summarized → steps lost
5. Model can't see instructions → "laziness"

### Recommended Config

```yaml
compression:
  enabled: true
  threshold: 0.75          # 75% of window (150K for 200K)
  target_ratio: 0.2        # compress to 20%
  protect_last_n: 40       # keep last 40 messages intact
  protect_first_n: 3       # preserve early context
  hygiene_hard_message_limit: 400
```

### Tuning Table

| Parameter | Conservative | Aggressive | Guidance |
|-----------|-------------|------------|----------|
| threshold | 0.6 | 0.8 | Higher = more room before compression |
| protect_last_n | 20 | 60 | Higher = skills survive longer |
| protect_first_n | 3 | 5 | Higher = early context preserved |

Free-tier (Bedrock/employee): threshold≥0.75, protect_last_n≥40. No reason to compress early.

### Verify

```bash
grep -A6 "^compression:" ~/.hermes/config.yaml
sqlite3 ~/.hermes/state.db "SELECT id, input_tokens, cache_read_tokens, message_count FROM sessions ORDER BY started_at DESC LIMIT 1;"
```

---

## Phase 3: Prompt Consistency Audit

### 3.1 System Prompt Inspection

```bash
sqlite3 ~/.hermes/state.db "SELECT system_prompt FROM sessions ORDER BY started_at DESC LIMIT 1;" > /tmp/current_system_prompt.txt
chars=$(wc -c < /tmp/current_system_prompt.txt)
echo "≈ $((chars / 4)) tokens ($(( chars * 100 / 800000 ))% of 200K)"
```

### 3.2 Conflict Detection Matrix

| Conflict Type | Detection | Impact |
|--------------|-----------|--------|
| Skill A vs Skill B | grep contradicting ALWAYS/NEVER on same topic | Random compliance |
| Skill vs SOUL.md | Compare style directives | Output oscillation |
| Skill internal | Steps that undo each other | Partial execution |
| Stale references | Skill mentions deleted skill | Wasted tool calls |
| Instruction saturation | 5+ loaded skills with imperatives | Attention dilution |

### 3.3 Automated Checks

```bash
# 1. Imperative density
grep -rn "ALWAYS\|NEVER\|MUST\|禁止\|必须" ~/.hermes/skills/*/SKILL.md | sort -t: -k3 | head -40

# 2. Cross-reference integrity (macOS compatible)
grep -rn "skill_view\|skill:" ~/.hermes/skills/*/SKILL.md | \
  grep -oE "skill_view\(name='[^']+'" | sed "s/skill_view(name='//;s/'//" | \
  sort -u > /tmp/referenced_skills.txt
ls ~/.hermes/skills/ > /tmp/existing_skills.txt
comm -23 <(sort /tmp/referenced_skills.txt) <(sort /tmp/existing_skills.txt)

# 3. Short descriptions (<50 chars)
for d in ~/.hermes/skills/*/SKILL.md; do
  desc=$(grep '^description:' "$d" | head -1 | sed 's/^description: *//;s/^"//;s/"$//')
  if [ ${#desc} -lt 50 ] && [ ${#desc} -gt 0 ]; then
    echo "SHORT(${#desc}): $(basename $(dirname $d))"
  fi
done

# 4. Oversized skills (>300 lines)
for d in ~/.hermes/skills/*/SKILL.md; do
  lines=$(wc -l < "$d")
  if [ $lines -gt 300 ]; then
    echo "LARGE($lines): $(basename $(dirname $d))"
  fi
done

# 5. SOUL.md vs skill style conflicts
grep -n "结论先行\|一句话\|简洁\|展开\|详细\|step-by-step" ~/.hermes/SOUL.md 2>/dev/null
grep -rn "输出格式\|output format\|详细\|step.by.step\|完整报告" ~/.hermes/skills/*/SKILL.md
```

### 3.4 Naming Quality

Per Anthropic best practices:
- **Name**: gerund form preferred, no "helper/util/tool/misc"
- **Description**: third person, WHAT + WHEN, 50-200 chars
- **Pushy triggers**: description should slightly over-claim

```bash
for d in ~/.hermes/skills/*/; do
  name=$(basename "$d")
  echo "$name" | grep -qiE "^(helper|util|tool|misc|common)$" && echo "VAGUE: $name"
  [ ${#name} -gt 40 ] && echo "TOO LONG(${#name}): $name"
done
```

---

## Phase 4: Skill Invocation Diagnosis

### 4.1 Verify Skill in Available List

```bash
grep "skill-name-here" /tmp/current_system_prompt.txt
```

Missing → malformed directory or bad YAML frontmatter.

### 4.2 Session JSON Load Events

```bash
cat $(ls -t ~/.hermes/sessions/session_*.json | head -1) | \
  python3 -c "import json,sys; d=json.load(sys.stdin); [print(m.get('content','')[:100]) for m in d.get('messages',[]) if 'skill_view' in str(m)]"
```

### 4.3 Failure Modes

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| Never triggers | Description too narrow | Rewrite with explicit trigger phrases |
| Loads but steps skipped | >500 lines | Split into SKILL.md + references/ |
| Works initially, fails later | Compression ate it | Increase protect_last_n or re-invoke |
| Wrong skill triggers | Overlapping descriptions | Add negative differentiation |
| Partially followed | Internal contradictions | Audit MUST/NEVER conflicts |

### 4.4 Re-injection Pattern

Add to SOUL.md for critical skills:

```
When executing a task relying on a previously-loaded skill and >20 messages
have passed since skill_view(), re-invoke skill_view() to refresh content.
```

---

## Phase 5: Overload Detection

Detect when the system is carrying too much cognitive load.

### 5.1 Skill Overload

```bash
# Total skill count
skill_count=$(ls -d ~/.hermes/skills/*/ 2>/dev/null | wc -l)
echo "Skills on disk: $skill_count"

# Total lines across all SKILL.md
total_lines=$(cat ~/.hermes/skills/*/SKILL.md 2>/dev/null | wc -l)
echo "Total skill lines: $total_lines"

# Available_skills section size in system prompt
avail_chars=$(grep -A9999 'available_skills' /tmp/current_system_prompt.txt | wc -c)
echo "available_skills section: $avail_chars chars ≈ $((avail_chars/4)) tokens"
```

**Thresholds:**

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Skills on disk | <40 | 40-70 | >70 |
| Total SKILL.md lines | <8000 | 8000-15000 | >15000 |
| available_skills in prompt | <5000 chars | 5000-15000 | >15000 |
| System prompt total | <20K chars | 20-30K | >30K |

### 5.2 System Prompt Overload

```bash
# Full system prompt size
sys_chars=$(sqlite3 ~/.hermes/state.db "SELECT length(system_prompt) FROM sessions ORDER BY started_at DESC LIMIT 1;")
echo "System prompt: $sys_chars chars ≈ $((sys_chars/4)) tokens"

# Break down: SOUL.md + Memory + User Profile + Skills list
# Each contributes to attention competition
sqlite3 ~/.hermes/state.db "SELECT system_prompt FROM sessions ORDER BY started_at DESC LIMIT 1;" | \
  awk '
    /^══.*MEMORY/{section="memory"; next}
    /^══.*USER PROFILE/{section="user"; next}
    /^<available_skills>/{section="skills"; next}
    /^<\/available_skills>/{section=""; next}
    {lens[section]+=length($0)+1}
    END{for(s in lens) if(s!="") printf "%s: %d chars\n", s, lens[s]}
  '
```

**Impact of overload:**
- >30K system prompt → model attention spreads thin across instructions
- >70 skills in available_skills → description matching accuracy degrades
- Multiple MUST/NEVER directives competing → model picks randomly

### 5.3 SOUL.md Complexity

```bash
# SOUL.md section count and directive density
soul_lines=$(grep -c "" ~/.hermes/SOUL.md 2>/dev/null || echo 0)
soul_directives=$(grep -ciE "MUST|NEVER|ALWAYS|禁止|必须|铁律" ~/.hermes/SOUL.md 2>/dev/null || echo 0)
echo "SOUL.md: $soul_lines lines, $soul_directives hard directives"
```

**Thresholds:**

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| SOUL.md lines | <150 | 150-300 | >300 |
| Hard directives | <20 | 20-40 | >40 |
| Directive density | <10% | 10-20% | >20% |

High directive density = model gets "instruction fatigue" — starts ignoring rules.

---

## Phase 6: Session Pattern Analysis

Analyze usage history to identify structural issues and recommend subagent delegation.

### 6.1 Session Statistics

```bash
# Overall stats
sqlite3 ~/.hermes/state.db "
SELECT
  count(*) as total_sessions,
  avg(message_count) as avg_messages,
  avg(tool_call_count) as avg_tools,
  max(message_count) as max_messages
FROM sessions WHERE source='feishu' AND message_count > 5;"

# End reason distribution
sqlite3 ~/.hermes/state.db "
SELECT end_reason, count(*) as cnt, avg(message_count) as avg_msgs, avg(tool_call_count) as avg_tools
FROM sessions WHERE source='feishu' AND message_count > 5
GROUP BY end_reason ORDER BY cnt DESC;"

# Compression frequency
sqlite3 ~/.hermes/state.db "
SELECT count(*) as compression_sessions,
  (SELECT count(*) FROM sessions WHERE source='feishu' AND message_count > 5) as total
FROM sessions WHERE source='feishu' AND end_reason='compression';"
```

### 6.2 Tool Density Analysis

```bash
# High-density sessions (tool_calls/messages > 0.8 = heavy automation)
sqlite3 ~/.hermes/state.db "
SELECT id, message_count, tool_call_count,
  round(cast(tool_call_count as real)/message_count, 2) as tool_density
FROM sessions WHERE source='feishu' AND message_count > 20
ORDER BY tool_density DESC LIMIT 10;"
```

**Interpretation:**
- tool_density > 0.8 → session is mostly automation (good candidate for subagent)
- tool_density < 0.3 → mostly conversation (no delegation needed)
- Sessions that hit compression with high tool density → subagent would have prevented compression

### 6.3 Interruption Pattern Detection

The #1 issue: user sends message while agent is executing multi-tool chain → current turn killed.

```bash
# Sessions with many messages but relatively few tool calls = frequent interruptions
sqlite3 ~/.hermes/state.db "
SELECT id, message_count, tool_call_count,
  round(cast(tool_call_count as real)/message_count*2, 2) as efficiency
FROM sessions WHERE source='feishu' AND message_count > 50
  AND cast(tool_call_count as real)/message_count < 0.4
ORDER BY message_count DESC LIMIT 10;"
```

Low efficiency ratio = many turns were interrupted before tools completed.

### 6.4 Recommended Subagent Profiles

Based on common session patterns, these subagent types prevent interruption:

| Profile | Trigger Condition | Toolsets | Typical Duration |
|---------|------------------|----------|-----------------|
| **Auditor** | "审计/扫描/检查" + >5 targets | terminal, file | 30-120s |
| **Researcher** | "调研/对比/分析" + open-ended | web, browser, terminal | 60-300s |
| **Builder** | "写/创建/生成" + multi-file output | terminal, file | 30-180s |
| **Deployer** | "部署/发布/推送" + infra changes | terminal, file | 60-300s |

### 6.5 Auto-Delegation Rules

Add to SOUL.md to enable automatic subagent dispatch:

```markdown
## Auto-Delegation Strategy

Automatically use delegate_task (not inline execution) when ALL of:
1. Task requires 5+ sequential tool calls with no user decision points
2. Task is one of: audit/scan, research/compare, batch process, deploy
3. User said "跑一下/帮我搞/全部做完" (execution intent, not discussion)

When delegating:
- Pass complete context (file paths, constraints, output location)
- Use toolsets: ["terminal", "file"] for most tasks, add "web" for research
- Write output to /tmp/ or specific path, then read back and summarize
- If task might take >60s, tell user "已派 subagent，继续聊不会打断它"
```

### 6.6 Compression Prevention via Delegation

Key insight: subagent results return as a **single compact summary** instead of 10+ intermediate tool results. This dramatically reduces context growth.

| Approach | Context cost | Interruption risk |
|----------|-------------|-------------------|
| Inline 10 tool calls | ~10 messages added | High (any user msg kills it) |
| delegate_task | 1 summary message | Zero (subagent isolated) |

**Rule of thumb**: Any task that would add >5 messages to context → delegate instead.

---

## Output Format

```
# Hermes Health Report — [date]

## Phase 1 Observability: ✅/⚠️/❌
- runtime_footer: [enabled/disabled]
- show_cost: [yes/no]
- tool_progress: [yes/no]

## Phase 2 Compression: ✅/⚠️/❌
- threshold: [value] (recommended: ≥0.75 for free-tier)
- protect_last_n: [value] (recommended: ≥40)
- current context: [X]% of [Y]K window

## Phase 3 Consistency: ✅/⚠️/❌
- Contradictions found: [N]
- Broken references: [N]
- Oversized skills (>300 lines): [N]
- Vague descriptions: [N]

## Phase 4 Invocation: ✅/⚠️/❌
- Skills in prompt: [N]/[total on disk]
- Naming issues: [N]

## Phase 5 Overload: ✅/⚠️/❌
- Skills count: [N] (threshold: 70)
- System prompt: [N] chars (threshold: 30K)
- SOUL.md directives: [N] (threshold: 40)
- Directive density: [N]% (threshold: 20%)

## Phase 6 Session Patterns: ✅/⚠️/❌
- Avg session length: [N] messages
- Compression rate: [N]% of sessions
- Avg tool density: [N]
- Recommended auto-delegate tasks: [list]

## Actions Taken
- [what was fixed]

## Remaining Issues
- [what needs manual decision]
```

---

## Scheduling

```bash
# Monthly auto-audit with report to feishu
hermes cron create --schedule "0 10 1 * *" \
  --prompt "Load hermes-health-audit skill, run all 6 phases, output report" \
  --skills hermes-health-audit
```
