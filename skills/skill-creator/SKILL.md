---
name: skill-creator
description: "Guide for creating Claude Code skills from scratch. Use when building new skills, understanding skill file structure, writing effective descriptions, or improving existing skills."
---

# Skill: skill-creator

A practical guide to creating high-quality Claude Code skills. Covers file structure, description writing, common pitfalls, and testing.

---

## Skill File Structure

```
skills/
└── my-skill/
    ├── SKILL.md              # Required — the skill definition
    ├── references/            # Optional — supporting docs, examples
    │   ├── example.md
    │   └── patterns.md
    ├── agents/                # Optional — sub-agent definitions
    │   └── specialist.md
    └── scripts/               # Optional — automation scripts
        └── scan.py
```

### SKILL.md Anatomy

```markdown
---
name: my-skill
description: "One-line description. Use when [trigger conditions]."
metadata:                     # Optional
  openclaw:
    emoji: "⚡"
    requires:
      bins: ["tool1", "tool2"]
---

# Skill: my-skill

Brief intro — what this skill does and why it exists.

## When to Use
Trigger conditions and decision criteria.

## Quick Start
Minimal steps to get value immediately.

## Core Content
The actual methodology, workflow, or reference material.

## Anti-Patterns / Gotchas
Common mistakes and how to avoid them.
```

---

## Writing Effective Descriptions

The `description` field is the most important line in your skill. It determines when the skill gets activated.

### Rules

1. **Start with what it does** — not what it is
2. **Include trigger phrases** — "Use when [specific scenario]"
3. **Be specific** — "AWS billing analysis" beats "cloud stuff"
4. **Keep it under 200 characters** — it's a filter, not documentation

### Good vs Bad

| Bad | Good |
|-----|------|
| "A tool for helping with code" | "Code quality review with security focus. Use after writing code, before merging." |
| "Handles AWS things" | "AWS infrastructure queries via CLI. Use for auditing, monitoring, and resource inventory." |
| "Testing skill" | "E2E browser testing via Chrome DevTools. Use when verifying UI flows, form submissions, or visual regressions." |

---

## 9 Tips for Skill Creation

### 1. One Skill, One Job

A skill should do one thing well. If your SKILL.md covers both "database optimization" and "API design," split it into two skills.

### 2. Lead with the Workflow

Users need to know WHAT to do, in WHAT order. Structure your skill as a numbered workflow, not a reference manual.

### 3. Include Decision Tables

When the skill involves choosing between approaches, provide a decision matrix:

```markdown
| Scenario | Approach | Why |
|----------|----------|-----|
```

### 4. Show the Output Format

Define what good output looks like. Include templates with placeholders that the agent can fill in.

### 5. Define Hard Rules

If there are non-negotiable constraints, state them explicitly in a "Hard Rules" or "Constraints" section. Agents follow explicit rules better than implicit conventions.

### 6. Add Anti-Patterns

A "Don't do this" section prevents the most common mistakes. Format as a table: `Don't | Do Instead`.

### 7. Keep References Separate

Large lookup tables, CLI command references, or pattern libraries belong in `references/`, not in SKILL.md. Keep the main file focused on workflow.

### 8. Test with Real Prompts

Before shipping, test your skill with 5+ realistic user prompts. Check:
- Does the skill activate when it should?
- Does it produce the expected output format?
- Does it handle edge cases gracefully?

### 9. Version Through Git

Skills are plain Markdown — use git for versioning. Commit messages should explain WHY the skill changed, not just what changed.

---

## Gotchas

| Pitfall | Impact | Prevention |
|---------|--------|------------|
| Description too vague | Skill never activates | Include specific trigger phrases |
| SKILL.md too long (>500 lines) | Agent loses focus mid-skill | Extract to `references/` |
| No output format defined | Inconsistent results | Add a template with placeholders |
| Hardcoded paths or secrets | Skill breaks on other machines | Use environment variables or relative paths |
| Missing `When to Use` section | Users don't know when to apply it | Always include trigger criteria |
| Overly rigid workflow | Doesn't adapt to variations | Mark optional steps clearly |
| No anti-patterns section | Users repeat common mistakes | Add "Don't / Do Instead" table |

---

## Eval Method

Test your skill systematically:

### Manual Eval

1. Write 5 test prompts that SHOULD trigger the skill
2. Write 3 test prompts that SHOULD NOT trigger it
3. Run each prompt and check:
   - Did it activate? (precision)
   - Did it produce correct output? (quality)
   - Did it follow the defined workflow? (compliance)

### Checklist

- [ ] `name` is lowercase-kebab-case
- [ ] `description` includes "Use when" trigger
- [ ] SKILL.md has Quick Start section
- [ ] Output format is defined with template
- [ ] Anti-patterns / Gotchas section exists
- [ ] No hardcoded paths, secrets, or machine-specific values
- [ ] References extracted to `references/` if SKILL.md > 300 lines
- [ ] Tested with 5+ realistic prompts
