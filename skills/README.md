# Claude Code Skills Collection

11 battle-tested Skills covering the core Claude Code use cases — from browser automation to infrastructure ops.

## Skill Catalog

| Category | Skill | Description |
|----------|-------|-------------|
| Library & API Reference | [`chrome-devtools`](chrome-devtools/) | Chrome DevTools Protocol automation: interaction, screenshots, scraping, performance auditing |
| Product Validation | [`claude-code`](claude-code/) | Task dispatch via tmux, progressive delivery, Slot Machine recovery, `/loop` mode |
| Data Extraction | *(coming soon)* | — |
| Workflow Automation | [`subagents`](subagents/) | 7 pre-built agent definitions for research, review, QA, cost optimization, and more |
| Code Scaffolding | [`skill-creator`](skill-creator/) | Meta-skill: how to build, structure, and evaluate your own Skills |
| Code Quality & Review | [`skill-vetting`](skill-vetting/) | Security audit for third-party Skills before installation |
| CI/CD & Deployment | [`aws-infra`](aws-infra/) | AWS infrastructure queries, auditing, and monitoring — read-only by default |
| Runbook | [`deep-research`](deep-research/) | Structured research: multi-source search, freshness filtering, cross-validation |
| Infrastructure Ops | [`config-sync`](config-sync/) | CLAUDE.md contradiction detection, stale reference checks, audit reports |
| Infrastructure Ops | [`openclaw-upgrade`](openclaw-upgrade/) | Upgrade OpenClaw: pre-flight, install, config migration, launchd re-register, smoke test, rollback |
| Developer Experience | [`notification-hooks`](notification-hooks/) | Desktop notifications via Notification/Stop hooks — project name, what's waiting, click-to-focus, distinct sounds |

**Bonus:** [`architecture-svg`](architecture-svg/) — Generate dark-theme SVG architecture diagrams for GitHub READMEs.

## Installation

Copy individual skills:

```bash
cp -r skills/<name> ~/.claude/skills/
```

Or install all at once:

```bash
git clone --depth 1 https://github.com/cncoder/oneclaw.git /tmp/oneclaw
cp -r /tmp/oneclaw/skills/* ~/.claude/skills/
rm -rf /tmp/oneclaw
```

## Skill Details

### chrome-devtools

Browser automation via CDP — click, type, screenshot, scrape, fill forms, run Lighthouse audits, emulate devices. Use when you need to interact with or inspect a web page.

### claude-code

Dispatch and manage Claude Code sessions through tmux. Handles task splitting, progressive delivery, session monitoring, and crash recovery via the Slot Machine pattern.

### subagents

7 specialized agent definitions: researcher, architect, code-reviewer, QA tester, data analyst, cost optimizer, doc updater. Drop them into your agent config for instant team orchestration.

### skill-creator

A guide for creating new Claude Code skills from scratch — covers file structure, SKILL.md format, description writing, trigger design, and eval methodology.

### skill-vetting

Security review checklist for third-party Skills. Detects prompt injection, secret exfiltration, excessive permissions, and unsafe tool usage before you install.

### deep-research

Structured research methodology with multi-source search, freshness filtering, cross-validation, and 5-dimension quality scoring. Use for any investigation that needs rigor.

### aws-infra

AWS infrastructure assistance via CLI. Queries resources, checks security groups, audits IAM policies, monitors costs. Read-only by default; write actions require explicit confirmation.

### config-sync

Scans CLAUDE.md files for contradictions, stale references, and redundancy. Generates audit reports with fix suggestions. Use after editing any configuration file.

### architecture-svg

Generates professional dark-theme SVG architecture diagrams optimized for GitHub README rendering. Supports AWS, system, and network topologies.

### openclaw-upgrade

Runbook for upgrading OpenClaw cleanly on macOS: pre-flight checks, pnpm install via proxy, config migration (breaking-change table), pnpm store cleanup, launchd re-registration, agent smoke test, and rollback. Includes a "Common Pitfalls" quick list — the 10 mistakes that block most upgrades.

### notification-hooks

Desktop notifications for Claude Code via `Notification` and `Stop` hooks. Pops a native macOS notification showing which project is waiting, what it's asking, and a distinct sound per event — plus click-to-focus back to your terminal. Includes the gotcha most people hit (whitelisting all tools silences `Notification`) and the verified Ghostty-vs-iTerm2 click-to-focus difference on Sequoia. Ships a terminal-aware `notify.sh`.

## License

MIT
