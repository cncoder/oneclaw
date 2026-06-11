# Hermes QA / Regression Evaluation Playbook

How to **prove** a config/prompt/skill change actually changed the agent's
behavior — not just that the file saved. The reverse-QA loop below is the most
effective diagnostic we found: change a rule → trigger it with a real task →
watch for the failure signal → if it fails, ask the agent *why* and let it name
the rule it skipped.

> Editing SOUL.md / config.yaml / a skill is NOT "done." A running gateway holds
> the OLD prompt and OLD config until you restart it. Always: **restart → trigger
> → observe → (on fail) interrogate.**

## Rule 0: test with the RIGHT harness

- **Use a STATEFUL session. Never judge behavior from a one-shot stateless call.**
  A stateless probe (`hermes -z`) starts fresh every time, remembers no history,
  and the agent doesn't treat it as a real conversation — so behaviors like
  "save long output to a doc", "follow formatting rules", or "use memory" all
  read wrong. Use a stateful invocation:
  `hermes chat --source <channel> --yolo -q "<task>"`.
- **Most accurate of all:** have a human send a real message through the actual
  channel and watch the gateway session. Synthetic tasks drift from real ones.
- **Restart before testing:** after editing SOUL/MEMORY/config, restart the
  gateway (e.g. `launchctl kickstart -k gui/$(id -u)/<gateway-label>` or your
  service manager's equivalent) or you're testing the old prompt.

## Rule 1: every optimized rule needs a triggering test case

Don't test "in general." For each rule you changed, write a case as
**`task → expected behavior → failure signal`**. The failure signal must be
something you can grep or eyeball unambiguously. Examples (adapt to your rules):

### Output is a finished product, not a workbench
- **Task:** ask for something that requires checking current state ("check the
  current version of X, then recommend").
- **Expected:** reply is plain prose; no tool-call XML, no bash, no command
  output, no model/progress lines.
- **Failure signal:** reply contains `<invoke>`, `<parameter>`, raw `bash`/`curl`,
  or a progress line like `...opus... 34%`.

### Long answers go to a document, not the chat
- **Task:** ask for a complete plan ("full migration plan: steps, risks, rollback").
- **Expected:** when the reply exceeds ~50 lines, the agent *proactively* creates
  a doc and returns a summary + link. It does NOT ask "want me to save this?" —
  the rule is MUST, not optional.
- **Failure signal:** the whole plan is dumped inline; or it ends with "I can save
  this to a doc if you'd like."
- **Verify the save is real:** check the tool log for the doc-create call and
  confirm the returned link's domain matches the intended workspace — don't trust
  the agent's claim that it saved.

### No code blocks in chat
- **Task:** the same plan task (plans usually contain commands).
- **Expected:** no code/XML/command fences in the reply; code goes in the doc.
- **Failure signal:** a ``` fence or a raw command with inline args in the reply.

### Profile / credential resolved at runtime, not hardcoded
- **Task:** ask it to do a channel action that needs a profile.
- **Expected:** it queries the available profiles and picks by attribute, instead
  of assuming a hardcoded name.
- **Failure signal:** "profile not found" from a hardcoded name; or it targets the
  wrong workspace/environment.

### Error → self-heal, don't bounce back
- **Task:** with a token deliberately expired, ask it to do the action.
- **Expected:** it runs its diagnose/self-heal path and recovers on its own.
- **Failure signal:** it stops and asks the human what to do.

## Rule 2: judgment

For each case: **all expected behaviors present = PASS; any failure signal = FAIL**,
and record the offending text verbatim.

## Rule 3: on FAIL, interrogate the agent for root cause (the key technique)

This is the highest-value step and the one most people skip. When a case fails,
ask the agent directly:

> "Why didn't you do X? One sentence, root cause, no excuses."

In practice the agent will often name exactly which rule it didn't read, or admit
it rationalized its way around one ("I treated this as 'just notes' so I skipped
the doc rule"). That tells you precisely how to rewrite the rule — usually it
needs a higher priority tag, an explicit consequence, or a closed loophole
("NEVER use 'this isn't the X channel' as an excuse"). Feed the fix back into
SOUL.md and re-run the case.

This closes the loop: **observe failure → extract root cause from the agent →
patch the rule → regression-test again.**

## Known gotchas

- **Restart or you test the old prompt.** The #1 false result.
- **Stateless ≠ stateful.** Don't draw conclusions from `-z`.
- **`finish_reason=length` is a technical truncation, not a rule failure.** A long
  task hitting the output-token cap looks like the agent "gave up" — it didn't.
  Distinguish a truncated answer from an ignored rule before logging a FAIL.
- **Use real tasks the human actually asked recently**, not invented scenarios —
  synthetic prompts trigger different behavior than genuine ones.

## How this fits the audit

Run this playbook as the verification gate after ANY Phase change in this skill:
Phase 1 (observability), Phase 2 (compression), Phase 3 (prompt consistency),
Phase 8 (tool-use/delegation). A green audit with no behavioral regression test
is an unverified audit.
