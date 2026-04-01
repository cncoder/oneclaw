#!/bin/bash
# cc-send.sh — 向 Claude Code tmux session 发送消息
#
# 从 iTerm2 osascript 迁移到 tmux（2026-03-15）
# 优化: 用 load-buffer + paste-buffer 替代 send-keys -l（2026-03-31）
#   - send-keys -l 对长文本和特殊字符（引号、反斜杠、$）不可靠
#   - load-buffer 通过临时文件传递，完全绕过终端转义问题
#
# Session 定位优先级（三级 fallback）：
#   1. --session <name>             → 精确指定 tmux session
#   2. /tmp/cc-active-tab           → cc-start.sh 记录的最近启动 session
#   3. 遍历找最后一个 cc-* session  → 兜底
#
# 用法:
#   cc-send.sh "你的任务指令"                      # 自动定位
#   cc-send.sh --session cc-daily "你的任务指令"    # 精确指定 session
#   echo "指令" | cc-send.sh                       # stdin 模式

set -euo pipefail

ACTIVE_TAB_FILE="/tmp/cc-active-tab"
TARGET_SESSION=""

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tab)
            # 兼容旧接口，忽略 tab 号
            echo "⚠️ --tab 已废弃（tmux 模式），使用 --session" >&2
            shift 2
            ;;
        --session)
            TARGET_SESSION="$2"
            shift 2
            ;;
        *)
            break
            ;;
    esac
done

# 读取消息
if [ $# -gt 0 ]; then
    MSG="$*"
else
    MSG=$(cat)
fi

if [ -z "$MSG" ]; then
    echo "❌ 没有消息内容" >&2
    exit 1
fi

# === Session 定位逻辑 ===

# 优先级 1: --session 参数
if [ -n "$TARGET_SESSION" ]; then
    if ! tmux has-session -t "$TARGET_SESSION" 2>/dev/null; then
        echo "❌ tmux session '$TARGET_SESSION' 不存在" >&2
        echo "   可用 sessions: $(tmux ls -F '#{session_name}' 2>/dev/null | grep '^cc-' | tr '\n' ' ')" >&2
        exit 2
    fi
    echo "📍 精确指定 session: $TARGET_SESSION"
fi

# 优先级 2: /tmp/cc-active-tab 文件
if [ -z "$TARGET_SESSION" ] && [ -f "$ACTIVE_TAB_FILE" ]; then
    # shellcheck source=/dev/null
    source "$ACTIVE_TAB_FILE" 2>/dev/null || true
    if [ -n "${SESSION_NAME:-}" ]; then
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            TARGET_SESSION="$SESSION_NAME"
            echo "📍 从 active tab 文件找到 session: $TARGET_SESSION"
        else
            echo "⚠️ active tab 文件记录的 session '$SESSION_NAME' 已不存在，fallback" >&2
        fi
    fi
fi

# 优先级 3: 找最后一个 cc-* session
if [ -z "$TARGET_SESSION" ]; then
    TARGET_SESSION=$(tmux ls -F '#{session_name}' 2>/dev/null | grep '^cc-' | tail -1 || true)
    if [ -z "$TARGET_SESSION" ]; then
        echo "❌ 没找到任何 cc-* tmux session" >&2
        echo "   请先运行: cc-start.sh <task-name>" >&2
        exit 2
    fi
    echo "📍 fallback 找到最后一个 CC session: $TARGET_SESSION"
fi

# === 发送消息 ===
# 用 tmux load-buffer + paste-buffer 替代 send-keys -l
# 原因：send-keys -l 对引号、$、反斜杠、长文本都有问题
# load-buffer 通过临时文件传递原始内容，完全绕过终端转义

TMPFILE=$(mktemp /tmp/cc-send-XXXXXX)
trap 'rm -f "$TMPFILE"' EXIT

# 写入消息到临时文件（不含换行，Enter 单独发）
printf '%s' "$MSG" > "$TMPFILE"

# 加载到 tmux buffer 并粘贴到目标 pane
tmux load-buffer "$TMPFILE"
tmux paste-buffer -t "$TARGET_SESSION" -d
sleep 0.5
tmux send-keys -t "$TARGET_SESSION" Enter

echo "✅ 已发送到 session $TARGET_SESSION (${#MSG} chars)"
