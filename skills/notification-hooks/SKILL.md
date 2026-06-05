---
name: notification-hooks
description: "Desktop notifications for Claude Code via Notification/Stop hooks. Pops a native macOS notification showing which project, who's waiting, and what for — with click-to-focus back to your terminal. Use when setting up sound alerts, desktop notifications, or 'tell me when Claude needs me / is done'."
metadata:
  openclaw:
    emoji: "🔔"
    requires:
      bins: ["jq"]
    optional:
      bins: ["terminal-notifier"]
---

# Skill: notification-hooks

Make Claude Code tell you when it needs you. Two lifecycle hooks cover the only two moments worth a heads-up:

- **`Notification`** fires when Claude is *blocked on you* — a permission prompt, an A/B/C question, or it's been idle a while waiting.
- **`Stop`** fires when Claude *finishes a turn* and hands control back.

This skill wires both to a script that pops a native desktop notification — **which project, who's waiting, what for** — plus a distinct sound per event, and click-to-focus back to your terminal.

---

## When to Use

- "Play a sound when Claude needs my approval / is done"
- "Notify me which project is waiting and what it's asking"
- "I keep missing permission prompts in a background terminal"
- Setting up `Notification` or `Stop` hooks for the first time

Not for: PostToolUse formatting, PreToolUse blocking, or any per-tool automation — those are different hook events.

---

## The One Thing People Get Wrong

`Notification` only fires when Claude is **actually blocked waiting on you**. If your `permissions.allow` whitelists `Bash`, `Write`, `Edit`, `Read`, then nothing ever prompts — so the hook never fires and you hear nothing. That's not a broken hook; it's a hook with no trigger.

**Decision table — what fires when:**

| Moment | Event | Fires if... |
|--------|-------|-------------|
| Permission prompt (command not allowed) | `Notification` | the command isn't in `allow` |
| A/B/C or yes-no question (AskUserQuestion) | `Notification` | always |
| Idle too long with input needed | `Notification` | always |
| Claude finished its turn, waiting for you | `Stop` | always |

If you whitelist everything, you'll only ever hear `Stop`. Want a beep on *every* turn-end regardless of permissions? That's `Stop` — and it always fires.

---

## Quick Start

### Sound only (zero dependencies, macOS)

Distinct sound per event so you can tell "needs me" from "done" without looking:

```json
{
  "hooks": {
    "Notification": [
      { "hooks": [{ "type": "command", "command": "afplay /System/Library/Sounds/Glass.aiff", "timeout": 10 }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "afplay /System/Library/Sounds/Hero.aiff", "timeout": 10 }] }
    ]
  }
}
```

Built-in macOS sounds live in `/System/Library/Sounds/` (Glass, Hero, Ping, Sosumi, Submarine, Funk...). Pick any two that sound different.

### Full notifications (project name + content + click-to-focus)

1. `brew install terminal-notifier`
2. Copy `scripts/notify.sh` to `~/.claude/hooks/notify.sh` and `chmod +x` it.
3. Point both hooks at the script, passing the event name as `$1`:

```json
{
  "hooks": {
    "Notification": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/notify.sh Notification", "timeout": 10 }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/notify.sh Stop", "timeout": 10 }] }
    ]
  }
}
```

The script reads the hook's stdin JSON, pulls `cwd` (→ project name) and `message` (→ what's being asked), and pops a notification titled e.g. **"Claude 在等你 · my-project"**. Sound is set inside the script, so you don't `afplay` separately.

---

## How the Script Decides Where to Click-Focus

The hook stdin JSON has no terminal info, so the script reads `$TERM_PROGRAM` (inherited from the Claude Code process) to pick which app to activate on click:

| `$TERM_PROGRAM` | Activates | bundle id |
|-----------------|-----------|-----------|
| `iTerm.app` | iTerm2 | `com.googlecode.iterm2` |
| `ghostty` | Ghostty | `com.mitchellh.ghostty` |
| `Apple_Terminal` | Terminal | `com.apple.Terminal` |
| `WezTerm` | WezTerm | `com.github.wez.wezterm` |

Add your own terminal to the `case` block if it's missing. Find its bundle id with `osascript -e 'id of app "YourTerminal"'`.

---

## Hard Rules / Gotchas

- ⚠️ **Click-to-focus depends on the terminal, not the script.** On macOS Sequoia, **Ghostty does not reliably respond to `-activate`/`-execute`** — clicking the notification does nothing. **iTerm2 works.** This is a LaunchServices/activation quirk in the terminal app, verified by testing both with the identical command. If click-to-focus matters, run Claude Code in iTerm2.
- ⚠️ **`terminal-notifier` click only works in "Alert" style, not "Banner."** Banners auto-dismiss in a few seconds and swallow clicks. Set it to "Alert" in System Settings → Notifications → terminal-notifier.
- ⚠️ **Grant notification permission.** First run may show nothing until you allow terminal-notifier (or your terminal) in System Settings → Notifications.
- ⚠️ **`~/.claude/` hook changes may not hot-reload mid-session.** The settings watcher only watches directories that had a settings file at session start. After editing, open `/hooks` once to reload, or just start a fresh session.
- ⚠️ **Whitelisting all tools silences `Notification`.** See "The One Thing People Get Wrong." If you hear nothing, this is almost always why.
- ⚠️ **Always use absolute paths in the script** (`/opt/homebrew/bin/terminal-notifier`, `/opt/homebrew/bin/jq`). Hooks run with a minimal environment; relying on `$PATH` is a common silent failure.

---

## Verifying It Works

Pipe a fake hook payload directly to the script — no need to trigger a real prompt:

```bash
# Simulate a permission prompt
echo '{"cwd":"/Users/me/projects/demo","message":"Claude needs your permission to use Bash"}' \
  | ~/.claude/hooks/notify.sh Notification

# Simulate turn-end
echo '{"cwd":"/Users/me/projects/demo","message":"Response complete"}' \
  | ~/.claude/hooks/notify.sh Stop
```

You should get two notifications with the project name "demo" in the title, different sounds, and (in iTerm2) click-to-focus. Then validate the JSON wiring:

```bash
jq -e '.hooks.Stop[].hooks[].command' ~/.claude/settings.json
jq -e '.hooks.Notification[].hooks[].command' ~/.claude/settings.json
```

---

## Anti-Patterns

| Don't | Do instead |
|-------|-----------|
| Assume the hook is broken because you hear nothing | Check whether the command is whitelisted — `Notification` needs a real block to fire |
| Use the same sound for both events | Distinct sounds (Glass vs Hero) so you know which without looking |
| Hardcode one terminal's bundle id | Read `$TERM_PROGRAM` and map it, so it follows you across terminals |
| Rely on `$PATH` in the hook command | Absolute paths to `terminal-notifier` and `jq` |
| Expect Ghostty click-to-focus to work on Sequoia | Run in iTerm2 if click matters, or accept sound+popup only |
| `afplay` AND call the script (double sound) | Let the script own the sound via `-sound` |
| Edit settings and expect instant effect | Open `/hooks` to reload, or start a fresh session |
