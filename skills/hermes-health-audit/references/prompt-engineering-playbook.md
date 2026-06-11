# Hermes Prompt-Engineering Playbook

How to write and refactor the identity prompt (`~/.hermes/SOUL.md`) so the model
actually *follows* it instead of nodding and forgetting. Distilled from a real
optimization round. **Methodology only — no personal identity, names, or paths.**

> **Where rules must live.** Hermes' system prompt stably loads exactly ONE
> identity file: `~/.hermes/SOUL.md` (official slot #1, loaded regardless of cwd).
> A workspace `AGENTS.md` is only read when the working directory *happens* to be
> `~/.hermes` — under cron, gateway, or external orchestration the cwd is usually
> elsewhere, so **rules written in AGENTS.md silently never load.** Put every
> behavioral rule and safety line in SOUL.md. Treat AGENTS.md as deprecated; leave
> a one-line tombstone pointing at SOUL.md so nobody re-adds rules there.

## The core problem: "loaded but ignored"

A long identity file gets read once and then out-prioritized by the live
conversation. Symptoms: the model narrates instead of acting, dumps raw tool
calls to users, skips a rule it "knows." Fixes below are ordered by leverage.

## 1. Priority labels the model can actually rank

Plain prose gives the model nothing to rank. Tag each rule with an explicit
strength and put the highest-priority section FIRST in the file:

- **`MUST` / `MUST NEVER`** — hard rules. Use sparingly; if everything is MUST,
  nothing is.
- **`(最高优先级 / highest priority)`** on the one or two sections that override
  all others (e.g. "speak plainly", "every reply is a finished product").
- **`NEVER` / `ALWAYS`** — strong defaults, one notch below MUST.

Ranking only works if it's scarce. Three MUST-NEVER lines beat thirty.

## 2. Every rule carries its consequence

A rule with a stated failure cost survives context pressure far better than a
bare imperative. Pattern: **`<rule>. 后果：<what breaks if you don't>.`**

- Weak:  "Don't hardcode credentials."
- Strong: "MUST NEVER hardcode credentials. 后果：once a key lands in the repo or
  a log it counts as leaked and must all be rotated."

The consequence is what makes the model *choose* the rule when it conflicts with
finishing a task fast.

## 3. Positive + negative example pairs

For any rule about *style or judgment* (not a binary action), show one bad and
one good example inline. The model pattern-matches against them.

```
反例（别这么写）: "该方案本质是对验证瓶颈的结构性重构，这意味着……"
正例（要这么写）: "以前测试靠人写人维护，太贵，大家干脆不写。现在 agent 把成本
                   压到几乎为零，验证这件事就重新值得做了。"
```

## 4. Compress, don't accumulate (the refactor that matters)

Identity files rot by accretion — every incident adds a paragraph. Past a point
the file is so long the model skims it. Measured compression method:

1. **One rule = one line.** Move the *why* and the *how* into a referenced skill;
   keep only the imperative + consequence in SOUL.md. Example: a 10-line
   "search strategy" section collapses to one line — "深度搜索先广后深，单一来源标
   待验证，详见 `skills/<name>`" — with the full protocol in the skill.
2. **Dedup across sections.** The same idea ("verify, don't trust memory") often
   appears 3× in different words. Merge to one canonical line.
3. **Pull operational detail OUT.** Step-by-step runbooks (how to publish a doc,
   how to self-heal a token) belong in a skill, not the identity prompt. SOUL.md
   says *what* and *why*; the skill says *how*.
4. **Keep safety lines verbatim.** Compression applies to guidance, not to the
   hard safety section — those stay explicit.

Target: an identity file you can read top-to-bottom in under two minutes. If you
can't, the model isn't either.

## 5. Output discipline lives in the prompt, not in hope

The single most valuable behavioral section in a chat-facing agent is **"every
reply is a finished product, not a workbench."** Make it explicit and MUST-level:

- Never emit tool-call XML, bash, command output, thinking drafts, or progress
  lines to the user. Report progress in one human sentence.
- Long content (a plan, a runbook, anything over ~50 lines) goes into a document
  with a link returned — not pasted into chat. (Also dodges provider timeouts on
  one giant generation: build the doc incrementally, append + read-back.)
- Self-check before sending: *would I forward this verbatim to a customer?* If
  not, rewrite.

This section pays for itself immediately and is the easiest to regression-test
(see the QA playbook).

## 6. Channel-specific rendering rules

If the agent talks to a client that renders markdown poorly (e.g. the Lark/Feishu
post-markdown renderer does NOT render pipe tables — `| a | b |` shows as raw
characters), put the workaround in the prompt: "prefer indented lists over tables
on Feishu." Pair it with the config-level mute flags (see the full config
reference, `display.platforms.feishu`). Prompt + config together; neither alone.

## 7. Anti-AI-tells list

Maintain an explicit ban list of filler the model defaults to. Deleting these is
the difference between "writing" and "AI slop":

> 这意味着 / 从本质上来说 / 接下来我们来看 / 值得一提的是 / 综上所述 / 希望对你有帮助 /
> "It's worth noting" / "In conclusion" / "Now that we've covered X, let's turn to Y"

State the rule as: say the thing directly, skip the ceremony.

## Refactor workflow (safe procedure)

1. **Back up first**: `cp SOUL.md SOUL.md.bak-$(date +%Y%m%d-%H%M%S)`.
2. Make the edit (compress / re-tag / add consequences).
3. **Fix stale cross-references.** A refactor that renames or moves a section
   leaves dangling pointers ("see AGENTS.md" after rules moved to SOUL.md). Grep
   for old section names and file names across SOUL.md, AGENTS.md, and skills;
   update or delete every dangling pointer (this is Phase 8.4 of the audit).
4. **Restart the gateway** — a running gateway keeps the OLD prompt until restart.
5. **Regression-test** every changed rule with a real triggering task (see
   `qa-evaluation-playbook.md`). Editing the file is not the same as the rule
   taking effect.
