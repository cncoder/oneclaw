#!/bin/bash
# cc-read.sh — Read terminal output from a Claude Code tmux session
#
# Uses tmux capture-pane to grab terminal content.
# Same 3-level session resolution as cc-send.sh.
#
# Usage:
#   cc-read.sh                       # Auto-locate, last 50 lines
#   cc-read.sh --session cc-daily    # Specific session
#   cc-read.sh --lines 100           # Last 100 lines
#   cc-read.sh --full                # Full scrollback

set -euo pipefail

ACTIVE_TAB_FILE="/tmp/cc-active-tab"
TARGET_SESSION=""
LINES=50
FULL=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --session)
            TARGET_SESSION="$2"
            shift 2
            ;;
        --lines)
            LINES="$2"
            shift 2
            ;;
        --full)
            FULL=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# === Session resolution (same as cc-send.sh) ===

if [ -n "$TARGET_SESSION" ]; then
    if ! tmux has-session -t "$TARGET_SESSION" 2>/dev/null; then
        echo "❌ tmux session '$TARGET_SESSION' does not exist" >&2
        exit 2
    fi
fi

if [ -z "$TARGET_SESSION" ] && [ -f "$ACTIVE_TAB_FILE" ]; then
    # shellcheck source=/dev/null
    source "$ACTIVE_TAB_FILE" 2>/dev/null || true
    if [ -n "${SESSION_NAME:-}" ]; then
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            TARGET_SESSION="$SESSION_NAME"
        fi
    fi
fi

if [ -z "$TARGET_SESSION" ]; then
    TARGET_SESSION=$(tmux ls -F '#{session_name}' 2>/dev/null | grep '^cc-' | tail -1 || true)
    if [ -z "$TARGET_SESSION" ]; then
        echo "❌ No cc-* tmux sessions found" >&2
        exit 2
    fi
fi

# === Read terminal output ===

if $FULL; then
    tmux capture-pane -t "$TARGET_SESSION" -p -S -
else
    tmux capture-pane -t "$TARGET_SESSION" -p -S "-${LINES}"
fi
