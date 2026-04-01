#!/bin/bash
# cc-start.sh — Launch a Claude Code session inside tmux
#
# Each CC task gets its own tmux session, identified by session name.
# The active session is tracked in /tmp/cc-active-tab for cc-send.sh / cc-read.sh.
#
# Usage:
#   cc-start.sh <task-name> [working-dir] [--max-turns N] [--no-bare] [--foreground]
#   cc-start.sh daily-digest
#   cc-start.sh tts-fix ~/projects/my-app
#   cc-start.sh big-task ~/project --max-turns 50
#   cc-start.sh complex-task ~/project --no-bare

set -euo pipefail

MAX_TURNS=200
USE_BARE=true
FOREGROUND=false
POSITIONAL_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-turns)
            MAX_TURNS="$2"
            shift 2
            ;;
        --no-bare)
            USE_BARE=false
            shift
            ;;
        --foreground|-f)
            FOREGROUND=true
            shift
            ;;
        *)
            POSITIONAL_ARGS+=("$1")
            shift
            ;;
    esac
done

TASK_NAME="${POSITIONAL_ARGS[0]:?Usage: cc-start.sh <task-name> [working-dir] [--max-turns N] [--no-bare]}"
WORK_DIR="${POSITIONAL_ARGS[1]:-$(pwd)}"
SESSION_NAME="cc-${TASK_NAME}"
ACTIVE_TAB_FILE="/tmp/cc-active-tab"
TABS_REGISTRY="/tmp/cc-tabs.json"

if [ ! -d "$WORK_DIR" ]; then
    echo "Error: working directory does not exist: $WORK_DIR" >&2
    exit 1
fi

# Kill existing session with same name (intentional: fresh start)
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "Warning: session '$SESSION_NAME' already exists, replacing it"
    tmux kill-session -t "$SESSION_NAME"
fi

tmux new-session -d -s "$SESSION_NAME" -c "$WORK_DIR"
tmux rename-window -t "$SESSION_NAME" "$TASK_NAME"

# Build Claude Code command
CC_CMD="claude --dangerously-skip-permissions --max-turns ${MAX_TURNS}"
if $USE_BARE; then
    CC_CMD="${CC_CMD} --bare"
fi

tmux send-keys -t "$SESSION_NAME" "$CC_CMD" Enter

# Track active session (used by cc-send.sh / cc-read.sh)
cat > "$ACTIVE_TAB_FILE" << EOF
# Most recently launched Claude Code session (auto-generated, do not edit)
SESSION_NAME=${SESSION_NAME}
TASK_NAME=${TASK_NAME}
WORK_DIR=${WORK_DIR}
MAX_TURNS=${MAX_TURNS}
BARE=${USE_BARE}
STARTED_AT=$(date +%Y-%m-%dT%H:%M:%S)
EOF

# Append to session registry (one JSON line per session)
echo "{\"session\":\"${SESSION_NAME}\",\"task\":\"${TASK_NAME}\",\"dir\":\"${WORK_DIR}\",\"maxTurns\":${MAX_TURNS},\"bare\":${USE_BARE},\"started\":\"$(date +%Y-%m-%dT%H:%M:%S)\"}" >> "$TABS_REGISTRY"

echo "CC session started"
echo "  Session:   ${SESSION_NAME}"
echo "  Directory: ${WORK_DIR}"
echo "  Max turns: ${MAX_TURNS}"
echo "  Bare mode: ${USE_BARE}"
echo ""
echo "  Attach: tmux attach -t ${SESSION_NAME}"
echo "  List:   tmux ls"

if $FOREGROUND; then
    echo "Entering foreground mode (Ctrl+B, D to detach)"
    exec tmux attach -t "$SESSION_NAME"
fi
