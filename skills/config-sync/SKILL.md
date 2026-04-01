---
name: config-sync
description: "Configuration consistency auditing for Claude Code setups. Use when checking CLAUDE.md for contradictions, detecting stale references, finding redundant rules, or auditing configuration health after changes."
---

# Skill: config-sync

Audit Claude Code configuration files for contradictions, stale references, redundancy, and drift. Keeps your rules, settings, and agent definitions consistent.

---

## When to Use

- After editing any config file (CLAUDE.md, settings.json, agents, rules)
- Periodic health checks (monthly or after major changes)
- When Claude Code behaves unexpectedly (possible conflicting rules)
- Before sharing configuration with teammates
- After merging configuration from another machine

---

## Audit Scope

| File / Directory | What to Check |
|------------------|---------------|
| `~/.claude/CLAUDE.md` | Global instructions, contradictions with project-level |
| `<project>/CLAUDE.md` | Project rules, stale tool/file references |
| `~/.claude/settings.json` | Hook paths, permission settings, MCP config |
| `~/.claude/rules/**/*.md` | Cross-rule contradictions, outdated patterns |
| `~/.claude/agents/*.md` | Agent definitions match available tools |
| `~/.mcp.json` | MCP server paths exist, no duplicate entries |

---

## Audit Workflow

### Step 1: Inventory

Collect all configuration files:

```bash
# List all CLAUDE.md files in scope
find ~/.claude -name "CLAUDE.md" -o -name "*.md" | head -50
cat ~/.claude/settings.json
cat ~/.mcp.json
```

### Step 2: Contradiction Detection

Check for conflicting instructions across files:

| Contradiction Type | Example | Detection Method |
|-------------------|---------|------------------|
| **Direct conflict** | File A: "always use tabs" / File B: "always use spaces" | Search for opposing directives |
| **Priority conflict** | Global says X, project says NOT X | Check CLAUDE.md hierarchy |
| **Tool conflict** | Rule says "use tool A" but tool A not in MCP config | Cross-reference with settings.json |
| **Model conflict** | Agent specifies model not available in provider config | Check against provider settings |

**Search patterns for contradictions:**

```bash
# Find opposing directives
grep -rn "never\|always\|must\|forbidden\|required" ~/.claude/rules/ ~/.claude/CLAUDE.md

# Find tool references
grep -rn "mcp__\|MCP\|tool" ~/.claude/rules/ ~/.claude/CLAUDE.md

# Find model references
grep -rn "haiku\|sonnet\|opus\|claude" ~/.claude/agents/
```

### Step 3: Stale Reference Detection

Check that referenced files, tools, paths, and commands still exist:

```bash
# Extract file paths from CLAUDE.md and verify they exist
grep -oE '~?/[a-zA-Z0-9_./-]+' ~/.claude/CLAUDE.md | while read p; do
  expanded=$(eval echo "$p")
  [ ! -e "$expanded" ] && echo "STALE: $p"
done

# Check MCP server commands exist
cat ~/.mcp.json | python3 -c "
import json, sys, shutil
cfg = json.load(sys.stdin)
for name, srv in cfg.get('mcpServers', {}).items():
    cmd = srv.get('command', '')
    if cmd and not shutil.which(cmd):
        print(f'MISSING: {name} → {cmd}')
"
```

### Step 4: Redundancy Detection

Find rules that say the same thing in different places:

- Same instruction in global CLAUDE.md AND project CLAUDE.md
- Same rule in `rules/common/` AND `rules/<language>/`
- Agent definition duplicated across files

### Step 5: Generate Report

---

## Audit Report Format

```markdown
## Config Audit Report — {date}

### Summary
- Files scanned: {count}
- Issues found: {critical} critical, {warning} warning, {info} info

### Critical Issues (fix immediately)
| ID | Type | File | Line | Description |
|----|------|------|------|-------------|
| C1 | Contradiction | path | N | Rule A conflicts with Rule B |

### Warnings (fix when convenient)
| ID | Type | File | Line | Description |
|----|------|------|------|-------------|
| W1 | Stale ref | path | N | Referenced file does not exist |

### Info (cosmetic)
| ID | Type | File | Description |
|----|------|------|-------------|
| I1 | Redundancy | path | Same rule appears in 2 files |

### Recommendations
1. {Highest priority fix}
2. {Second priority}

### Files Scanned
- {list of all files checked}
```

---

## Common Issues & Fixes

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Claude ignores a rule | Contradicted by higher-priority CLAUDE.md | Remove contradiction or adjust priority |
| Agent uses wrong model | Agent definition outdated | Update `model` field in agent YAML |
| MCP tool calls fail | Server path changed after upgrade | Update `~/.mcp.json` command/args |
| Hook doesn't fire | Path in settings.json is wrong | Verify hook script path exists |
| Rules from old project | Copy-pasted without cleanup | Remove project-specific references |

---

## Automation

Run this audit periodically. Add to your workflow:

```bash
# Quick health check (run in Claude Code)
# "Audit my Claude Code configuration for contradictions and stale references"

# Or as a scheduled reminder
# Add to your weekly review checklist
```

---

## Anti-Patterns

| Don't | Do Instead |
|-------|-----------|
| Copy entire CLAUDE.md between projects | Extract shared rules to `~/.claude/rules/common/` |
| Override global rules in every project | Fix the global rule if it's wrong |
| Keep rules for removed tools/features | Delete stale rules during audit |
| Duplicate agent definitions | Single source of truth in `~/.claude/agents/` |
| Ignore audit warnings | Fix warnings — they become bugs later |
