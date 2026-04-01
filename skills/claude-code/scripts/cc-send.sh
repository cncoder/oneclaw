#!/bin/bash
# cc-send.sh — Send a message to a Claude Code tmux session
#
# Uses tmux load-buffer + paste-buffer instead of send-keys -l.
# Reason: send-keys -l breaks on quotes, $, backslashes, and long text.
# load-buffer pipes raw content via temp file, bypassing terminal escaping.
#
# Session resolution (3-level fallback):
#   1. --session <name>             → exact tmux session
#   2. /tmp/cc-active-tab           → most recently launched session
#   3. last cc-* session found      → fallback
#
# Usage:
#   cc-send.sh "implement the auth middleware"
#   cc-send.sh --session cc-auth "add rate limiting"
#   echo "instructions" | cc-send.sh

set -euo pipefail

ACTIVE_TAB_FILE="/tmp/cc-active-tab"
TARGET_SESSION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --session)
            TARGET_SESSION="$2"
            shift 2
            ;;
        *)
            break
            ;;
    esac
done

# Read message from args or stdin
if [ $# -gt 0 ]; then
    MSG="$*"
else
    MSG=$(cat)
fi

if [ -z "$MSG" ]; then
    echo "Error: no message provided" >&2
    exit 1
fi

# === Session resolution ===

# Priority 1: --session flag
if [ -n "$TARGET_SESSION" ]; then
    if ! tmux has-session -t "$TARGET_SESSION" 2>/dev/null; then
        echo "Error: tmux session '$TARGET_SESSION' does not exist" >&2
        echo "  Available sessions: $(tmux ls -F '#{session_name}' 2>/dev/null | grep '^cc-' | tr '\n' ' ')" >&2
        exit 2
    fi
fi

# Priority 2: /tmp/cc-active-tab
if [ -z "$TARGET_SESSION" ] && [ -f "$ACTIVE_TAB_FILE" ]; then
    # shellcheck source=/dev/null
    source "$ACTIVE_TAB_FILE" 2>/dev/null || true
    if [ -n "${SESSION_NAME:-}" ]; then
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            TARGET_SESSION="$SESSION_NAME"
        else
            echo "Warning: recorded session '$SESSION_NAME' no longer exists, falling back" >&2
        fi
    fi
fi

# Priority 3: last cc-* session
if [ -z "$TARGET_SESSION" ]; then
    TARGET_SESSION=$(tmux ls -F '#{session_name}' 2>/dev/null | grep '^cc-' | tail -1 || true)
    if [ -z "$TARGET_SESSION" ]; then
        echo "Error: no cc-* tmux session found" >&2
        echo "  Start one first: cc-start.sh <task-name>" >&2
        exit 2
    fi
fi

# === Send message ===
# Use load-buffer + paste-buffer for reliable delivery of arbitrary text

TMPFILE=$(mktemp /tmp/cc-send-XXXXXX)
trap 'rm -f "$TMPFILE"' EXIT

printf '%s' "$MSG" > "$TMPFILE"

tmux load-buffer "$TMPFILE"
tmux paste-buffer -t "$TARGET_SESSION" -d
# Brief pause to let paste complete before sending Enter.
# Without this, Enter can arrive before paste finishes on slow systems.
sleep 0.3
tmux send-keys -t "$TARGET_SESSION" Enter

echo "Sent to $TARGET_SESSION (${#MSG} chars)"
