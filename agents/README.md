# Claude Code Sub-Agents

Specialized sub-agents for Claude Code. Install to `~/.claude/agents/` to use with the `Agent` tool.

## Installation

```bash
cp agents/*.md ~/.claude/agents/
```

After copying, agents are available via Claude Code's `Agent` tool with `subagent_type`.

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

## Decision Table

| Task Type | Primary Agent | Supporting Agent(s) |
|-----------|--------------|---------------------|
| New feature planning | `architect` | `researcher` (prior art) |
| Feature implementation | (you, the main agent) | `code-reviewer` (post-write) |
| Bug investigation | `researcher` (logs/docs) | `data-analyst` (metrics) |
| Performance optimization | `data-analyst` (profiling) | `cost-optimizer` (infra) |
| Release preparation | `qa-tester` (verification) | `doc-writer` (changelog) |
| Cost review | `cost-optimizer` | `data-analyst` (trends) |
| Security audit | `code-reviewer` | `researcher` (CVE lookup) |

## Model Selection

| Tier | Cost | Best For |
|------|------|----------|
| **Haiku** | Lowest | Repetitive tasks, data collection, formatting, simple QA |
| **Sonnet** | Medium | Day-to-day development, research, code review, analysis |
| **Opus** | Highest | Deep architecture, complex trade-offs, multi-system design |
