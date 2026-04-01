#!/bin/bash
# cc-read.sh — Read terminal output from a Claude Code tmux session
#
# Captures tmux pane content with ANSI escape stripping (on by default).
# The --status flag analyzes recent output to detect CC state:
#   idle / working / waiting / error / bootstrapping
#
# Usage:
#   cc-read.sh                       # Auto-locate, last 50 lines, ANSI stripped
#   cc-read.sh --session cc-auth     # Specific session
#   cc-read.sh --lines 100           # Last 100 lines
#   cc-read.sh --full                # Full scrollback
#   cc-read.sh --raw                 # Keep ANSI escapes (for debugging)
#   cc-read.sh --status              # Return only the status string

set -euo pipefail

ACTIVE_TAB_FILE="/tmp/cc-active-tab"
TARGET_SESSION=""
LINES=50
FULL=false
STRIP_ANSI=true
STATUS_ONLY=false

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
        --raw)
            STRIP_ANSI=false
            shift
            ;;
        --status)
            STATUS_ONLY=true
            LINES=20
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# === Session resolution (same logic as cc-send.sh) ===

if [ -n "$TARGET_SESSION" ]; then
    if ! tmux has-session -t "$TARGET_SESSION" 2>/dev/null; then
        echo "Error: tmux session '$TARGET_SESSION' does not exist" >&2
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
        echo "Error: no cc-* tmux session found" >&2
        exit 2
    fi
fi

# === Capture output ===

capture_output() {
    if $FULL; then
        tmux capture-pane -t "$TARGET_SESSION" -p -S -
    else
        tmux capture-pane -t "$TARGET_SESSION" -p -S "-${LINES}"
    fi
}

strip_ansi() {
    # Strip ANSI escape sequences: CSI, CSI with ?, OSC, charset selection, SI
    sed 's/\x1b\[\?[0-9;]*[a-zA-Z]//g; s/\x1b\[[0-9;]*[a-zA-Z]//g; s/\x1b\][^\x07]*\x07//g; s/\x1b[()][0-9A-Z]//g; s/\x0f//g'
}

if $STATUS_ONLY; then
    OUTPUT=$(capture_output | strip_ansi)
    TAIL=$(echo "$OUTPUT" | sed '/^[[:space:]]*$/d' | tail -5)

    if echo "$TAIL" | grep -qE '❯[[:space:]]*$'; then
        echo "idle"
    elif echo "$TAIL" | grep -qi 'bootstrapping\|cogitating\|compacting'; then
        echo "bootstrapping"
    elif echo "$TAIL" | grep -qi 'enter to confirm\|yes.*no\|allow\|deny'; then
        echo "waiting"
    elif echo "$TAIL" | grep -qi 'error\|failed\|traceback\|exception'; then
        echo "error"
    else
        echo "working"
    fi
    exit 0
fi

if $STRIP_ANSI; then
    capture_output | strip_ansi
else
    capture_output
fi
