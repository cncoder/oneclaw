---
name: deep-research
description: "Structured research methodology for technical investigations. Use when evaluating technologies, comparing solutions, investigating incidents, or any task requiring verified, multi-source information gathering."
---

# Skill: deep-research

A structured methodology for conducting thorough technical research. Produces verified, actionable intelligence from multiple sources.

---

## When to Use

- Evaluating a technology, library, or service before adopting it
- Comparing competing solutions for a technical decision
- Investigating production incidents or performance issues
- Gathering requirements from scattered documentation
- Any question where the first search result isn't enough

---

## Research Workflow

### Phase 1: Scope Definition

Before searching anything, define the research boundary:

```markdown
## Research Scope
- **Question**: {specific question to answer}
- **Context**: {why this matters, what decision it informs}
- **Constraints**: {budget, timeline, tech stack, compliance}
- **Success Criteria**: {what "good enough" looks like}
- **Time Box**: {max research time before synthesizing}
```

### Phase 2: Multi-Source Search

Use at least 3 independent sources. Never rely on a single source for critical decisions.

| Source Type | Best For | Tools |
|-------------|----------|-------|
| Official docs | API details, configuration, limits | Context7, WebFetch, CDP |
| GitHub issues | Known bugs, workarounds, community sentiment | WebSearch, GitHub API |
| Stack Overflow | Common problems and vetted solutions | WebSearch |
| Release notes | Breaking changes, deprecations | GitHub releases, changelogs |
| Benchmarks | Performance claims verification | GitHub repos, blog posts |
| Source code | Ground truth when docs are wrong | `git clone --depth 1`, Grep |

**Search Strategy:**
1. Start with official documentation (highest signal-to-noise)
2. Check GitHub issues for real-world problems
3. Search for recent (< 6 months) comparisons or benchmarks
4. Clone and read source code when docs are ambiguous

### Phase 3: Freshness Filter

Information decays. Apply these freshness rules:

| Information Type | Max Age | Action if Older |
|------------------|---------|-----------------|
| API documentation | 3 months | Verify against source code |
| Security advisories | 1 month | Check CVE databases directly |
| Performance benchmarks | 6 months | Note date, flag as "may be outdated" |
| Architecture patterns | 2 years | Still valid if fundamentals unchanged |
| Library popularity / stars | 3 months | Check current numbers |

### Phase 4: Cross-Validation

Every critical finding needs corroboration:

```
Finding → Source 1 confirms → Source 2 confirms → HIGH confidence
Finding → Source 1 confirms → Source 2 contradicts → INVESTIGATE
Finding → Single source only → MEDIUM confidence (flag it)
Finding → No source, inferred → LOW confidence (state assumptions)
```

**Red flags that require deeper investigation:**
- Official docs and community reports disagree
- Feature claimed in marketing but absent from changelog
- Benchmark numbers that seem too good (check methodology)
- "Works great" posts from accounts with no other activity

### Phase 5: Synthesis

Compile findings into the output template below.

---

## Output Template

```markdown
## Research Report: {topic}

### Executive Summary
{2-3 sentences: what was investigated, key finding, recommendation}

### Findings

#### {Finding 1 Title}
- **Claim**: {what the source says}
- **Source**: {URL or reference}
- **Verified by**: {second source or "single source — medium confidence"}
- **Relevance**: {how this affects the decision}

#### {Finding 2 Title}
...

### Comparison Matrix (if comparing options)

| Criteria | Option A | Option B | Option C |
|----------|----------|----------|----------|
| {criterion 1} | | | |
| {criterion 2} | | | |
| {criterion 3} | | | |

### Quality Score

Rate each dimension 1-5:

| Dimension | Score | Notes |
|-----------|-------|-------|
| **Completeness** | /5 | Were all aspects of the question covered? |
| **Freshness** | /5 | How current is the information? |
| **Source Diversity** | /5 | How many independent sources? |
| **Verification** | /5 | Were findings cross-validated? |
| **Actionability** | /5 | Can a decision be made from this? |

### Open Questions
- {What couldn't be determined}
- {What needs further investigation}

### Methodology
- Sources consulted: {count}
- Time spent: {duration}
- Search queries used: {list key queries}
```

---

## Anti-Patterns

| Don't | Do Instead |
|-------|-----------|
| Trust the first result | Cross-validate with 2+ sources |
| Spend 2 hours searching without synthesizing | Time-box each phase, synthesize incrementally |
| Ignore information age | Always check publication date, flag stale data |
| Copy-paste without attribution | Track sources for every finding |
| Research endlessly | Define "good enough" upfront, stop when criteria met |
| Skip official docs and go straight to blogs | Official docs first — they're the ground truth |
| Assume popular = good | Check issues, maintenance activity, and alternatives |

---

## Quick Reference: Search Commands

```bash
# Clone a repo for local analysis (fast, read-only)
git clone --depth 1 https://github.com/org/repo.git /tmp/repo-inspect

# Search for specific patterns across a cloned repo
grep -rn "pattern" /tmp/repo-inspect/src/

# Check project health signals
gh api repos/org/repo --jq '{stars: .stargazers_count, issues: .open_issues_count, updated: .pushed_at}'

# Get recent releases
gh api repos/org/repo/releases --jq '.[0:5] | .[] | {tag: .tag_name, date: .published_at}'
```
