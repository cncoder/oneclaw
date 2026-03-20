#!/bin/bash
# cc-send.sh — Send a message to a Claude Code tmux session
#
# Session resolution (3-level fallback):
#   1. --session <name>             → Exact tmux session
#   2. /tmp/cc-active-tab           → Most recently launched (from cc-start.sh)
#   3. Last cc-* session found      → Fallback
#
# Usage:
#   cc-send.sh "your task instruction"
#   cc-send.sh --session cc-daily "your task instruction"
#   echo "instruction" | cc-send.sh

set -euo pipefail

ACTIVE_TAB_FILE="/tmp/cc-active-tab"
TARGET_SESSION=""

# Parse arguments
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
    echo "❌ No message content" >&2
    exit 1
fi

# === Session resolution ===

# Priority 1: --session argument
if [ -n "$TARGET_SESSION" ]; then
    if ! tmux has-session -t "$TARGET_SESSION" 2>/dev/null; then
        echo "❌ tmux session '$TARGET_SESSION' does not exist" >&2
        echo "   Available: $(tmux ls -F '#{session_name}' 2>/dev/null | grep '^cc-' | tr '\n' ' ')" >&2
        exit 2
    fi
    echo "📍 Using specified session: $TARGET_SESSION"
fi

# Priority 2: /tmp/cc-active-tab
if [ -z "$TARGET_SESSION" ] && [ -f "$ACTIVE_TAB_FILE" ]; then
    # shellcheck source=/dev/null
    source "$ACTIVE_TAB_FILE" 2>/dev/null || true
    if [ -n "${SESSION_NAME:-}" ]; then
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            TARGET_SESSION="$SESSION_NAME"
            echo "📍 Found session from active tab: $TARGET_SESSION"
        else
            echo "⚠️  Session '$SESSION_NAME' from active tab no longer exists, falling back" >&2
        fi
    fi
fi

# Priority 3: last cc-* session
if [ -z "$TARGET_SESSION" ]; then
    TARGET_SESSION=$(tmux ls -F '#{session_name}' 2>/dev/null | grep '^cc-' | tail -1 || true)
    if [ -z "$TARGET_SESSION" ]; then
        echo "❌ No cc-* tmux sessions found" >&2
        echo "   Start one first: cc-start.sh <task-name>" >&2
        exit 2
    fi
    echo "📍 Fallback to last CC session: $TARGET_SESSION"
fi

# === Send message ===
# Claude Code TUI: send text content, then press Enter to submit
tmux send-keys -t "$TARGET_SESSION" -l "$MSG"
sleep 0.5
tmux send-keys -t "$TARGET_SESSION" Enter

echo "✅ Sent to session $TARGET_SESSION"
