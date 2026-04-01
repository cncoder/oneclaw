---
name: subagents
description: "Business process automation with specialized sub-agents. Use when orchestrating multi-step workflows that benefit from role-specific agents — research, architecture, code review, QA, data analysis, cost optimization, or documentation."
---

# Skill: subagents

Orchestrate specialized sub-agents for complex workflows. Each agent has a focused role, recommended model tier, and structured output format.

---

## Installation

```bash
cp agents/*.md ~/.claude/agents/
```

After copying, agents are available via Claude Code's `/agent` command or the `Agent` tool with `subagent_type`.

---

## Agent Inventory

| Agent | Model | Role | When to Use |
|-------|-------|------|-------------|
| `researcher` | Sonnet | Web research, doc lookup, competitive analysis | Need external information before making decisions |
| `architect` | Opus | System design, tech decisions, trade-off analysis | Planning new features, evaluating architectures |
| `code-reviewer` | Sonnet | Code quality, security, best practices | After writing code, before merging |
| `qa-tester` | Haiku | Test execution, bug verification, regression checks | After implementation, before release |
| `data-analyst` | Sonnet | Data processing, visualization, insight extraction | Analyzing logs, billing, metrics, survey data |
| `cost-optimizer` | Haiku | Cloud spend analysis, waste detection, savings recommendations | Monthly reviews, unexpected bill spikes |
| `doc-writer` | Haiku | Documentation updates, changelog generation, API docs | After features ship, before release notes |

---

## Decision Table

Use this to pick the right agent(s) for a task:

| Task Type | Primary Agent | Supporting Agent(s) |
|-----------|--------------|---------------------|
| New feature planning | `architect` | `researcher` (prior art) |
| Feature implementation | (you, the main agent) | `code-reviewer` (post-write) |
| Bug investigation | `researcher` (logs/docs) | `data-analyst` (metrics) |
| Performance optimization | `data-analyst` (profiling) | `cost-optimizer` (infra) |
| Release preparation | `qa-tester` (verification) | `doc-writer` (changelog) |
| Cost review | `cost-optimizer` | `data-analyst` (trends) |
| Security audit | `code-reviewer` | `researcher` (CVE lookup) |

---

## Model Selection Guide

| Tier | Models | Cost | Best For |
|------|--------|------|----------|
| **Haiku** | claude-haiku-4-5 | Lowest | Repetitive tasks, data collection, formatting, simple QA |
| **Sonnet** | claude-sonnet-4-6 | Medium | Day-to-day development, research, code review, analysis |
| **Opus** | claude-opus-4-6 | Highest | Deep architecture, complex trade-offs, multi-system design |

**Rule of thumb:** Start with the cheapest model that can do the job. Escalate only when output quality is insufficient.

---

## Orchestration Patterns

### Parallel Fan-Out

When tasks are independent, launch agents simultaneously:

```
# Research + Architecture in parallel
Agent(researcher, "Survey authentication libraries for Node.js")
Agent(architect, "Design auth module given these constraints: ...")
```

### Sequential Pipeline

When each step depends on the previous:

```
1. researcher → gather requirements and prior art
2. architect → design solution based on research
3. (implement)
4. code-reviewer → review implementation
5. qa-tester → verify functionality
6. doc-writer → update documentation
```

### Review Gate

Block progress until review passes:

```
1. Implement feature
2. code-reviewer → review
3. If CRITICAL/HIGH issues → fix → re-review
4. If clean → proceed to QA
```

---

## Anti-Patterns

| Don't | Do Instead |
|-------|-----------|
| Use Opus for simple formatting tasks | Use Haiku — it's 20x cheaper |
| Run all agents sequentially | Parallelize independent tasks |
| Skip code review on "small" changes | Small changes cause big bugs — always review |
| Give agents vague prompts | Include scope, goal, constraints, expected output |
| Let a single agent run for 30+ minutes | Split into smaller sub-tasks |

---

## Agent Definitions

Each agent file in `agents/` follows this structure:

```yaml
---
name: agent-name
description: One-line description
model: haiku | sonnet | opus
---

## Role
What this agent does.

## Responsibilities
- Specific duty 1
- Specific duty 2

## Output Format
How results should be structured.

## Constraints
- Boundary 1
- Boundary 2
```

See `agents/` directory for all agent definitions.
