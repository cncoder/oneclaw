#!/bin/bash
# cc-start.sh — 在 tmux 中启动 Claude Code session
#
# 从 iTerm2 osascript 迁移到 tmux（2026-03-15）
# 优化: 加 --bare 提速、--max-turns 防无限循环、终端 reset 防按键残留（2026-03-31）
# 核心：每个 CC 任务一个 tmux session，通过 session name 唯一标识。
#
# 用法:
#   cc-start.sh <task-name> [working-dir] [--max-turns N] [--no-bare]
#   cc-start.sh daily-digest
#   cc-start.sh tts-fix ~/Documents/ccdev/local-mactts
#   cc-start.sh big-task ~/project --max-turns 50
#
# 副作用: 写 /tmp/cc-active-tab（兼容旧接口）

set -euo pipefail

# 默认参数
MAX_TURNS=200
USE_BARE=true
FOREGROUND=false
POSITIONAL_ARGS=()

# 解析参数
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

TASK_NAME="${POSITIONAL_ARGS[0]:?用法: cc-start.sh <task-name> [working-dir] [--max-turns N] [--no-bare]}"
WORK_DIR="${POSITIONAL_ARGS[1]:-$HOME/.openclaw/workspace}"
SESSION_NAME="cc-${TASK_NAME}"
ACTIVE_TAB_FILE="/tmp/cc-active-tab"
TABS_REGISTRY="/tmp/cc-tabs.json"

# 验证工作目录存在
if [ ! -d "$WORK_DIR" ]; then
    echo "❌ 工作目录不存在: $WORK_DIR" >&2
    exit 1
fi

# 如果同名 session 已存在，先 kill
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "⚠️ session '$SESSION_NAME' 已存在，kill 并重建"
    tmux kill-session -t "$SESSION_NAME"
fi

# 创建新 tmux session（后台模式）
tmux new-session -d -s "$SESSION_NAME" -c "$WORK_DIR"

# 设置 session 窗口标题
tmux rename-window -t "$SESSION_NAME" "$TASK_NAME"

# 构建 Claude Code 启动命令
CC_CMD="claude --dangerously-skip-permissions --max-turns ${MAX_TURNS}"
if $USE_BARE; then
    CC_CMD="${CC_CMD} --bare"
fi

# 启动 Claude Code
tmux send-keys -t "$SESSION_NAME" "$CC_CMD" Enter

# 写入 active tab 文件（兼容 cc-send.sh / cc-read.sh）
cat > "$ACTIVE_TAB_FILE" << EOF
# 最近启动的 Claude Code session（自动生成，勿手动编辑）
SESSION_NAME=${SESSION_NAME}
TASK_NAME=${TASK_NAME}
WORK_DIR=${WORK_DIR}
MAX_TURNS=${MAX_TURNS}
BARE=${USE_BARE}
STARTED_AT=$(date +%Y-%m-%dT%H:%M:%S)
PID=$$
EOF

# 更新 tabs 注册表
echo "{\"session\":\"${SESSION_NAME}\",\"task\":\"${TASK_NAME}\",\"dir\":\"${WORK_DIR}\",\"maxTurns\":${MAX_TURNS},\"bare\":${USE_BARE},\"started\":\"$(date +%Y-%m-%dT%H:%M:%S)\"}" >> "$TABS_REGISTRY"

echo "✅ 新 CC tmux session 已启动"
echo "   Session: ${SESSION_NAME}"
echo "   Dir: ${WORK_DIR}"
echo "   Max turns: ${MAX_TURNS}"
echo "   Bare mode: ${USE_BARE}"
echo ""
echo "查看: tmux attach -t ${SESSION_NAME}"
echo "列表: tmux ls"

# 前台模式：自动 attach 到 session
if $FOREGROUND; then
    echo "🖥 进入前台模式（Ctrl+B, D 退出回后台）"
    exec tmux attach -t "$SESSION_NAME"
fi
