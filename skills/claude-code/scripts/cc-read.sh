#!/bin/bash
# cc-read.sh — 读取 Claude Code tmux session 终端输出
#
# 从 iTerm2 osascript 迁移到 tmux（2026-03-15）
# 优化: ANSI strip + 状态检测（2026-03-31）
#   - capture-pane 输出包含 ANSI 转义码，干扰 agent 解析
#   - 加 --strip 自动过滤（默认开启）
#   - 加 --status 只返回 CC 当前状态（idle/working/waiting/error/bootstrapping）
#
# 用法:
#   cc-read.sh                       # 自动定位，ANSI stripped
#   cc-read.sh --session cc-daily    # 精确指定 session
#   cc-read.sh --lines 100           # 最近 100 行（默认 50）
#   cc-read.sh --full                # 捕获完整 scrollback
#   cc-read.sh --raw                 # 不过滤 ANSI（调试用）
#   cc-read.sh --status              # 只返回状态字符串

set -euo pipefail

ACTIVE_TAB_FILE="/tmp/cc-active-tab"
TARGET_SESSION=""
LINES=50
FULL=false
STRIP_ANSI=true
STATUS_ONLY=false

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tab)
            echo "⚠️ --tab 已废弃（tmux 模式），使用 --session" >&2
            shift 2
            ;;
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

# === Session 定位逻辑（与 cc-send.sh 相同） ===

# 优先级 1: --session 参数
if [ -n "$TARGET_SESSION" ]; then
    if ! tmux has-session -t "$TARGET_SESSION" 2>/dev/null; then
        echo "❌ tmux session '$TARGET_SESSION' 不存在" >&2
        exit 2
    fi
fi

# 优先级 2: /tmp/cc-active-tab 文件
if [ -z "$TARGET_SESSION" ] && [ -f "$ACTIVE_TAB_FILE" ]; then
    source "$ACTIVE_TAB_FILE" 2>/dev/null || true
    if [ -n "${SESSION_NAME:-}" ]; then
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            TARGET_SESSION="$SESSION_NAME"
        fi
    fi
fi

# 优先级 3: 找最后一个 cc-* session
if [ -z "$TARGET_SESSION" ]; then
    TARGET_SESSION=$(tmux ls -F '#{session_name}' 2>/dev/null | grep '^cc-' | tail -1 || true)
    if [ -z "$TARGET_SESSION" ]; then
        echo "❌ 没找到任何 cc-* tmux session" >&2
        exit 2
    fi
fi

# === 读取终端输出 ===

capture_output() {
    if $FULL; then
        tmux capture-pane -t "$TARGET_SESSION" -p -S -
    else
        tmux capture-pane -t "$TARGET_SESSION" -p -S "-${LINES}"
    fi
}

strip_ansi() {
    # 过滤 ANSI 转义序列: CSI sequences, OSC sequences, 简单转义
    sed 's/\x1b\[[0-9;]*[a-zA-Z]//g; s/\x1b\][^\x07]*\x07//g; s/\x1b[()][0-9A-Z]//g; s/\x1b\[?[0-9;]*[a-zA-Z]//g; s/\x0f//g'
}

if $STATUS_ONLY; then
    # 状态检测模式：分析最近输出判断 CC 状态
    OUTPUT=$(capture_output | strip_ansi)

    # 取最后几行非空内容
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

# 正常输出模式
if $STRIP_ANSI; then
    capture_output | strip_ansi
else
    capture_output
fi
