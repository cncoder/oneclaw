#!/bin/bash
# cc-start.sh — Launch a Claude Code session in tmux
#
# Each CC task gets its own tmux session (cc-{task}), tracked via
# /tmp/cc-active-tab so cc-send.sh and cc-read.sh can find it.
#
# Usage:
#   cc-start.sh <task-name> [working-dir]
#   cc-start.sh daily-digest
#   cc-start.sh tts-fix ~/projects/my-app

set -euo pipefail

TASK_NAME="${1:?Usage: cc-start.sh <task-name> [working-dir]}"
WORK_DIR="${2:-$(pwd)}"
SESSION_NAME="cc-${TASK_NAME}"
ACTIVE_TAB_FILE="/tmp/cc-active-tab"
TABS_REGISTRY="/tmp/cc-tabs.json"

# Validate working directory
if [ ! -d "$WORK_DIR" ]; then
    echo "❌ Working directory does not exist: $WORK_DIR" >&2
    exit 1
fi

# Kill existing session with same name
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "⚠️  Session '$SESSION_NAME' already exists, killing and recreating"
    tmux kill-session -t "$SESSION_NAME"
fi

# Create new tmux session (detached)
tmux new-session -d -s "$SESSION_NAME" -c "$WORK_DIR"
tmux rename-window -t "$SESSION_NAME" "$TASK_NAME"

# Launch Claude Code
tmux send-keys -t "$SESSION_NAME" "claude --dangerously-skip-permissions" Enter

# Write active tab file (used by cc-send.sh / cc-read.sh)
cat > "$ACTIVE_TAB_FILE" << EOF
# Most recently launched Claude Code session (auto-generated)
SESSION_NAME=${SESSION_NAME}
TASK_NAME=${TASK_NAME}
WORK_DIR=${WORK_DIR}
STARTED_AT=$(date +%Y-%m-%dT%H:%M:%S)
PID=$$
EOF

# Append to tabs registry
echo "{\"session\":\"${SESSION_NAME}\",\"task\":\"${TASK_NAME}\",\"dir\":\"${WORK_DIR}\",\"started\":\"$(date +%Y-%m-%dT%H:%M:%S)\"}" >> "$TABS_REGISTRY"

echo "✅ New CC tmux session started"
echo "   Session: ${SESSION_NAME}"
echo "   Dir:     ${WORK_DIR}"
echo ""
echo "Attach: tmux attach -t ${SESSION_NAME}"
echo "List:   tmux ls"
