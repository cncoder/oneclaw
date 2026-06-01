---
name: hermes-health-audit
description: "Full-stack Hermes Agent health audit: observability config, compression tuning, prompt/skill consistency, skill invocation diagnosis, system overload detection, and session pattern analysis with subagent recommendations. Use when skills stop triggering, model ignores loaded skill steps, context grows unexpectedly, sessions hit compression too often, long tasks get interrupted, or after editing any prompt/skill/config file."
---

# Hermes Health Audit

**Target: Hermes Agent (本地源码: ~/.hermes/hermes-agent/)**
本 skill 专门审计和优化 Hermes Agent 的配置、行为和性能。所有路径、配置项、数据库 schema 均指 Hermes Agent，不涉及 Claude Code、OpenClaw 或其他 agent 框架。

**执行环境要求：**
- 本 skill 应由 Hermes Agent 自身执行（或由了解 Hermes 目录结构的 agent 执行）
- 所有 `~/.hermes/` 路径指向 Hermes Agent 的数据目录
- SQLite 查询针对 `~/.hermes/state.db`（Hermes 的 session 存储）
- 配置修改仅影响 `~/.hermes/config.yaml`（Hermes 的配置文件）
- **绝不修改** Claude Code (`~/.claude/`)、OpenClaw (`~/.openclaw/`) 或其他 agent 的配置

**后端：** AWS Bedrock Claude (us.anthropic.claude-opus-4-6-v1)，1M context window，免费无限量。所有优化方案以质量最优为目标，忽略成本。

6-phase diagnostic covering observability, compression, consistency, invocation, overload detection, and session behavior analysis.

## When to Use

- Skills stop triggering after extended conversation
- Model "laziness" — loads skill but ignores steps
- Context window grows unexpectedly or compression fires too early
- Long tasks keep getting interrupted by user messages
- After editing SOUL.md, skills, or config.yaml
- Periodic health check (monthly recommended)
- Onboarding a new teammate to Hermes
- 其他 agent (Claude Code / OpenClaw) 需要对 Hermes 做优化时，作为 reference spec 使用

## Quick Start

Run all 6 phases. Each is independent — skip recently verified ones.

---

## Phase 1: Observability Config

Ensure diagnostic signals are visible before debugging anything else.

### Required Config (`~/.hermes/config.yaml`)

```yaml
display:
  tool_progress_command: true    # show tool calls in real-time
  show_cost: true                # show token spend per turn (CLI mode only)
  busy_input_mode: "queue"       # interrupt | queue | steer
    # interrupt(默认): 用户消息立即杀当前 turn
    # queue: 消息排队，当前 turn 完成后处理（推荐自动化重度用户）
    # steer: 新消息作为方向调整注入当前 turn
  runtime_footer:
    enabled: true
    fields: [model, context_pct, cwd]  # ONLY these 3 fields are valid
    # ⚠️ tokens/cost/etc are silently ignored — not implemented in runtime_footer.py
```

### Verify

```bash
grep -A8 "runtime_footer:" ~/.hermes/config.yaml
grep "show_cost:" ~/.hermes/config.yaml
grep "tool_progress_command:" ~/.hermes/config.yaml
grep "busy_input_mode:" ~/.hermes/config.yaml

# Validate runtime_footer fields (only model/context_pct/cwd are valid)
VALID_FIELDS="model context_pct cwd"
CONFIGURED=$(grep -A5 "runtime_footer:" ~/.hermes/config.yaml | grep "fields:" | grep -oE '\[.*\]')
for field in $(echo "$CONFIGURED" | tr -d '[],' ); do
  if ! echo "$VALID_FIELDS" | grep -qw "$field"; then
    echo "⚠️  Invalid runtime_footer field: '$field' (silently ignored)"
  fi
done

# Check critical agent settings
grep "gateway_auto_continue_freshness" ~/.hermes/config.yaml
grep -A8 "tool_loop_guardrails:" ~/.hermes/config.yaml
```

### Key Agent Settings (often missing from default config)

```yaml
agent:
  max_turns: 90
  gateway_auto_continue_freshness: 3600  # 中断后 1h 内自动恢复上下文

tool_loop_guardrails:
  warnings_enabled: true
  hard_stop_enabled: true     # 防 agent 死循环（生产环境建议 true）
  warn_after:
    exact_failure: 2
    same_tool_failure: 3
    idempotent_no_progress: 2
  hard_stop_after:
    exact_failure: 5
    same_tool_failure: 8
    idempotent_no_progress: 5
```

### Gateway vs CLI

- Verbose 通过 CLI flag: `hermes chat -v` 或 `hermes gateway run -v`（不是 config.yaml 字段）
- Gateway hardcodes `verbose_logging=False` in `gateway/run.py`
- `runtime_footer` works in **both** modes

### 查看完整 Prompt / Context（Debug 必备）

**方法 1：HERMES_DUMP_REQUESTS=1 — 每次 API 调用写完整 request 到文件**

```bash
HERMES_DUMP_REQUESTS=1 hermes gateway run
```

输出位置：`~/.hermes/sessions/request_dump_<session>_<timestamp>.json`

文件内容结构：
```json
{
  "timestamp": "...",
  "session_id": "...",
  "reason": "preflight | non_retryable_client_error | max_retries_exhausted",
  "request": {
    "method": "POST",
    "url": "...",
    "body": {
      "model": "us.anthropic.claude-opus-4-6-v1",
      "system": "（完整 system prompt：SOUL.md + memory + skills index）",
      "messages": [{"role":"user","content":"..."},  ...],
      "tools": [...],
      "max_tokens": 128000,
      "thinking": {...}
    }
  }
}
```

**方法 2：HERMES_DUMP_REQUEST_STDOUT=1 — 直接打到终端**

```bash
HERMES_DUMP_REQUEST_STDOUT=1 hermes chat 2>&1 | tee /tmp/hermes_dump.json
```

适合一次性调试，输出巨大建议 pipe 到文件。

**方法 3：事后分析已有 dump**

```bash
# 列出所有 dump 文件
ls -lt ~/.hermes/sessions/request_dump_*.json | head -5

# 解析最新一条的 context 大小
python3 -c "
import json, sys, glob
files = sorted(glob.glob('/Users/abel/.hermes/sessions/request_dump_*.json'))
if not files: sys.exit('No dumps found')
d = json.load(open(files[-1]))
body = json.loads(d['request']['body']) if isinstance(d['request']['body'], str) else d['request']['body']
sys_len = len(str(body.get('system', '')))
msgs = body.get('messages', [])
msg_chars = sum(len(str(m.get('content',''))) for m in msgs)
tools_chars = len(json.dumps(body.get('tools', [])))
print(f'System prompt: {sys_len:,} chars (~{sys_len//4:,} tokens)')
print(f'Messages ({len(msgs)}): {msg_chars:,} chars (~{msg_chars//4:,} tokens)')
print(f'Tools definition: {tools_chars:,} chars (~{tools_chars//4:,} tokens)')
print(f'Total payload: ~{(sys_len+msg_chars+tools_chars)//4:,} tokens')
print(f'Model: {body.get(\"model\")}')
print(f'Max tokens: {body.get(\"max_tokens\")}')
"
```

**注意事项：**
- `runtime_footer` 的 `fields` 仅支持 `model`、`context_pct`、`cwd` 三个值，其他字段 silently ignored
- `context_pct` 显示当前 token 占 context window 的百分比（实时）
- 要看绝对 token 数必须用 dump request 方式
- Dump 文件会累积，定期清理：`rm ~/.hermes/sessions/request_dump_*.json`

---

## Phase 2: Compression Tuning

Compression = #1 cause of "skill stops working after chatting".

### Root Cause Chain

1. `skill_view()` 在对话中被模型调用时，内容作为 **tool result message** 进入 history（可被压缩）
   - 预加载 (`-s` flag) 的 skill 走 system prompt（永不压缩）
   - `/skill-name` 斜杠命令作为 user message 注入
2. Context hits threshold → compression summarizes old messages
3. `protect_last_n` determines how many recent messages survive
4. Skill loaded 30+ messages ago → summarized → steps lost
5. Model can't see instructions → "laziness"

### Recommended Config

```yaml
compression:
  enabled: true
  threshold: 0.75          # 75% of window (750K for 1M)
  target_ratio: 0.2        # compress to 20%
  protect_last_n: 40       # keep last 40 messages intact
  # protect_first_n: 硬编码=3，不可通过 config 配置
  hygiene_hard_message_limit: 400
```

**Auxiliary compression model:**
```yaml
auxiliary:
  compression:
    provider: bedrock
    model: us.anthropic.claude-opus-4-6-v1  # Abel: 免费无限量，用 Opus 保质量
    # 如果有成本约束的用户，可降级 Sonnet — 压缩摘要质量轻微下降但够用
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
# Tool density = tool_calls / message_count
# NOTE: message_count includes BOTH user AND assistant messages
# So density 0.45 means ~0.9 tools per agent turn (healthy high-automation)
sqlite3 ~/.hermes/state.db "
SELECT id, message_count, tool_call_count,
  round(cast(tool_call_count as real)/message_count, 2) as density,
  round(cast(tool_call_count as real)/(message_count/2.0), 2) as tools_per_turn
FROM sessions WHERE source='feishu' AND message_count > 20
ORDER BY tools_per_turn DESC LIMIT 10;"

# Density distribution (classify interruption patterns)
sqlite3 ~/.hermes/state.db "
SELECT
  CASE
    WHEN cast(tool_call_count as real)/message_count < 0.3 THEN 'very_low (<0.3) = frequent interrupts'
    WHEN cast(tool_call_count as real)/message_count < 0.5 THEN 'normal (0.3-0.5) = standard usage'
    WHEN cast(tool_call_count as real)/message_count >= 0.5 THEN 'high (>0.5) = deep automation'
  END as category,
  count(*) as sessions,
  round(avg(message_count)) as avg_msgs
FROM sessions WHERE source='feishu' AND message_count > 10
GROUP BY category ORDER BY sessions DESC;"
```

**Interpretation (corrected for dual-count):**
- `tools_per_turn` ≈ 0.85-1.0 → every agent response uses a tool (normal for power users)
- `tools_per_turn` < 0.5 → many turns without tools = user sending messages faster than agent can execute
- `density` 0.4-0.5 is the healthy baseline (NOT 0.8 — that would mean 1.6 tools per turn)

### 6.3 Interruption Pattern Detection

User sends message while agent executes multi-tool chain → current turn killed.

```bash
# Compression timing analysis: when does compression typically fire?
sqlite3 ~/.hermes/state.db "
SELECT
  min(message_count) as earliest,
  round(avg(message_count)) as avg_point,
  max(message_count) as latest
FROM sessions WHERE source='feishu' AND end_reason='compression';"

# Sessions with very low tool density = frequent interruptions
sqlite3 ~/.hermes/state.db "
SELECT id, message_count, tool_call_count,
  round(cast(tool_call_count as real)/(message_count/2.0), 2) as tools_per_turn
FROM sessions WHERE source='feishu' AND message_count > 30
  AND cast(tool_call_count as real)/message_count < 0.3
ORDER BY message_count DESC LIMIT 10;"

# Check delegate_task usage in session JSONs
ls -t ~/.hermes/sessions/session_*.json | head -20 | while read f; do
  if grep -ql "delegate_task" "$f" 2>/dev/null; then
    echo "HAS_DELEGATE: $(basename $f)"
  fi
done
```

**Benchmark (from real data, Abel's 100+ feishu sessions):**

| Metric | Actual Value | Meaning |
|--------|-------------|---------|
| Avg session length | 72 messages | ~36 turns |
| Compression fires at | avg 107 messages (old 0.6 threshold) | ~54 turns |
| Tool density | 0.43-0.50 (= 0.85-1.0 tools/turn) | High automation |
| Compression rate | 39% of sessions | Expected for power users |
| Sessions with delegate_task | ~4 recent | Adoption just starting |

**Prediction with new config (threshold=0.75, protect_last_n=40):**
- Compression should fire ~30% later (at ~140 messages instead of 107)
- Skills loaded within last 40 messages now survive compression
- Monitor after 2 weeks to validate

### 6.4 Cache Hit Ratio (Prompt Caching Health)

```bash
# Cache hit ratio = cache_read_tokens / (input_tokens + cache_read_tokens)
# High ratio (>90%) = prompt caching working well, low marginal cost
sqlite3 ~/.hermes/state.db "
SELECT
  round(sum(cache_read_tokens) * 100.0 / (sum(input_tokens) + sum(cache_read_tokens)), 1) as cache_hit_pct,
  sum(input_tokens) as total_input,
  sum(cache_read_tokens) as total_cache_read
FROM sessions WHERE source='feishu' AND message_count > 5;"

# Per-session cache efficiency (recent 10)
sqlite3 ~/.hermes/state.db "
SELECT id,
  round(cache_read_tokens * 100.0 / nullif(input_tokens + cache_read_tokens, 0), 1) as cache_pct,
  input_tokens, cache_read_tokens
FROM sessions WHERE source='feishu' AND message_count > 10
ORDER BY started_at DESC LIMIT 10;"
```

**Interpretation:**
- Cache hit >95% → excellent (system prompt + early messages fully cached)
- Cache hit 80-95% → normal (some cache misses on long sessions)
- Cache hit <80% → investigate (config changes invalidating cache, or model switching mid-session)
- Abel's baseline: >99% cache hit (system prompt dominates repeated calls)

### 6.5 Long Task & Interrupt Strategy

- `busy_input_mode: "queue"` — 根本性解决中断问题（消息排队而非杀 turn）
- `gateway_auto_continue_freshness: 3600` — 被中断后 1h 内自动注入恢复 system note
- Recurring 长任务 → cronjob（独立 session，完全隔离）
- 一次性长任务 → delegate_task（不防中断，但已写入文件不丢 + context 膨胀可控）

---

## Phase 7: Skill Usage Analysis & Pruning

Unused skills waste tokens in `available_skills` index (system prompt overhead).

### 7.1 Skill Load Frequency

```bash
# Scan last 100 session JSONs for skill_view tool calls
python3 -c "
import json, glob, os, re
from collections import Counter

skill_loads = Counter()
files = sorted(glob.glob(os.path.expanduser('~/.hermes/sessions/session_*.json')), key=os.path.getmtime, reverse=True)[:100]

for f in files:
    try:
        d = json.load(open(f))
        content = json.dumps(d.get('messages', []))
        # Match skill_view tool_use blocks
        for m in re.finditer(r'skill_view.*?\"name\":\s*\"([^\"]+)\"', content):
            name = m.group(1)
            if name not in ('skill_view', 'skills_list', 'skill_manage'):
                skill_loads[name] += 1
    except: pass

all_skills = set(os.path.basename(d.rstrip('/')) for d in glob.glob(os.path.expanduser('~/.hermes/skills/*/')))
never = sorted(all_skills - set(skill_loads.keys()))

print('=== Top loaded skills ===')
for s, c in skill_loads.most_common(20):
    print(f'  {c:3d}x  {s}')

print(f'\n=== Never loaded ({len(never)}/{len(all_skills)} local skills) ===')
for s in never:
    path = os.path.expanduser(f'~/.hermes/skills/{s}/SKILL.md')
    lines = len(open(path).readlines()) if os.path.exists(path) else 0
    print(f'  {s} ({lines} lines)')
"
```

### 7.2 Pruning Criteria

| Condition | Action |
|-----------|--------|
| Never loaded in 100+ sessions AND >100 lines | 🔴 Strong candidate for removal |
| Never loaded but <50 lines | 🟡 Low overhead, keep unless >70 total skills |
| Loaded 1-2x in 100 sessions | 🟡 Review — may be niche but legitimate |
| Loaded 5+ times | 🟢 Active, keep |

### 7.3 Removal Decision

After running 7.1, output a pruning recommendation:

```
## Skill Pruning Recommendations

### 🔴 Remove (never used, high overhead)
- skill-name (N lines) — reason

### 🟡 Consider removing (rarely used)
- skill-name (N lines) — last used: session_XXX

### 🟢 Keep (actively used)
- skill-name (Nx in 100 sessions)
```

**Important**: Only remove skills from `~/.hermes/skills/` (local). Plugin-provided skills (openclaw-imports, etc.) are managed by the plugin system.

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
- Cache hit ratio: [N]%
- busy_input_mode: [interrupt/queue/steer]

## Phase 7 Skill Pruning: ✅/⚠️/❌
- Never-loaded skills: [N]/[total]
- Recommended removals: [N] (saving ~[N] lines from index)

## Actions Taken
- [what was fixed]

## Remaining Issues
- [what needs manual decision]
```

---

## Scheduling

```bash
# Monthly auto-audit with report to feishu
hermes cron create "0 10 1 * *" \
  "Load hermes-health-audit skill, run all 7 phases, output report" \
  --skill hermes-health-audit
```
