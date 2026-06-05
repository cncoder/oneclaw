#!/bin/bash
# Claude Code 通知 hook：弹 macOS 通知，显示「哪个项目 + 谁在等你 + 干嘛」
# 用法：在 settings.json 里把 Notification / Stop 的 command 指向本脚本，
#       并把事件名作为第一个参数传入，例如：notify.sh Notification

EVENT="${1:-Unknown}"
TN="/opt/homebrew/bin/terminal-notifier"
JQ="/opt/homebrew/bin/jq"

# 读取 hook 传入的 stdin JSON
INPUT="$(cat)"

# 解析字段（缺失时给默认值）
CWD="$(printf '%s' "$INPUT" | "$JQ" -r '.cwd // empty' 2>/dev/null)"
MSG="$(printf '%s' "$INPUT" | "$JQ" -r '.message // empty' 2>/dev/null)"
PROJECT="$(basename "${CWD:-未知项目}")"

# 自动识别当前终端 → 决定点击通知时激活哪个 app
# TERM_PROGRAM 由终端注入；hook 进程继承 Claude Code 的环境
case "$TERM_PROGRAM" in
  iTerm.app)  ACTIVATE="com.googlecode.iterm2" ;;
  ghostty)    ACTIVATE="com.mitchellh.ghostty" ;;
  Apple_Terminal) ACTIVATE="com.apple.Terminal" ;;
  WezTerm)    ACTIVATE="com.github.wez.wezterm" ;;
  *)          ACTIVATE="com.googlecode.iterm2" ;;  # 识别不出时默认 iTerm2
esac

# 按事件类型决定标题、正文、声音
case "$EVENT" in
  Notification)
    TITLE="Claude 在等你 · ${PROJECT}"
    SUBTITLE="需要你回应"
    BODY="${MSG:-有一个权限请求或问题在等你}"
    SOUND="Glass"
    ;;
  Stop)
    TITLE="Claude 说完了 · ${PROJECT}"
    SUBTITLE="这一轮结束"
    BODY="${MSG:-回合结束，等你下一步}"
    SOUND="Hero"
    ;;
  *)
    TITLE="Claude · ${PROJECT}"
    SUBTITLE="$EVENT"
    BODY="${MSG:-$EVENT}"
    SOUND="Glass"
    ;;
esac

# 弹通知：同时给 -activate 和 -execute 双保险
"$TN" \
  -title "$TITLE" \
  -subtitle "$SUBTITLE" \
  -message "$BODY" \
  -sound "$SOUND" \
  -activate "$ACTIVATE" \
  >/dev/null 2>&1 || true

exit 0
