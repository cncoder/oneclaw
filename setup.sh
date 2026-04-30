#!/bin/bash
# ============================================================================
# OnClick-Claw: One-Click Setup for Claude Code + OpenClaw on Mac
# ============================================================================
# Usage: curl -fsSL https://raw.githubusercontent.com/cncoder/oneclaw/main/setup.sh | bash
#   or:  bash setup.sh
#
# What it does:
#   1. Install Claude Code (no dependencies — your AI assistant for troubleshooting)
#   2. Collect AWS credentials + configure Claude Code for Bedrock
#   3. Install fnm (Fast Node Manager) + Node.js
#   4. Install pnpm, uv/uvx, AWS CLI
#   5. Install OpenClaw
#   6. Configure OpenClaw (Bedrock, browser, agents)
#   7. Set up Guardian watchdog + LaunchAgents (auto-start on boot)
#   8. Generate a CLAUDE.md for OpenClaw initialization
#
# Requirements: macOS, internet connection
# ============================================================================

set -euo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# --- Helpers ---
info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step()    { echo -e "\n${CYAN}${BOLD}=== Step $1: $2 ===${NC}\n"; }

# --- launchctl modern API helpers (bootstrap/bootout for macOS 13+, fallback to load/unload) ---
_launchctl_has_bootstrap() {
    # macOS 13+ (Ventura) supports bootstrap/bootout
    local major
    major=$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)
    [ "${major:-0}" -ge 13 ]
}

GUI_UID=$(id -u)

la_load() {
    local plist="$1"
    local label
    label=$(basename "$plist" .plist)
    if _launchctl_has_bootstrap; then
        launchctl bootstrap "gui/${GUI_UID}" "$plist" 2>/dev/null || \
            launchctl kickstart -k "gui/${GUI_UID}/${label}" 2>/dev/null || true
    else
        launchctl load "$plist" 2>/dev/null || true
    fi
}

la_unload() {
    local plist="$1"
    local label
    label=$(basename "$plist" .plist)
    if _launchctl_has_bootstrap; then
        launchctl bootout "gui/${GUI_UID}/${label}" 2>/dev/null || true
    else
        launchctl unload "$plist" 2>/dev/null || true
    fi
}

ask_secret() {
    local prompt="$1" var_name="$2" hide="${3:-false}"
    local value=""
    while [ -z "$value" ]; do
        echo -en "${YELLOW}$prompt: ${NC}"
        if [ "$hide" = "true" ]; then
            read -rs value </dev/tty
            echo ""
        else
            read -r value </dev/tty
        fi
        [ -z "$value" ] && warn "必填项，请输入内容。"
    done
    printf -v "$var_name" '%s' "$value"
}

ask_optional() {
    local prompt="$1" var_name="$2" default="$3"
    echo -en "${YELLOW}$prompt [${default}]: ${NC}"
    read -r value </dev/tty
    value="${value:-$default}"
    printf -v "$var_name" '%s' "$value"
}

check_command() {
    command -v "$1" >/dev/null 2>&1
}

# Validate AWS Access Key ID format (AKIA/ASIA prefix, 20 chars, alphanumeric)
validate_aws_ak() {
    local ak="$1"
    if [[ ! "$ak" =~ ^(AKIA|ASIA)[A-Z0-9]{16}$ ]]; then
        return 1
    fi
    return 0
}

# Validate AWS Secret Access Key format (40 chars, Base64 charset: A-Za-z0-9+/)
validate_aws_sk() {
    local sk="$1"
    if [[ ${#sk} -ne 40 ]]; then
        return 1
    fi
    if [[ ! "$sk" =~ ^[A-Za-z0-9+/]{40}$ ]]; then
        return 1
    fi
    return 0
}

# Ask for AWS Access Key ID with format validation
ask_aws_ak() {
    local var_name="$1"
    local value=""
    while true; do
        echo -en "${YELLOW}请输入 AWS Access Key ID: ${NC}"
        read -r value </dev/tty
        if [ -z "$value" ]; then
            warn "必填项，请输入内容。"
            continue
        fi
        if ! validate_aws_ak "$value"; then
            warn "格式不正确。AWS Access Key ID 应以 AKIA 或 ASIA 开头，共 20 个大写字母和数字。"
            echo -e "  示例: ${GREEN}AKIAIOSFODNN7EXAMPLE${NC}"
            echo -en "${YELLOW}重新输入？(Y/n): ${NC}"
            read -r retry </dev/tty
            [[ "$retry" =~ ^[Nn]$ ]] && break  # User insists, accept as-is
            continue
        fi
        break
    done
    printf -v "$var_name" '%s' "$value"
}

# Ask for AWS Secret Access Key with format validation
ask_aws_sk() {
    local var_name="$1"
    local value=""
    while true; do
        echo -en "${YELLOW}请输入 AWS Secret Access Key（输入时不会显示）: ${NC}"
        read -rs value </dev/tty
        echo ""
        if [ -z "$value" ]; then
            warn "必填项，请输入内容。"
            continue
        fi
        if ! validate_aws_sk "$value"; then
            warn "格式不正确。AWS Secret Access Key 应为 40 个字符（A-Z、a-z、0-9、+、/）。你输入了 ${#value} 个字符。"
            echo -en "${YELLOW}重新输入？(Y/n): ${NC}"
            read -r retry </dev/tty
            [[ "$retry" =~ ^[Nn]$ ]] && break  # User insists, accept as-is
            continue
        fi
        break
    done
    printf -v "$var_name" '%s' "$value"
}

# ============================================================================
# Pre-flight checks
# ============================================================================
echo -e "\n${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║       OnClick-Claw: One-Click Setup Script       ║"
echo "  ║     Claude Code + OpenClaw + AWS on macOS         ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check macOS
[[ "$(uname)" == "Darwin" ]] || error "This script only runs on macOS."
info "Detected: macOS $(sw_vers -productVersion) ($(uname -m))"

# ============================================================================
# Optional components — interactive toggle menu
# ============================================================================
# Defaults: all optional components OFF
INSTALL_GHOSTTY=false

# Each optional component: (variable_name  label  default)
OPTIONAL_COMPONENTS=(
    "INSTALL_GHOSTTY|Ghostty 终端配置（为 Claude Code 优化的字体/主题/快捷键）|false"
)

# Interactive menu: space to toggle, enter to confirm
show_optional_menu() {
    local num=${#OPTIONAL_COMPONENTS[@]}
    # Parse into arrays
    local -a vars=() labels=() states=()
    for entry in "${OPTIONAL_COMPONENTS[@]}"; do
        IFS='|' read -r var label default <<< "$entry"
        vars+=("$var")
        labels+=("$label")
        states+=("$default")
    done

    echo ""
    echo -e "${BOLD}可选组件（空格切换选择，回车确认）：${NC}"
    echo ""

    local current=0
    # Hide cursor
    tput civis 2>/dev/null || true

    # Draw menu
    draw_menu() {
        # Move cursor up to redraw
        for ((i=0; i<num; i++)); do
            [ "$i" -gt 0 ] && printf "\033[A"
        done
        printf "\r"
        for ((i=0; i<num; i++)); do
            local marker="  "
            [ "$current" -eq "$i" ] && marker="> "
            local check="[ ]"
            [ "${states[$i]}" = "true" ] && check="[✓]"
            if [ "$current" -eq "$i" ]; then
                printf "\033[K${CYAN}${marker}${check} ${labels[$i]}${NC}\n"
            else
                printf "\033[K${marker}${check} ${labels[$i]}\n"
            fi
        done
    }

    # Initial draw
    for ((i=0; i<num; i++)); do
        echo ""
    done
    draw_menu

    # Read keys
    while true; do
        IFS= read -rsn1 key </dev/tty || true
        case "$key" in
            ' ')  # Space: toggle
                if [ "${states[$current]}" = "true" ]; then
                    states[$current]="false"
                else
                    states[$current]="true"
                fi
                draw_menu
                ;;
            '')   # Enter: confirm
                break
                ;;
            $'\x1b')  # Arrow keys (escape sequence)
                read -rsn2 arrow </dev/tty
                case "$arrow" in
                    '[A')  # Up
                        ((current > 0)) && ((current--)) || true
                        draw_menu
                        ;;
                    '[B')  # Down
                        ((current < num-1)) && ((current++)) || true
                        draw_menu
                        ;;
                esac
                ;;
        esac
    done

    # Restore cursor
    tput cnorm 2>/dev/null || true

    # Apply selections
    for ((i=0; i<num; i++)); do
        eval "${vars[$i]}=${states[$i]}"
    done
    echo ""
}

show_optional_menu

echo ""
echo -e "${YELLOW}${BOLD}提示：${NC}安装过程需要管理员权限（sudo），请先输入你的 Mac 登录密码。"
echo -e "      密码输入时屏幕不会显示任何字符，输完按回车就行。"
echo ""

# Pre-flight sudo check — acquire sudo before anything else
if ! sudo -n true 2>/dev/null; then
    sudo -v || error "无法获取管理员权限。请确认你的账户是管理员，并输入正确的密码。"
fi
# Keep sudo alive throughout the script
(while true; do sudo -n true; sleep 50; done) 2>/dev/null &
SUDO_KEEPALIVE_PID=$!
trap 'kill $SUDO_KEEPALIVE_PID 2>/dev/null' EXIT
success "管理员权限已获取"

# ============================================================================
# Step 0.5: Xcode Command Line Tools (required for compilation tools)
# ============================================================================
if ! xcode-select -p >/dev/null 2>&1; then
    info "Installing Xcode Command Line Tools (may take a few minutes)..."
    xcode-select --install 2>/dev/null || true
    # Wait for installation to complete
    echo -e "${YELLOW}请在弹出的对话框中点击「安装」，等待安装完成后按回车继续...${NC}"
    read -r </dev/tty
    if ! xcode-select -p >/dev/null 2>&1; then
        echo ""
        echo -e "${RED}${BOLD}Xcode Command Line Tools 安装失败。${NC}"
        echo -e "${YELLOW}请手动执行以下命令，安装完成后重新运行本脚本：${NC}"
        echo ""
        echo -e "  ${CYAN}xcode-select --install${NC}"
        echo ""
        echo -e "  如果弹窗没出现，可以从 Apple 开发者网站下载："
        echo -e "  ${CYAN}https://developer.apple.com/download/more/${NC}"
        echo -e "  搜索 \"Command Line Tools\"，下载对应 macOS 版本的安装包。"
        echo ""
        exit 1
    fi
    success "Xcode Command Line Tools installed"
else
    success "Xcode Command Line Tools already installed"
fi

# ============================================================================
# Step 1: Install Claude Code (NO dependencies — install first as safety net)
# ============================================================================
step 1 "Install Claude Code"

# Claude Code install puts binary in ~/.claude/local/bin/ and updates ~/.zshrc
# We need to check multiple possible locations
CLAUDE_SEARCH_PATHS=(
    "$HOME/.claude/local/bin"
    "$HOME/.local/bin"
    "/usr/local/bin"
    "/opt/homebrew/bin"
)

find_claude() {
    for p in "${CLAUDE_SEARCH_PATHS[@]}"; do
        if [ -x "$p/claude" ]; then
            echo "$p"
            return 0
        fi
    done
    return 1
}

# Helper: ensure a PATH dir is in ~/.zshrc so new terminals can find claude
ensure_path_in_zshrc() {
    local dir="$1"
    local zshrc="$HOME/.zshrc"
    touch "$zshrc"
    # Check if this exact export already exists
    if ! grep -qF "export PATH=\"$dir:\$PATH\"" "$zshrc" 2>/dev/null && \
       ! grep -qF "export PATH=\"$dir:" "$zshrc" 2>/dev/null && \
       ! grep -qF "PATH=\"$dir:" "$zshrc" 2>/dev/null; then
        echo "" >> "$zshrc"
        echo "# Claude Code" >> "$zshrc"
        echo "export PATH=\"$dir:\$PATH\"" >> "$zshrc"
        info "已将 ${dir} 写入 ~/.zshrc（新终端窗口自动生效）"
    fi
}

if check_command claude; then
    success "Claude Code already installed: $(claude --version 2>/dev/null || echo 'installed')"
elif CLAUDE_BIN_DIR=$(find_claude); then
    export PATH="$CLAUDE_BIN_DIR:$PATH"
    ensure_path_in_zshrc "$CLAUDE_BIN_DIR"
    success "Claude Code already installed (found in $CLAUDE_BIN_DIR): $(claude --version 2>/dev/null || echo 'installed')"
else
    echo -e "${BOLD}Claude Code 是 AI 编程助手，无额外依赖，优先安装。${NC}"
    echo -e "后续步骤如果遇到问题，你可以随时${BOLD}打开新终端${NC}输入 ${GREEN}claude${NC} 让它帮你修复。\n"

    # Pre-flight: check if claude.ai is accessible from this region
    info "检测 claude.ai 网络可达性..."
    CLAUDE_PREFLIGHT=$(curl -fsSL -o /dev/null -w "%{http_code}" -m 10 "https://claude.ai/install.sh" 2>/dev/null || echo "000")
    if [ "$CLAUDE_PREFLIGHT" != "200" ]; then
        # Double-check: fetch a small chunk and look for region block signature
        CLAUDE_BODY=$(curl -fsSL -m 10 "https://claude.ai/install.sh" 2>/dev/null | head -c 2000 || true)
        if echo "$CLAUDE_BODY" | grep -qi "unavailable in region\|unavailable here\|isn.*t available"; then
            echo ""
            echo -e "${RED}${BOLD}Claude.ai 在当前网络环境下不可用（IP 属地受限）。${NC}"
            echo ""
            echo -e "  检测到 claude.ai 返回 ${YELLOW}\"App unavailable in region\"${NC}，"
            echo -e "  说明你的网络出口 IP 不在 Claude 服务的可用区域内。"
            echo ""
            echo -e "  ${BOLD}解决方法：${NC}"
            echo -e "  配置终端代理，确保出口 IP 在支持的区域（如美国、日本等），然后重新运行本脚本。"
            echo ""

            # Auto-detect local proxy: scan localhost LISTEN ports, test which can reach Google
            PROXY_FOUND=false
            SUGGESTED_PORT=""
            info "正在探测本地代理端口（可能需要几秒）..."

            # Collect unique localhost LISTEN ports (skip well-known non-proxy: 22,53,80,443,3000,3306,5432,8443,9222,18789...)
            LOCAL_PORTS=$(lsof -i -sTCP:LISTEN -P -n 2>/dev/null \
                | awk '$5=="IPv4" || $5=="IPv6" {print $9}' \
                | grep -E '127\.0\.0\.1:|localhost:|\*:' \
                | grep -oE '[0-9]+$' \
                | sort -un \
                | grep -vE '^(22|53|80|443|3000|3306|5432|5900|8443|9222|18789)$' \
                || true)

            for port in $LOCAL_PORTS; do
                # Try using this port as HTTP proxy to reach Google (2s timeout)
                if curl -s -o /dev/null -m 2 -w "%{http_code}" --proxy "http://127.0.0.1:${port}" "https://www.google.com" 2>/dev/null | grep -qE "^(200|301|302)"; then
                    PROXY_FOUND=true
                    SUGGESTED_PORT="$port"
                    success "发现可用代理端口: ${port}"
                    break
                fi
            done

            if [ "$PROXY_FOUND" = true ]; then
                echo ""
                echo -e "  ${BOLD}在终端执行以下命令设置代理，然后重新运行本脚本：${NC}"
                echo ""
                echo -e "    ${CYAN}export http_proxy=http://127.0.0.1:${SUGGESTED_PORT}${NC}"
                echo -e "    ${CYAN}export https_proxy=http://127.0.0.1:${SUGGESTED_PORT}${NC}"
            else
                echo -e "  ${YELLOW}未检测到可用的本地代理。请先打开代理软件，然后执行：${NC}"
                echo ""
                echo -e "    ${CYAN}export http_proxy=http://127.0.0.1:<代理端口>${NC}"
                echo -e "    ${CYAN}export https_proxy=http://127.0.0.1:<代理端口>${NC}"
            fi

            echo ""
            echo -e "  ${YELLOW}提示：可以先用浏览器打开 ${CYAN}https://claude.ai${YELLOW} 测试是否能正常访问。${NC}"
            echo ""
            exit 1
        fi
        # Not a region block, might be a transient network issue
        warn "claude.ai 返回 HTTP ${CLAUDE_PREFLIGHT}，可能是临时网络问题，尝试继续安装..."
    fi

    info "Installing Claude Code..."
    if curl -fsSL https://claude.ai/install.sh | bash; then
        # Reload PATH: source shell profile to pick up changes made by `claude install`
        if [ -f "$HOME/.zshrc" ]; then
            source "$HOME/.zshrc" 2>/dev/null || true
        fi
        # Also explicitly add known locations
        for p in "${CLAUDE_SEARCH_PATHS[@]}"; do
            [[ ":$PATH:" != *":$p:"* ]] && export PATH="$p:$PATH"
        done

        if check_command claude; then
            success "Claude Code installed: $(claude --version 2>/dev/null || echo 'installed')"
        elif CLAUDE_BIN_DIR=$(find_claude); then
            export PATH="$CLAUDE_BIN_DIR:$PATH"
            success "Claude Code installed (at $CLAUDE_BIN_DIR): $(claude --version 2>/dev/null || echo 'installed')"
        else
            echo ""
            echo -e "${YELLOW}${BOLD}Claude Code 安装可能已成功，但当前终端找不到 claude 命令。${NC}"
            echo -e "请${BOLD}关闭终端，重新打开一个新终端${NC}，然后重新运行本脚本。"
            echo -e "如果仍然找不到，请手动运行："
            echo -e "  ${CYAN}curl -fsSL https://claude.ai/install.sh | bash${NC}"
            echo -e "  然后关闭终端重新打开，输入 ${GREEN}claude --version${NC} 验证。"
            exit 1
        fi

    else
        echo -e "${RED}Claude Code 安装失败。${NC}"
        echo -e "请手动运行: ${CYAN}curl -fsSL https://claude.ai/install.sh | bash${NC}"
        echo -e "安装完成后${BOLD}关闭终端重新打开${NC}，再重新运行本脚本。"
        exit 1
    fi
fi

# Create symlink in /usr/local/bin so `claude` works in ANY shell without PATH config
CLAUDE_REAL=$(command -v claude 2>/dev/null)
if [ -z "$CLAUDE_REAL" ]; then
    CLAUDE_DIR=$(find_claude 2>/dev/null) && CLAUDE_REAL="$CLAUDE_DIR/claude"
fi
if [ -n "$CLAUDE_REAL" ] && [ -x "$CLAUDE_REAL" ] && [ ! -e "/usr/local/bin/claude" ]; then
    mkdir -p /usr/local/bin 2>/dev/null || true
    if ln -sf "$CLAUDE_REAL" /usr/local/bin/claude 2>/dev/null; then
        info "已创建 /usr/local/bin/claude → $CLAUDE_REAL（任何终端直接可用）"
    fi
fi

# --- Gate: Claude Code MUST be working before proceeding ---
if ! claude --version >/dev/null 2>&1; then
    echo ""
    echo -e "${RED}${BOLD}Claude Code 未能正常运行，安装无法继续。${NC}"
    echo ""
    echo -e "  Claude Code 是整个系统的基础，后续所有组件都依赖它。"
    echo -e "  请先确保 Claude Code 安装成功后再重新运行本脚本。"
    echo ""
    echo -e "  ${BOLD}排查步骤：${NC}"
    echo -e "  1. 关闭当前终端，打开新终端"
    echo -e "  2. 输入 ${GREEN}claude --version${NC} 检查是否能正常输出版本号"
    echo -e "  3. 如果提示找不到命令，手动运行："
    echo -e "     ${CYAN}curl -fsSL https://claude.ai/install.sh | bash${NC}"
    echo -e "  4. 安装成功后，关闭终端重新打开，再运行本脚本"
    echo ""
    exit 1
fi
CLAUDE_VERSION=$(claude --version 2>/dev/null || echo "unknown")
success "Claude Code 已就绪: ${CLAUDE_VERSION}"

# --- Immediately create rescue scripts (only depends on Claude Code) ---
info "创建快捷脚本到 ~/Documents/OneClaw/ ..."
mkdir -p "$HOME/Documents/OneClaw"

# open-claude.command — one-click open Claude Code interactive mode
cat > "$HOME/Documents/OneClaw/open-claude.command" <<'ASKCLAUDE_EOF'
#!/bin/bash
# open-claude.command — Open Claude Code in interactive mode

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/Library/pnpm:/usr/local/bin:$PATH"
eval "$(fnm env 2>/dev/null)" || true

if ! command -v claude >/dev/null 2>&1; then
    echo "Claude Code not found. Please run: source ~/.zshrc"
    exit 1
fi

echo ""
echo "  正在启动 Claude Code..."
echo "  用中文描述你的问题，例如："
echo "    「帮我检查 AWS 凭证是否正确」"
echo "    「OpenClaw 报错了，帮我看看日志」"
echo "    「Chrome 连不上」"
echo ""

mkdir -p ~/Downloads
cd ~/Downloads
claude
ASKCLAUDE_EOF
chmod +x "$HOME/Documents/OneClaw/open-claude.command"

# ai-repair.command — Full-stack OneClaw AI diagnostic + repair
cat > "$HOME/Documents/OneClaw/ai-repair.command" <<'AIREPAIR_EOF'
#!/bin/bash
# ai-repair.command — OneClaw 全栈 AI 诊断+修复
# 覆盖：OpenClaw / Claude Code / AWS Bedrock / Chrome CDP / Skills / Agents / MCP / 代理 / LaunchAgents

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/Library/pnpm:/opt/homebrew/bin:/usr/local/bin:$PATH"
eval "$(fnm env 2>/dev/null)" || true

# Run from ~/Downloads so Claude Code doesn't prompt to trust root dir every time
mkdir -p ~/Downloads
cd ~/Downloads

echo -e "\n${CYAN}${BOLD}=== OneClaw 全栈 AI 诊断+修复 ===${NC}"
echo -e "${YELLOW}覆盖 OpenClaw / Claude Code / AWS / Chrome / Skills / MCP 的所有环节${NC}"
echo -e "${YELLOW}预计 2-5 分钟（视问题严重程度）${NC}\n"

if ! command -v claude >/dev/null 2>&1; then
    echo -e "${RED}找不到 claude 命令。${NC}"
    echo -e "请新开一个终端窗口重试，或先执行: ${CYAN}source ~/.zshrc${NC}"
    echo -e "仍无效就重新装: ${CYAN}curl -fsSL https://claude.ai/install.sh | bash${NC}"
    exit 1
fi

REPAIR_PROMPT='你是 OneClaw 全栈诊断修复 agent（覆盖 OpenClaw + Claude Code + AWS Bedrock + Chrome CDP + Skills + MCP + 代理）。

铁律（不遵守直接中止）：
- 不确定根因就停下来告诉用户，绝不瞎改
- 任何删文件用 `mv ~/.Trash/`，不用 `rm`
- 改 openclaw.json 前先 `cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak.$(date +%s)`
- 改 plist 后必须 `launchctl bootout` + `bootstrap`（`kickstart -k` 不重读 env）
- 只报告事实 + 做的事，不编造
- **不检测 Discord/Telegram/Feishu 网络可达性**（用户可能根本没启用这些 channel）。只在 openclaw.json 里配置了对应 channel 且日志有 ETIMEDOUT/reconnect 时才排查

# ===== Step 1: 全栈采集（只读，全跑完再分析）=====

## 1a. 基础环境
```
sw_vers
uname -m
which claude node pnpm aws openclaw 2>&1
claude --version
openclaw --version 2>&1 || echo "openclaw MISSING"
node -v
pnpm -v
aws --version 2>&1
echo "PNPM_HOME=${PNPM_HOME:-unset}"
echo "https_proxy=${https_proxy:-unset}"
```

## 1b. OpenClaw 运行态
```
openclaw daemon status 2>&1
openclaw doctor 2>&1
launchctl list | grep openclaw
pgrep -fl openclaw
lsof -nP -i :18789 -i :9222 -i :8880 2>/dev/null
```

## 1c. OpenClaw 配置与日志
```
test -f ~/.openclaw/openclaw.json && python3 -c "import json; json.load(open(\"$HOME/.openclaw/openclaw.json\"))" 2>&1 || echo "JSON INVALID"
ls -la ~/Library/LaunchAgents/ai.openclaw.*.plist 2>/dev/null
tail -80 ~/.openclaw/logs/gateway.err.log 2>/dev/null
tail -80 ~/.openclaw/logs/node.err.log 2>/dev/null
tail -40 ~/.openclaw/logs/gateway.log 2>/dev/null | grep -iE "error|fatal|reconnect|proxy|econn|etimedout|reason=auth|no api key"
# 兜底：查最近 1 天内任何 log 文件
find ~/.openclaw -name "*.log" -mtime -1 2>/dev/null | head -20
```

## 1d. Claude Code 状态
```
ls -la ~/.claude/settings.json ~/.mcp.json 2>&1
test -f ~/.claude/settings.json && python3 -m json.tool ~/.claude/settings.json > /dev/null 2>&1 && echo "settings.json OK" || echo "settings.json BROKEN"
ls ~/.claude/skills/ 2>&1 | head -20
ls ~/.claude/agents/ 2>&1 | head -20
```

## 1e. AWS / Bedrock
```
test -f ~/.aws/credentials && echo "~/.aws/credentials exists" || echo "~/.aws/credentials MISSING"
aws sts get-caller-identity 2>&1
aws bedrock list-inference-profiles --region us-west-2 --output text 2>&1 | grep -E "opus-4-7|sonnet-4-6|haiku-4-5" | head -5
# 检查 plist 是否注入了 AWS 环境变量（pi-ai 必需）
grep -A1 "AWS_ACCESS_KEY_ID\|AWS_REGION\|AWS_SECRET" ~/Library/LaunchAgents/ai.openclaw.gateway.plist 2>/dev/null | head -20
```

## 1f. Chrome CDP
```
curl -s -m 3 http://127.0.0.1:9222/json/version 2>&1 | head -5
ls -d ~/.openclaw/browser/abel-chrome ~/.openclaw/chrome-profile 2>/dev/null
```

## 1g. 网络 / 代理
```
curl -s -o /dev/null -m 5 -w "github %{http_code} %{time_total}s\n" https://github.com
curl -s -o /dev/null -m 5 -w "bedrock %{http_code} %{time_total}s\n" https://bedrock.us-west-2.amazonaws.com
# 检测本地代理（用户可能用 Clash/Stash/V2ray 任一端口）
for port in 7897 7890 1087 8080 8888 10808; do
  curl -s -o /dev/null -m 2 --proxy http://127.0.0.1:$port https://www.google.com -w "proxy $port: %{http_code}\n" 2>/dev/null || true
done
```

## 1h. pnpm / Node 健康
```
ls "$HOME/Library/pnpm/global/"*"/.pnpm/" 2>/dev/null | grep openclaw | head -5
ls "$HOME/Library/pnpm/global/"*"/node_modules/openclaw/" 2>/dev/null | head -5
```

# ===== Step 2: 根因 → 修复映射（严格按症状判断）=====

## OpenClaw 层
| 症状 | 根因 | 修复 |
|-----|-----|------|
| `ERR_MODULE_NOT_FOUND: tslog` / bundled plugins 缺文件 | pnpm store 污染 | `pnpm store prune` → `mv $HOME/Library/pnpm/global/5/.pnpm/openclaw@<坏版本>* ~/.Trash/` → 重装 |
| `No API key found for amazon-bedrock` | gateway plist 没注入 AWS env（pi-ai 只读进程 env，不读 openclaw.json.env.vars） | 给 plist 的 `EnvironmentVariables` 加 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION；bootout+bootstrap 重载 |
| `reason=auth candidate=...claude-opus-4-6-v1` | 旧 inference profile 下线 | openclaw.json 里所有 `model.primary` / `imageModel.primary` / 子 agent `model` 更新到 `global.anthropic.claude-opus-4-7` / `global.anthropic.claude-sonnet-4-6` / `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `Invalid config ... Unrecognized key` | 升级后字段被移除 | `openclaw doctor --fix`，仍报则手动删 cliBackends / talk.voiceId / feishu 旧 streaming 标量等 |
| `discord: Max reconnect attempts` + ETIMEDOUT/ECONNRESET（若用户启用了 Discord） | 防火墙/fake-ip，ws 不读 env 代理 | openclaw.json 里设 `channels.discord.proxy: "http://127.0.0.1:<Step 1g 实测可达端口>"`，`channels.telegram.proxy` 同理，重启 gateway |
| Gateway plist 里写着 `openclaw@旧版本` | 升级后没重注册 | `openclaw daemon install --force` + `openclaw node install --force` |
| `Invalid JSON` | openclaw.json 手改坏了 | 从 `openclaw.json.bak*` 或 git 恢复；没备份就报告不要瞎改 |
| LaunchAgent 非 0 退出 | 具体 bug | 先看对应 .err.log 定位 |
| 端口 18789/9222 被占 | 孤儿进程 | `pkill -f openclaw-gateway; pkill -f openclaw-node; pkill -f "remote-debugging-port=9222"` 后 bootstrap |
| `better_sqlite3 NODE_MODULE_VERSION mismatch` | Node 升级后 native 模块失效 | `cd $(brew --prefix)/lib/node_modules/@tobilu/qmd && npm rebuild better-sqlite3` |

## Claude Code 层
| 症状 | 根因 | 修复 |
|-----|-----|------|
| `claude` 命令找不到 | PATH 未加载 | `source ~/.zshrc`；仍无效重装：`curl -fsSL https://claude.ai/install.sh \| bash` |
| `~/.claude/settings.json` 损坏 | JSON 语法错 | 贴出错误行让用户确认，或从 git/备份恢复 |
| `~/.claude/skills/` 为空 | setup.sh 没跑完 | `git clone --depth 1 https://github.com/cncoder/oneclaw.git /tmp/oneclaw-skills && cp -r /tmp/oneclaw-skills/skills/* ~/.claude/skills/` |
| `~/.claude/agents/` 为空 | 同上 | `cp -r /tmp/oneclaw-skills/agents/*.md ~/.claude/agents/`（跳过 README.md） |
| MCP 连不上（chrome-devtools/aws-documentation） | `~/.mcp.json` 配置错 | 贴出错误，向用户确认是否需要重建 |

## AWS 层
| 症状 | 根因 | 修复 |
|-----|-----|------|
| `aws sts get-caller-identity` 失败 `InvalidClientTokenId` | Access Key 错或已失效 | 让用户到 AWS Console → IAM → 用户 → Security credentials 重发一对新的 |
| `list-inference-profiles` 无 opus-4-7 | 账号没开通模型访问 | 让用户去 Bedrock Console → Model access 申请 Anthropic Claude 全家桶 |
| 返回 403 `bedrock:InvokeModel` | IAM 策略不够 | 需要 `AmazonBedrockFullAccess` 或等价自定义策略 |

## Chrome CDP 层
| 症状 | 根因 | 修复 |
|-----|-----|------|
| `curl :9222/json/version` 连不上 | Chrome LaunchAgent 未启动 | `pkill -f "remote-debugging-port=9222"` → `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.chrome.plist` |
| profile 路径不存在 | 新装或被清理 | `mkdir -p ~/.openclaw/browser/abel-chrome`（或 chrome-profile，看 plist 配的是哪个）|

## 网络层
| 症状 | 根因 | 修复 |
|-----|-----|------|
| 所有 curl 都超时/reset 但代理端口可达 | 直连被拦，需走代理 | 环境变量只对 axios/undici 生效，Discord ws 需要 openclaw.json 里 `channels.*.proxy` |
| 访问解析到 198.18.x.x 被 reset | Clash fake-ip 污染 | 对应 channel 配 `proxy` 字段让 ws 走代理，或 DoH 兜底 |

# ===== Step 3: 服务重启顺序（只在需要时执行）=====

```
launchctl bootout gui/$(id -u)/ai.openclaw.node 2>/dev/null || true
launchctl bootout gui/$(id -u)/ai.openclaw.gateway 2>/dev/null || true
pkill -f openclaw-gateway 2>/dev/null || true
pkill -f openclaw-node 2>/dev/null || true
sleep 1
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.gateway.plist
# 等 gateway ready（最多 15 秒）
for i in $(seq 1 15); do
  curl -s -o /dev/null -m 1 http://127.0.0.1:18789/ && break
  sleep 1
done
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.node.plist
sleep 2
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18789/
```
期望返回 200 或 401（401 = 正常，需要 token 登录）。

# ===== Step 4: 最终验证（必须跑）=====

```
openclaw daemon status   # Runtime: running, RPC probe: ok
# 取第一个 agent 名跑 smoke test（用户可能改过名字）
AGENT=$(openclaw agent list 2>/dev/null | awk "NR==2{print \$1}")
AGENT=${AGENT:-main}
openclaw agent --agent "$AGENT" -m "say hi in 3 words" --timeout 60
```

`doctor ok ≠ agent ok`。agent 测试失败就继续回到 Step 2 找下一个根因。

# ===== 输出格式（中文）=====

## 发现的问题
- 列出命中的症状 + 贴关键日志（带行号/时间戳）
- 按严重度排序（P0: 服务挂了 / P1: 功能残缺 / P2: 告警）

## 执行的修复
- 每一步：做了什么 + 为什么 + 命令
- 改了配置的，贴 diff

## 验证结果
- `daemon status` 输出
- `agent` smoke test 输出
- 仍异常的日志尾部

## 未解决 / 需用户决策
- 凭证类问题（AWS Key 失效、Discord token 错）只提示不自动改
- 破坏性变更（删配置、回滚版本）先问用户
- 若完全定位不到，列出已收集的证据交回给用户

开始执行。'

claude --dangerously-skip-permissions --max-turns 50 -p "$REPAIR_PROMPT" --output-format text 2>&1 || true

echo -e "\n${GREEN}${BOLD}AI 诊断完成${NC}"
echo -e "如仍有问题请提 issue 附上本次输出: ${CYAN}https://github.com/cncoder/oneclaw/issues${NC}\n"
AIREPAIR_EOF
chmod +x "$HOME/Documents/OneClaw/ai-repair.command"

# Chinese symlinks
ln -sf "open-claude.command" "$HOME/Documents/OneClaw/打开Claude对话.command"
ln -sf "ai-repair.command" "$HOME/Documents/OneClaw/AI修复.command"

success "快捷脚本已创建: ~/Documents/OneClaw/"
echo -e "  📁 ${GREEN}open-claude.command${NC}  (打开Claude对话) — 双击打开 Claude Code 交互模式"
echo -e "  📁 ${GREEN}ai-repair.command${NC}    (AI修复) — 双击让 AI 自动诊断修复"
echo ""
echo -e "${GREEN}${BOLD}后续步骤如果遇到任何问题，${NC}可以："
echo -e "  1. 打开新终端输入 ${GREEN}claude${NC}"
echo -e "  2. 或双击 ${GREEN}~/Documents/OneClaw/打开Claude对话.command${NC}"
echo ""

# ============================================================================
# Step 2: Collect AWS credentials + Configure Claude Code for Bedrock
# ============================================================================
step 2 "配置 AWS 凭证 + Claude Code"

echo -e "${BOLD}接下来检查 AWS 凭证配置...${NC}"
echo -e "所有信息只保存在你的电脑上，不会上传到任何地方。\n"

# Check if AWS credentials already exist and work
AWS_CREDS_EXIST=false
if [ -f "$HOME/.aws/credentials" ] && grep -q "aws_access_key_id" "$HOME/.aws/credentials" 2>/dev/null; then
    # Extract existing values for later use
    AWS_AK=$(grep -m1 "aws_access_key_id" "$HOME/.aws/credentials" | sed 's/.*=[ ]*//')
    AWS_SK=$(grep -m1 "aws_secret_access_key" "$HOME/.aws/credentials" | sed 's/.*=[ ]*//')

    # Try to validate credentials with a lightweight API call
    if check_command aws && aws sts get-caller-identity >/dev/null 2>&1; then
        AWS_CREDS_EXIST=true
        AWS_IDENTITY=$(aws sts get-caller-identity --output text --query 'Arn' 2>/dev/null || echo "unknown")
        success "已检测到有效的 AWS 凭证: ${AWS_IDENTITY}"
        echo -e "  ${YELLOW}如需更换凭证，请手动编辑 ~/.aws/credentials${NC}"
    else
        warn "~/.aws/credentials 存在但凭证无效或 AWS CLI 未安装，稍后验证"
        # Still use existing values — they may work once AWS CLI is installed
        AWS_CREDS_EXIST=true
    fi
fi

if [ "$AWS_CREDS_EXIST" = false ]; then
    # AWS credentials
    echo -e "${CYAN}--- AWS 凭证（用于访问 Bedrock Claude 模型） ---${NC}"
    echo -e "  ${BOLD}没有 AWS 账号？${NC}找帮你装机的人要一组 Access Key 和 Secret Key。"
    echo -e "  ${BOLD}已有账号但没有密钥？${NC}登录 AWS Console → IAM → Users → 你的用户 → Security credentials → Create access key"
    echo ""
    echo -e "  ${BOLD}${YELLOW}IAM 用户需要以下权限（缺一不可）：${NC}"
    echo -e "  ${GREEN}bedrock:InvokeModel${NC}              — 调用模型（Claude Code + OpenClaw 核心）"
    echo -e "  ${GREEN}bedrock:InvokeModelWithResponseStream${NC} — 流式调用（实时对话）"
    echo -e "  ${GREEN}bedrock:ListFoundationModels${NC}     — 列出可用模型"
    echo -e "  ${GREEN}bedrock:GetFoundationModel${NC}       — 查询模型详情"
    echo -e ""
    echo -e "  ${BOLD}最简方式：${NC}给 IAM 用户附加 AWS 托管策略 ${GREEN}AmazonBedrockFullAccess${NC}"
    echo -e "  ${BOLD}最小权限：${NC}只需上面 4 个 Action，Resource 设为 ${GREEN}arn:aws:bedrock:*::foundation-model/*${NC}"
    echo -e ""
    echo -e "  ${YELLOW}还需要在 Bedrock 控制台开启模型访问：${NC}"
    echo -e "  AWS Console → Bedrock → Model access → 勾选 Anthropic Claude 全系列 → Save"
    echo ""
    ask_aws_ak AWS_AK
    ask_aws_sk AWS_SK
fi

# Region: read from existing config or ask
if [ -f "$HOME/.aws/config" ] && grep -q "region" "$HOME/.aws/config" 2>/dev/null; then
    AWS_BEDROCK_REGION=$(grep -m1 "region" "$HOME/.aws/config" | sed 's/.*=[ ]*//')
    success "已检测到 AWS 区域: ${AWS_BEDROCK_REGION}"
else
    echo ""
    echo -e "${CYAN}--- AWS 区域配置 ---${NC}"
    echo -e "  默认使用 ${GREEN}us-west-2${NC}（美国西部-俄勒冈），直接按回车即可"
    echo -e "  其他常用区域：us-east-1（美东）、eu-west-1（欧洲）、ap-northeast-1（东京）"
    ask_optional "AWS Bedrock 区域" AWS_BEDROCK_REGION "us-west-2"
fi

# Claude Code uses the same region — derive inference profile prefix
CC_BEDROCK_REGION="$AWS_BEDROCK_REGION"

# Discord (optional)
echo -e "\n${CYAN}--- Discord 机器人（可选，按回车跳过） ---${NC}"
echo -e "  OpenClaw 可以连接 Discord，让你在 Discord 里和 AI 对话、接收告警通知。"
echo -e "  如果暂时不需要，两项都直接按回车跳过，以后可以再配。\n"
echo -e "  ${BOLD}如何获取 Discord Bot Token：${NC}"
echo -e "  1. 打开 ${CYAN}https://discord.com/developers/applications${NC}"
echo -e "  2. 点右上角 ${GREEN}New Application${NC} → 输入名字（如 OpenClaw）→ Create"
echo -e "  3. 左侧点 ${GREEN}机器人(Bot)${NC} → 点 ${GREEN}重置令牌(Reset Token)${NC} → 复制 Token"
echo -e "  4. 在同一页面往下找到 ${GREEN}特权网关意图(Privileged Gateway Intents)${NC}"
echo -e "     打开 ${GREEN}消息内容意图(Message Content Intent)${NC} 开关 → 点 ${GREEN}保存(Save)${NC}"
echo -e ""
echo -e "  ${BOLD}如何邀请 Bot 到你的 Discord 服务器：${NC}"
echo -e "  5. 左侧点 ${GREEN}OAuth2${NC} → 往下找到 ${GREEN}OAuth2 URL 生成器${NC}"
echo -e "     范围(Scopes)勾选: ${GREEN}bot${NC}"
echo -e "     勾选后下方出现 ${GREEN}机器人权限(Bot Permissions)${NC}，勾选:"
echo -e "     ${GREEN}Send Messages${NC} / ${GREEN}Read Message History${NC} / ${GREEN}View Channels${NC}"
echo -e "  6. 页面最下方会生成一个 URL → 点 ${GREEN}Copy${NC} → 浏览器打开"
echo -e "     选择你的服务器 → 点 ${GREEN}授权(Authorize)${NC}\n"
echo -en "${YELLOW}Discord Bot Token（没有就直接回车）: ${NC}"
read -r DISCORD_BOT_TOKEN </dev/tty
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN:-}"

echo -e "\n  ${BOLD}如何获取 Discord Webhook URL：${NC}"
echo -e "  1. 打开 Discord → 进入你想收通知的频道"
echo -e "  2. 点频道名旁的 ⚙️ 设置 → 左侧 ${GREEN}Integrations${NC} → ${GREEN}Webhooks${NC}"
echo -e "  3. 点 ${GREEN}New Webhook${NC} → 取名（如 OpenClaw Alert）→ ${GREEN}Copy Webhook URL${NC}\n"
echo -en "${YELLOW}Discord Webhook URL（用于异常告警，没有就直接回车）: ${NC}"
read -r DISCORD_WEBHOOK_URL </dev/tty
DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"

# OpenClaw gateway token — auto-generate, user doesn't need to know
GATEWAY_TOKEN=$(openssl rand -hex 24)
info "已自动生成 Gateway 安全令牌"

# --- Write AWS credentials ---
info "Writing AWS credentials..."
mkdir -p "$HOME/.aws"

if command -v aws >/dev/null 2>&1; then
    aws configure set aws_access_key_id "$AWS_AK" --profile default
    aws configure set aws_secret_access_key "$AWS_SK" --profile default
    aws configure set region "$AWS_BEDROCK_REGION" --profile default
    aws configure set output json --profile default
    success "AWS credentials set via 'aws configure set' (default profile only, other profiles untouched)"
else
    # aws cli not yet installed — write files directly (only [default] section)
    if [ ! -f "$HOME/.aws/credentials" ] || ! grep -q "\[default\]" "$HOME/.aws/credentials" 2>/dev/null; then
        cat > "$HOME/.aws/credentials" <<EOF
[default]
aws_access_key_id = ${AWS_AK}
aws_secret_access_key = ${AWS_SK}
EOF
        success "AWS credentials written to ~/.aws/credentials"
    else
        warn "~/.aws/credentials [default] already exists, not overwriting (aws cli not available for safe merge)"
    fi

    if [ ! -f "$HOME/.aws/config" ] || ! grep -q "\[default\]" "$HOME/.aws/config" 2>/dev/null; then
        cat > "$HOME/.aws/config" <<EOF
[default]
region = ${AWS_BEDROCK_REGION}
output = json
EOF
        success "AWS config written to ~/.aws/config"
    else
        warn "~/.aws/config [default] already exists, not overwriting (aws cli not available for safe merge)"
    fi
fi

# --- Verify Bedrock access ---
if check_command aws; then
    info "验证 Bedrock 模型访问权限..."
    if aws bedrock list-foundation-models --region "$AWS_BEDROCK_REGION" --query 'modelSummaries[?starts_with(modelId, `anthropic.claude`)].[modelId]' --output text >/dev/null 2>&1; then
        success "Bedrock 权限验证通过"
    else
        warn "无法访问 Bedrock 模型。可能的原因："
        echo -e "  1. IAM 用户缺少 ${GREEN}bedrock:ListFoundationModels${NC} 权限"
        echo -e "  2. 区域 ${GREEN}${AWS_BEDROCK_REGION}${NC} 未开启 Bedrock 模型访问"
        echo -e "  3. 请在 AWS Console → Bedrock → Model access 中勾选 Anthropic Claude 系列"
        echo ""
        echo -en "${YELLOW}是否重新输入 AWS Access Key？(y/N): ${NC}"
        read -r RETRY_CREDS </dev/tty
        if [[ "$RETRY_CREDS" =~ ^[Yy]$ ]]; then
            ask_aws_ak AWS_AK
            ask_aws_sk AWS_SK
            aws configure set aws_access_key_id "$AWS_AK" --profile default
            aws configure set aws_secret_access_key "$AWS_SK" --profile default
            if aws bedrock list-foundation-models --region "$AWS_BEDROCK_REGION" --query 'modelSummaries[?starts_with(modelId, `anthropic.claude`)].[modelId]' --output text >/dev/null 2>&1; then
                success "Bedrock 权限验证通过（新凭证）"
            else
                warn "新凭证仍无法访问 Bedrock，安装将继续。"
                echo -e "  ${YELLOW}安装完成后可以打开新终端输入 ${GREEN}claude${YELLOW} 让它帮你排查权限问题。${NC}"
            fi
        else
            echo -e "  ${YELLOW}安装将继续。完成后可以打开新终端输入 ${GREEN}claude${YELLOW} 让它帮你排查。${NC}"
        fi
    fi
else
    info "AWS CLI 尚未安装，Bedrock 权限将在后续步骤验证"
fi

# --- Configure Claude Code for Bedrock ---
info "Configuring Claude Code for Bedrock..."

CLAUDE_DIR="$HOME/.claude"
mkdir -p "$CLAUDE_DIR"

PROFILE_PREFIX="us"
case "$CC_BEDROCK_REGION" in
    eu-*)  PROFILE_PREFIX="eu" ;;
    ap-*)  PROFILE_PREFIX="ap" ;;
esac

if [ -f "$CLAUDE_DIR/settings.json" ]; then
    cp "$CLAUDE_DIR/settings.json" "$CLAUDE_DIR/settings.json.bak.$(date +%s)"
    warn "已有 settings.json 已备份为 settings.json.bak.*"
fi

cat > "$CLAUDE_DIR/settings.json" <<SETTINGS_EOF
{
    "\$schema": "https://json.schemastore.org/claude-code-settings.json",
    "respectGitignore": true,
    "cleanupPeriodDays": 30,
    "env": {
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "AWS_REGION": "${CC_BEDROCK_REGION}",
        "ANTHROPIC_MODEL": "${PROFILE_PREFIX}.anthropic.claude-opus-4-6-v1",
        "CLAUDE_CODE_SUBAGENT_MODEL": "${PROFILE_PREFIX}.anthropic.claude-sonnet-4-6",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "128000",
        "CLAUDE_CODE_EFFORT_LEVEL": "medium",
        "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "50",
        "CLAUDE_PACKAGE_MANAGER": "pnpm",
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1"
    },
    "model": "${PROFILE_PREFIX}.anthropic.claude-opus-4-6-v1",
    "permissions": {
        "allow": [
            "Bash",
            "mcp__plugin_context7_context7__*",
            "mcp__chrome-devtools__*",
            "mcp__aws-documentation__*",
            "WebFetch",
            "Write",
            "Edit"
        ],
        "deny": [
            "Bash(rm -rf /*)",
            "Bash(rm -rf /)",
            "Bash(rm -rf ~/*)",
            "Bash(rm -rf ~)",
            "Bash(sudo rm *)",
            "Bash(git push --force *)",
            "Bash(git reset --hard *)",
            "Bash(git clean -f*)",
            "Bash(mkfs*)",
            "Bash(dd if=*)"
        ]
    },
    "outputStyle": "Concise",
    "language": "chinese",
    "sandbox": {
        "enabled": false,
        "autoAllowBashIfSandboxed": true
    },
    "enabledPlugins": {
        "context7@claude-plugins-official": true
    }
}
SETTINGS_EOF
success "Claude Code settings.json written"

if [ -f "$HOME/.mcp.json" ]; then
    cp "$HOME/.mcp.json" "$HOME/.mcp.json.bak.$(date +%s)"
    warn "已有 .mcp.json 已备份为 .mcp.json.bak.*"
fi

cat > "$HOME/.mcp.json" <<MCP_EOF
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest", "--browserUrl", "http://localhost:9222"]
    },
    "aws-documentation": {
      "command": "uvx",
      "args": ["awslabs.aws-documentation-mcp-server@latest"],
      "env": {
        "FASTMCP_LOG_LEVEL": "ERROR",
        "AWS_DOCUMENTATION_PARTITION": "aws"
      }
    }
  }
}
MCP_EOF
success "MCP servers config written to ~/.mcp.json"

# --- Generate ~/.claude/CLAUDE.md (global instructions for Claude Code) ---
if [ ! -f "$CLAUDE_DIR/CLAUDE.md" ]; then
    cat > "$CLAUDE_DIR/CLAUDE.md" <<'GLOBALMD_EOF'
# Claude Code 全局配置

## 验证门控（最高优先级）

声称完成前必须有新鲜验证证据。禁止无证据说"应该可以了"。

**所有功能开发完成后必须：**
1. 运行构建/编译，确认无错误
2. 用 Chrome DevTools MCP 打开页面，截图验证 UI 和功能
3. 检查控制台无报错，网络请求正常
4. 前端改动必须 CDP 截图对比（改前 vs 改后）

**E2E 验证流程：**
- 优先使用 Chrome DevTools MCP 进行端到端测试
- 模拟用户操作：点击、输入、导航、表单提交
- 验证关键路径：页面加载 → 用户交互 → 数据展示 → 结果确认
- 截图保存每个关键步骤的页面状态作为证据

## 语言

默认使用中文回复。技术术语保持英文原文。代码注释和 commit message 用英文。

## 文档先行

禁止仅凭训练数据中的旧知识编码，写代码前必须先查最新文档：

- **编程库/SDK/框架**: 用 Context7 插件查最新用法
- **AWS 服务/API**: 用 AWS Documentation MCP 查官方文档
- **第三方 API**: Context7 查文档，查不到则 WebFetch 官方文档页
- **不确定的参数/接口**: 必须查文档确认，不要猜

## 编码规范

- 写代码前先读已有代码，理解上下文再动手
- 修改文件前必须先 Read，不要凭印象修改
- 函数保持短小（<50 行），文件不超过 800 行
- 优先不可变数据，避免就地修改对象
- 只在系统边界做输入验证（用户输入、外部 API），内部代码信任传参
- 不要添加没被要求的功能、注释、类型标注或重构
- 全栈开发顺序：后端 → API → 前端组件 → 页面集成 → 构建 → 浏览器验证

## 前端开发

- 注重功能完整性和可演示性，优先让功能跑通可见
- 开发完成后用 Chrome DevTools MCP 截图检查 UI 质量
- 关注布局、配色、响应式、动效，迭代优化直到界面精致
- 开发完必须在浏览器中实际测试

## Chrome DevTools (CDP) 使用规则

- **绝对不要在当前聚焦的 tab 直接 navigate** — 用户可能正在使用该页面
- 必须先用 `new_page` 打开新 tab，在新 tab 里操作
- 操作完毕后不要关闭用户的其他 tab
- CDP 超时 → 先 `curl 127.0.0.1:9222/json` 验证连接
- WebFetch 被 403 拒绝时，立即改用 Chrome DevTools MCP 获取页面内容

## 安全

- 绝不在代码中硬编码密钥、Token、密码
- 使用环境变量或密钥管理器
- SQL 必须用参数化查询
- 用户输入必须做 XSS 防护
- 禁止直接 `rm` 删除文件，用 `mv` 移到回收目录

## 工具使用

- 用 Read 读文件，不用 cat/head/tail
- 用 Edit 改文件，不用 sed/awk
- 用 Grep 搜索内容，不用 grep/rg
- 用 Glob 找文件，不用 find/ls
- Write/Edit 前必须先 Read
- 大输出 pipe `head -100`
- 命令失败 2 次换方案
- Mac 用 `python3` 不是 `python`

## 子代理 (Sub-Agents)

- 子代理任务必须拆小拆细，每个子任务聚焦单一目标
- 独立任务必须并行执行，不要串行
- 避免单个代理执行时间过长导致假死
- 模型选择：Haiku（数据采集/格式化）、Sonnet（日常开发）、Opus（深度分析/架构）

可用子代理：

| 子代理 | 用途 |
|--------|------|
| researcher | 调研、文档搜索、技术对比、深度调研（多轮多源信息收集与验证） |
| architect | 架构设计、技术决策、系统设计 |
| code-reviewer | 代码审查，写完立即用 |
| qa-tester | 测试、E2E 验证 |
| data-analyst | 数据分析、结构化数据 |
| cost-optimizer | 云成本分析 |
| doc-writer | 文档更新 |

## 调试

- 先读完整错误信息和堆栈，不跳过 warning
- 先稳定复现问题，再提修复方案
- 检查 recent changes（git diff、最近 commit）
- 一次只改一个变量验证假设
- 连续失败 3 次停下来重新分析，和用户讨论
- 禁止"先改了看看"的猜测性修复

## Git

- Commit message 格式：`<type>: <description>`（feat/fix/refactor/docs/test/chore）
- 重要步骤后立即 commit 作为 checkpoint
- 不要自动 commit，除非明确要求
- 不要 force push、reset --hard、跳过 hooks

## 可用工具

- **Chrome DevTools MCP**: 浏览器自动化和调试（端口 9222）
- **AWS Documentation MCP**: 查询 AWS 官方文档
- **Context7 Plugin**: 查询编程库/SDK/框架最新文档
- **lark-cli**: 飞书/Lark CLI，支持日历、消息、文档、表格等操作
GLOBALMD_EOF
    success "Claude Code CLAUDE.md 已生成 (~/.claude/CLAUDE.md)"
else
    success "Claude Code CLAUDE.md 已存在，跳过"
fi

echo ""
echo -e "${GREEN}${BOLD}Claude Code 已配置完成，可以随时使用！${NC}"
echo -e "如果后续步骤遇到问题，打开新终端窗口输入 ${CYAN}claude${NC} 让它帮你排查。"
echo ""

# ============================================================================
# Step 3: fnm (Fast Node Manager) + Node.js
# ============================================================================
step 3 "Install fnm + Node.js"

# fnm (Fast Node Manager)
if check_command fnm; then
    success "fnm already installed: $(fnm --version)"
else
    info "Installing fnm (Fast Node Manager)..."
    if curl -fsSL https://fnm.vercel.app/install | bash; then
        export PATH="$HOME/.local/share/fnm:$PATH"
        eval "$(fnm env 2>/dev/null)" || true
        success "fnm installed"
    else
        echo -e "${RED}fnm 安装失败。${NC}你可以打开新终端输入 ${GREEN}claude${NC} 让它帮你修，或手动运行: ${CYAN}curl -fsSL https://fnm.vercel.app/install | bash${NC}"
        exit 1
    fi
fi

# Ensure fnm is in PATH
eval "$(fnm env 2>/dev/null)" || true

# Node.js via fnm
if check_command node; then
    success "Node.js already installed: $(node --version)"
else
    info "Installing Node.js LTS via fnm..."
    if fnm install --lts && fnm use lts-latest && fnm default lts-latest; then
        eval "$(fnm env)"
        success "Node.js installed: $(node --version)"
    else
        echo -e "${RED}Node.js 安装失败。${NC}你可以打开新终端输入 ${GREEN}claude${NC} 让它帮你修，或手动运行: ${CYAN}fnm install --lts${NC}"
        exit 1
    fi
fi

# ============================================================================
# Step 4: Core dependencies (pnpm, lark-cli, uv, AWS CLI, Chrome)
# ============================================================================
step 4 "Install core dependencies (pnpm, lark-cli, uv, AWS CLI)"

# pnpm
if check_command pnpm; then
    success "pnpm already installed: $(pnpm --version)"
else
    info "Installing pnpm..."
    if npm install -g pnpm; then
        pnpm setup 2>/dev/null || true
        export PNPM_HOME="$HOME/Library/pnpm"
        export PATH="$PNPM_HOME:$PATH"
        success "pnpm installed"
    else
        echo -e "${RED}pnpm 安装失败。${NC}你可以打开新终端输入 ${GREEN}claude${NC} 让它帮你修，或手动运行: ${CYAN}npm install -g pnpm${NC}"
        exit 1
    fi
fi

# lark-cli (Lark/Feishu CLI for AI Agents)
if check_command lark-cli; then
    success "lark-cli already installed: $(lark-cli --version 2>/dev/null || echo 'installed')"
else
    info "Installing lark-cli (飞书/Lark CLI)..."
    if npm install -g @larksuite/cli 2>/dev/null; then
        success "lark-cli installed"
        # Install lark-cli skills for Claude Code
        info "安装 lark-cli Skills..."
        npx skills add larksuite/cli -y -g 2>/dev/null \
            && success "lark-cli Skills 已安装" \
            || warn "lark-cli Skills 安装失败，可稍后运行: npx skills add larksuite/cli -y -g"
    else
        warn "lark-cli 安装失败，可稍后手动运行: npm install -g @larksuite/cli"
    fi
fi

# uv (for Python MCP servers)
if check_command uv; then
    success "uv already installed: $(uv --version)"
else
    info "Installing uv (Python package manager)..."
    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
        export PATH="$HOME/.local/bin:$PATH"
        success "uv installed"
    else
        echo -e "${RED}uv 安装失败。${NC}你可以打开新终端输入 ${GREEN}claude${NC} 让它帮你修，或手动运行: ${CYAN}curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
        exit 1
    fi
fi

# AWS CLI (official pkg installer)
if check_command aws; then
    success "AWS CLI already installed: $(aws --version 2>&1 | head -1)"
else
    info "Installing AWS CLI via official installer..."
    AWSCLI_TMP="/tmp/awscli-install-$$"
    mkdir -p "$AWSCLI_TMP"
    if curl -fsSL "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "$AWSCLI_TMP/AWSCLIV2.pkg" \
       && sudo installer -pkg "$AWSCLI_TMP/AWSCLIV2.pkg" -target /; then
        rm -rf "$AWSCLI_TMP"
        success "AWS CLI installed: $(aws --version 2>&1 | head -1)"
    else
        rm -rf "$AWSCLI_TMP"
        echo -e "${RED}AWS CLI 安装失败。${NC}你可以打开新终端输入 ${GREEN}claude${NC} 让它帮你修，或手动从 ${CYAN}https://awscli.amazonaws.com/AWSCLIV2.pkg${NC} 下载安装"
        exit 1
    fi
fi

# Google Chrome (needed for chrome-devtools MCP)
CHROME_APP="/Applications/Google Chrome.app"
if [ -d "$CHROME_APP" ]; then
    success "Google Chrome already installed"
else
    warn "未检测到 Google Chrome。Chrome DevTools MCP 需要 Chrome 才能工作。"
    echo -e "  请手动从 ${CYAN}https://www.google.com/chrome/${NC} 下载安装，然后重新运行本脚本。"
    echo -e "  ${YELLOW}安装会继续，但 Chrome 相关功能暂不可用。${NC}"
fi

# Verify AWS credentials (now that AWS CLI is available)
info "Verifying AWS credentials..."
if aws sts get-caller-identity >/dev/null 2>&1; then
    success "AWS credentials valid: $(aws sts get-caller-identity --query 'Account' --output text)"
else
    warn "AWS 凭证验证失败。"
    echo ""
    echo -en "${YELLOW}是否重新输入 AWS Access Key？(y/N): ${NC}"
    read -r RETRY_STS </dev/tty
    if [[ "$RETRY_STS" =~ ^[Yy]$ ]]; then
        ask_aws_ak AWS_AK
        ask_aws_sk AWS_SK
        aws configure set aws_access_key_id "$AWS_AK" --profile default
        aws configure set aws_secret_access_key "$AWS_SK" --profile default
        if aws sts get-caller-identity >/dev/null 2>&1; then
            success "AWS credentials valid (new): $(aws sts get-caller-identity --query 'Account' --output text)"
        else
            warn "新凭证仍然无效，安装将继续。"
            echo -e "  ${YELLOW}安装完成后可以打开新终端输入 ${GREEN}claude${YELLOW} 让它帮你排查。${NC}"
        fi
    else
        warn "跳过，安装将继续。"
        echo -e "  ${YELLOW}安装完成后可以打开新终端输入 ${GREEN}claude${YELLOW} 让它帮你排查 AWS 凭证问题。${NC}"
    fi
fi

# Verify Bedrock endpoint
info "Verifying Bedrock endpoint in ${AWS_BEDROCK_REGION}..."
BEDROCK_TEST_PREFIX="us"
case "$AWS_BEDROCK_REGION" in
    eu-*)  BEDROCK_TEST_PREFIX="eu" ;;
    ap-*)  BEDROCK_TEST_PREFIX="ap" ;;
esac

verify_bedrock_endpoint() {
    aws bedrock-runtime invoke-model \
        --model-id "${BEDROCK_TEST_PREFIX}.anthropic.claude-haiku-4-5-20251001-v1:0" \
        --region "$AWS_BEDROCK_REGION" \
        --body '{"anthropic_version":"bedrock-2023-05-31","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}' \
        --content-type "application/json" \
        /dev/null >/dev/null 2>&1
}

if verify_bedrock_endpoint; then
    success "Bedrock endpoint verified in ${AWS_BEDROCK_REGION} (model accessible)"
else
    warn "Bedrock 权限检测失败（${AWS_BEDROCK_REGION}）"
    echo ""
    echo -e "  ${YELLOW}${BOLD}⚠ 你的 AWS 账号可能缺少 Bedrock 权限，Claude Code 和 OpenClaw 将无法正常工作。${NC}"
    echo ""
    echo -e "  ${BOLD}可能的原因：${NC}"
    echo ""
    echo -e "  ${CYAN}1. IAM 权限不足${NC}"
    echo -e "     → 给你的 IAM 用户附加策略 ${GREEN}AmazonBedrockFullAccess${NC}"
    echo -e "     → 或至少添加这 4 个权限："
    echo -e "       ${GREEN}bedrock:InvokeModel${NC}"
    echo -e "       ${GREEN}bedrock:InvokeModelWithResponseStream${NC}"
    echo -e "       ${GREEN}bedrock:ListFoundationModels${NC}"
    echo -e "       ${GREEN}bedrock:GetFoundationModel${NC}"
    echo ""
    echo -e "  ${CYAN}2. 模型访问未开启${NC}"
    echo -e "     → AWS Console → Bedrock → Model access → 勾选 ${GREEN}Anthropic Claude 全系列${NC} → Save"
    echo ""
    echo -e "  ${CYAN}3. 区域不支持 Bedrock${NC}"
    echo -e "     → 当前区域: ${YELLOW}${AWS_BEDROCK_REGION}${NC}"
    echo -e "     → 推荐使用: ${GREEN}us-west-2${NC}（美西）或 ${GREEN}us-east-1${NC}（美东）"
    echo ""
    echo -en "  ${YELLOW}是否重新输入 AWS Access Key 再试？(y/N): ${NC}"
    read -r RETRY_BEDROCK </dev/tty
    if [[ "$RETRY_BEDROCK" =~ ^[Yy]$ ]]; then
        ask_aws_ak AWS_AK
        ask_aws_sk AWS_SK
        ask_optional "AWS Bedrock 区域" AWS_BEDROCK_REGION "$AWS_BEDROCK_REGION"
        aws configure set aws_access_key_id "$AWS_AK" --profile default
        aws configure set aws_secret_access_key "$AWS_SK" --profile default
        aws configure set region "$AWS_BEDROCK_REGION" --profile default
        # Recalculate prefix after possible region change
        BEDROCK_TEST_PREFIX="us"
        case "$AWS_BEDROCK_REGION" in
            eu-*)  BEDROCK_TEST_PREFIX="eu" ;;
            ap-*)  BEDROCK_TEST_PREFIX="ap" ;;
        esac
        CC_BEDROCK_REGION="$AWS_BEDROCK_REGION"
        if verify_bedrock_endpoint; then
            success "Bedrock endpoint verified in ${AWS_BEDROCK_REGION}（新凭证）"
        else
            warn "新凭证仍无法访问 Bedrock，安装将继续。"
            echo -e "  ${YELLOW}安装完成后可以打开新终端输入 ${GREEN}claude${YELLOW} 让它帮你排查权限问题。${NC}"
        fi
    else
        echo -e "  ${GREEN}${BOLD}安装会继续，但请尽快修复权限，否则 Claude Code 和 OpenClaw 无法调用 AI 模型。${NC}"
        echo -e "  修复后可以打开新终端输入 ${CYAN}claude${NC} 验证是否正常工作。"
    fi
    echo ""
fi

# ============================================================================
# Step 4.5: Ensure PATH is persistent in ~/.zshrc
# ============================================================================
ZSHRC="$HOME/.zshrc"
touch "$ZSHRC"

add_to_zshrc() {
    local line="$1"
    if [[ "$line" == \#* ]]; then
        grep -qxF "$line" "$ZSHRC" 2>/dev/null || echo "$line" >> "$ZSHRC"
    else
        grep -qxF "$line" "$ZSHRC" 2>/dev/null || echo "$line" >> "$ZSHRC"
    fi
}

add_to_zshrc '# fnm (Fast Node Manager)'
add_to_zshrc 'eval "$(fnm env)"'
add_to_zshrc '# pnpm'
add_to_zshrc 'export PNPM_HOME="$HOME/Library/pnpm"'
add_to_zshrc 'export PATH="$PNPM_HOME:$PATH"'
add_to_zshrc '# uv / Claude Code / local bin'
add_to_zshrc 'export PATH="$HOME/.local/bin:$PATH"'

success "PATH 配置已写入 ~/.zshrc（新终端窗口自动生效）"

# ============================================================================
# Step 5: Install OpenClaw
# ============================================================================
step 5 "Install OpenClaw"

if check_command openclaw; then
    success "OpenClaw already installed: $(openclaw --version 2>/dev/null || echo 'installed')"
else
    info "Installing OpenClaw..."
    if curl -fsSL https://openclaw.ai/install.sh | bash; then
        export PATH="$HOME/Library/pnpm:$HOME/.local/bin:$PATH"
        hash -r 2>/dev/null || true
        if check_command openclaw; then
            success "OpenClaw installed"
        else
            warn "OpenClaw 已安装但未在 PATH 中。请稍后打开新终端窗口再试。"
        fi
    else
        echo -e "${RED}OpenClaw 安装失败。请手动运行: ${CYAN}curl -fsSL https://openclaw.ai/install.sh | bash${NC}"
        exit 1
    fi
fi

# ============================================================================
# Step 6: Configure OpenClaw
# ============================================================================
step 6 "Configure OpenClaw"

OPENCLAW_DIR="$HOME/.openclaw"
mkdir -p "$OPENCLAW_DIR/logs"
mkdir -p "$OPENCLAW_DIR/scripts"
mkdir -p "$OPENCLAW_DIR/workspace"

# Determine OpenClaw Bedrock model prefix (must match region)
OC_MODEL_PREFIX="us"
case "$AWS_BEDROCK_REGION" in
    eu-*)  OC_MODEL_PREFIX="eu" ;;
    ap-*)  OC_MODEL_PREFIX="ap" ;;
esac

# Backup existing OpenClaw config if present
if [ -f "$OPENCLAW_DIR/openclaw.json" ]; then
    cp "$OPENCLAW_DIR/openclaw.json" "$OPENCLAW_DIR/openclaw.json.bak.$(date +%s)"
    warn "已有 openclaw.json 已备份为 openclaw.json.bak.*"
fi

# openclaw.json — minimal but complete
cat > "$OPENCLAW_DIR/openclaw.json" <<OC_EOF
{
  "browser": {
    "enabled": true,
    "headless": false,
    "noSandbox": false,
    "defaultProfile": "default-chrome",
    "profiles": {
      "default-chrome": {
        "cdpPort": 9222,
        "color": "#4285F4"
      }
    }
  },
  "acp": {
    "enabled": true,
    "defaultAgent": "claude-code",
    "allowedAgents": ["claude-code"],
    "maxConcurrentSessions": 3
  },
  "models": {
    "mode": "merge",
    "providers": {
      "amazon-bedrock": {
        "baseUrl": "https://bedrock-runtime.${AWS_BEDROCK_REGION}.amazonaws.com",
        "auth": "aws-sdk",
        "api": "bedrock-converse-stream",
        "models": [
          {
            "id": "${OC_MODEL_PREFIX}.anthropic.claude-opus-4-6-v1",
            "name": "Opus 4.6",
            "api": "bedrock-converse-stream",
            "reasoning": true,
            "input": ["text", "image"],
            "cost": { "input": 5, "output": 25, "cacheRead": 0.5, "cacheWrite": 10 },
            "contextWindow": 200000,
            "maxTokens": 131072
          },
          {
            "id": "${OC_MODEL_PREFIX}.anthropic.claude-sonnet-4-6",
            "name": "Sonnet 4.6",
            "api": "bedrock-converse-stream",
            "reasoning": true,
            "input": ["text", "image"],
            "cost": { "input": 3, "output": 15, "cacheRead": 0.3, "cacheWrite": 6 },
            "contextWindow": 200000,
            "maxTokens": 65536
          },
          {
            "id": "${OC_MODEL_PREFIX}.anthropic.claude-haiku-4-5-20251001-v1:0",
            "name": "Haiku 4.5",
            "api": "bedrock-converse-stream",
            "reasoning": false,
            "input": ["text", "image"],
            "cost": { "input": 1, "output": 5, "cacheRead": 0.1, "cacheWrite": 2 },
            "contextWindow": 200000,
            "maxTokens": 8192
          }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "amazon-bedrock/${OC_MODEL_PREFIX}.anthropic.claude-sonnet-4-6"
      },
      "workspace": "${OPENCLAW_DIR}/workspace",
      "bootstrapMaxChars": 40000,
      "bootstrapTotalMaxChars": 200000,
      "cliBackends": {
        "claude-code": {
          "command": "${HOME}/.local/bin/claude",
          "args": ["--dangerously-skip-permissions", "-p", "--output-format", "stream-json"],
          "output": "jsonl",
          "input": "arg",
          "sessionMode": "always"
        }
      },
      "contextPruning": { "mode": "cache-ttl", "ttl": "1h" },
      "thinkingDefault": "medium",
      "heartbeat": { "every": "30m" },
      "maxConcurrent": 4,
      "subagents": { "maxConcurrent": 8 }
    },
    "list": [
      {
        "id": "main",
        "default": true,
        "name": "Assistant"
      }
    ]
  },
  "tools": {
    "exec": {
      "host": "gateway",
      "security": "full",
      "ask": "off"
    }
  },
  "commands": {
    "native": "auto",
    "nativeSkills": "auto",
    "restart": true
  },
  "gateway": {
    "port": 18789,
    "mode": "local",
    "bind": "loopback",
    "controlUi": { "allowInsecureAuth": false },
    "auth": {
      "mode": "token",
      "token": "${GATEWAY_TOKEN}"
    },
    "tailscale": { "mode": "off" }
  },
  "skills": {
    "install": { "nodeManager": "pnpm" }
  },
  "plugins": {
    "entries": {
      "acpx": { "enabled": true }
    }
  }
}
OC_EOF
success "OpenClaw config written to ~/.openclaw/openclaw.json"

# Workspace markdown files — leave empty templates
for md_file in AGENTS.md SOUL.md TOOLS.md IDENTITY.md USER.md HEARTBEAT.md MEMORY.md; do
    if [ ! -f "$OPENCLAW_DIR/workspace/$md_file" ]; then
        touch "$OPENCLAW_DIR/workspace/$md_file"
    fi
done
success "Workspace markdown files created (empty)"

# Install skill-vetter from ClawHub (security skill for vetting other skills)
info "安装 skill-vetter（技能安全审查工具）..."
mkdir -p "$OPENCLAW_DIR/skills"
npx clawhub install spclaudehome/skill-vetter --dir "$OPENCLAW_DIR/skills" 2>/dev/null \
    && success "skill-vetter 已安装" \
    || warn "skill-vetter 安装失败，可稍后手动安装：npx clawhub install spclaudehome/skill-vetter"

# Install OneClaw bundled skills + Claude Code universal skills
info "安装 Skills..."
OC_SKILLS_DIR="$OPENCLAW_DIR/workspace/skills"
CC_SKILLS_DIR="$HOME/.claude/skills"
mkdir -p "$OC_SKILLS_DIR" "$CC_SKILLS_DIR"
ONECLAW_TMP="/tmp/oneclaw-skills-$$"
if git clone --depth 1 https://github.com/cncoder/oneclaw.git "$ONECLAW_TMP" 2>/dev/null; then
    # OpenClaw-specific skills → ~/.openclaw/workspace/skills/
    for skill_name in claude-code aws-infra chrome-devtools skill-vetting; do
        if [ -d "$ONECLAW_TMP/skills/$skill_name" ]; then
            cp -r "$ONECLAW_TMP/skills/$skill_name" "$OC_SKILLS_DIR/"
            success "OpenClaw Skill: $skill_name"
        fi
    done

    # Universal dev skills → ~/.claude/skills/ (for Claude Code direct use)
    for skill_name in coding-standards security-review python-patterns frontend-patterns backend-patterns api-design docker-patterns database-migrations deployment-patterns openclaw-upgrade; do
        if [ -d "$ONECLAW_TMP/skills/$skill_name" ]; then
            cp -r "$ONECLAW_TMP/skills/$skill_name" "$CC_SKILLS_DIR/"
            success "Claude Code Skill: $skill_name"
        fi
    done

    # Install Claude Code sub-agents to ~/.claude/agents/
    info "安装 Claude Code Sub-Agents..."
    AGENTS_DIR="$HOME/.claude/agents"
    mkdir -p "$AGENTS_DIR"
    if [ -d "$ONECLAW_TMP/agents" ]; then
        AGENT_COUNT=0
        for agent_file in "$ONECLAW_TMP"/agents/*.md; do
            [ -f "$agent_file" ] || continue
            agent_name=$(basename "$agent_file")
            # Skip README
            [ "$agent_name" = "README.md" ] && continue
            cp "$agent_file" "$AGENTS_DIR/"
            AGENT_COUNT=$((AGENT_COUNT + 1))
        done
        success "Claude Code Sub-Agents 已安装: ${AGENT_COUNT} 个 (${AGENTS_DIR}/)"
    else
        warn "agents/ 目录不存在，跳过 Sub-Agents 安装"
    fi

    rm -rf "$ONECLAW_TMP"
else
    warn "Skills 和 Agents 自动安装失败（网络问题？），可稍后手动安装。"
    echo -e "  打开终端输入 ${GREEN}claude${NC}，然后说：「帮我安装 OneClaw skills 和 agents」"
fi

# ============================================================================
# Step 7: Guardian watchdog script
# ============================================================================
step 7 "Set up Guardian watchdog"

cat > "$OPENCLAW_DIR/scripts/guardian-check.sh" <<'GUARDIAN_EOF'
#!/bin/bash
# guardian-check.sh — OpenClaw Gateway health check + auto-repair
# Called every 60s by ai.openclaw.guardian LaunchAgent
# Three layers: process alive → HTTP port → openclaw status

set -euo pipefail

GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
GATEWAY_HOST="127.0.0.1"
HEALTH_URL="http://${GATEWAY_HOST}:${GATEWAY_PORT}/"
STATE_FILE="/tmp/openclaw-guardian-state.json"
LOG_FILE="${HOME}/.openclaw/logs/guardian.log"
MAX_REPAIR=3
COOLDOWN_SECONDS=300
DISCORD_WEBHOOK="${DISCORD_WEBHOOK_URL:-}"

log() {
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] $1" >> "$LOG_FILE"
}

notify() {
    local msg="$1"
    log "[NOTIFY] $msg"
    if [ -n "$DISCORD_WEBHOOK" ]; then
        curl -s -m 10 -X POST "$DISCORD_WEBHOOK" \
            -H "Content-Type: application/json" \
            -d "{\"content\": \"🦞 **OpenClaw Guardian**: $msg\"}" \
            >/dev/null 2>&1 || true
    fi
}

read_state() {
    if [ -f "$STATE_FILE" ]; then
        cat "$STATE_FILE"
    else
        echo '{"failures":0,"last_repair":0,"cooldown_until":0}'
    fi
}

write_state() {
    local failures="$1" last_repair="$2" cooldown_until="$3"
    cat > "$STATE_FILE" <<EOF
{"failures":${failures},"last_repair":${last_repair},"cooldown_until":${cooldown_until}}
EOF
}

get_field() {
    local json="$1" field="$2"
    python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('$field',0))" <<< "$json"
}

check_process() {
    launchctl list ai.openclaw.node >/dev/null 2>&1
}

check_http() {
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" -m 2 "$HEALTH_URL" 2>/dev/null || echo "000")
    [ "$code" = "200" ]
}

check_status() {
    local output
    output=$(openclaw status 2>&1 || true)
    echo "$output" | grep -qi "reachable\|running\|online"
}

try_repair() {
    log "Starting doctor --fix repair..."
    openclaw doctor --fix --non-interactive >> "$LOG_FILE" 2>&1 || true
    sleep 5

    if ! check_process; then
        log "Process not running, attempting kickstart..."
        launchctl kickstart -k "gui/$(id -u)/ai.openclaw.node" >> "$LOG_FILE" 2>&1 || true
        sleep 10
    fi
}

main() {
    mkdir -p "$(dirname "$LOG_FILE")"
    local now
    now=$(date +%s)

    local state
    state=$(read_state)
    local failures cooldown_until
    failures=$(get_field "$state" "failures")
    cooldown_until=$(get_field "$state" "cooldown_until")
    : "${failures:=0}"
    : "${cooldown_until:=0}"

    if [ "$now" -lt "$cooldown_until" ]; then
        log "In cooldown, skipping check (remaining $((cooldown_until - now))s)"
        exit 0
    fi

    local healthy=true
    local fail_layer=""

    if ! check_process; then
        healthy=false
        fail_layer="process"
    elif ! check_http; then
        healthy=false
        fail_layer="http"
    elif ! check_status; then
        healthy=false
        fail_layer="status"
    fi

    if [ "$healthy" = true ]; then
        if [ "$failures" -gt 0 ]; then
            log "Gateway recovered, resetting failure count (was ${failures})"
            write_state 0 0 0
        fi
        exit 0
    fi

    failures=$((failures + 1))
    log "Health check failed [layer=${fail_layer}] (consecutive failure #${failures})"

    if [ "$failures" -le "$MAX_REPAIR" ]; then
        try_repair

        if check_http; then
            log "Repair successful! Gateway recovered"
            notify "Gateway issue (${fail_layer}) → doctor --fix repair succeeded (attempt ${failures})"
            write_state 0 "$now" 0
        else
            log "Still unhealthy after repair (${failures}/${MAX_REPAIR})"
            write_state "$failures" "$now" 0
        fi
    else
        local cooldown_end=$((now + COOLDOWN_SECONDS))
        log "Max repairs (${MAX_REPAIR}) exceeded, entering ${COOLDOWN_SECONDS}s cooldown"
        notify "⚠️ Gateway persistent failure (${fail_layer}), doctor --fix failed ${MAX_REPAIR} times. Cooldown ${COOLDOWN_SECONDS}s. Manual intervention needed."
        write_state "$failures" "$now" "$cooldown_end"
    fi
}

main "$@"
GUARDIAN_EOF
chmod +x "$OPENCLAW_DIR/scripts/guardian-check.sh"
success "Guardian script written"

# ============================================================================
# Step 8: LaunchAgents (auto-start on boot)
# ============================================================================
step 8 "Set up LaunchAgents for auto-start"

LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"

# Find openclaw install path
OPENCLAW_BIN=$(which openclaw 2>/dev/null || echo "$HOME/Library/pnpm/openclaw")
if [ ! -x "$OPENCLAW_BIN" ]; then
    # Try common fallback locations
    for candidate in "$HOME/.local/bin/openclaw" "$HOME/Library/pnpm/openclaw"; do
        if [ -x "$candidate" ]; then
            OPENCLAW_BIN="$candidate"
            break
        fi
    done
fi

# Build PATH string for LaunchAgents
LAUNCH_PATH="$HOME/.local/bin:$HOME/Library/pnpm:$HOME/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Gateway plist
cat > "$LAUNCH_DIR/ai.openclaw.gateway.plist" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.openclaw.gateway</string>
    <key>ProgramArguments</key>
    <array>
        <string>${OPENCLAW_BIN}</string>
        <string>gateway</string>
        <string>--port</string>
        <string>18789</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${LAUNCH_PATH}</string>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>OPENCLAW_GATEWAY_PORT</key>
        <string>18789</string>
        <key>OPENCLAW_GATEWAY_TOKEN</key>
        <string>${GATEWAY_TOKEN}</string>
PLIST_EOF

# Add Discord bot token if provided
if [ -n "$DISCORD_BOT_TOKEN" ]; then
    cat >> "$LAUNCH_DIR/ai.openclaw.gateway.plist" <<PLIST_DISCORD
        <key>DISCORD_BOT_TOKEN</key>
        <string>${DISCORD_BOT_TOKEN}</string>
PLIST_DISCORD
fi

cat >> "$LAUNCH_DIR/ai.openclaw.gateway.plist" <<PLIST_TAIL
    </dict>
    <key>StandardOutPath</key>
    <string>${OPENCLAW_DIR}/logs/gateway.log</string>
    <key>StandardErrorPath</key>
    <string>${OPENCLAW_DIR}/logs/gateway.err.log</string>
</dict>
</plist>
PLIST_TAIL
success "Gateway LaunchAgent created"

# Node plist
cat > "$LAUNCH_DIR/ai.openclaw.node.plist" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.openclaw.node</string>
    <key>ProgramArguments</key>
    <array>
        <string>${OPENCLAW_BIN}</string>
        <string>node</string>
        <string>run</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>18789</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${LAUNCH_PATH}</string>
        <key>HOME</key>
        <string>${HOME}</string>
PLIST_EOF

if [ -n "$DISCORD_BOT_TOKEN" ]; then
    cat >> "$LAUNCH_DIR/ai.openclaw.node.plist" <<PLIST_DISCORD
        <key>DISCORD_BOT_TOKEN</key>
        <string>${DISCORD_BOT_TOKEN}</string>
PLIST_DISCORD
fi

cat >> "$LAUNCH_DIR/ai.openclaw.node.plist" <<PLIST_TAIL
    </dict>
    <key>StandardOutPath</key>
    <string>${OPENCLAW_DIR}/logs/node.log</string>
    <key>StandardErrorPath</key>
    <string>${OPENCLAW_DIR}/logs/node.err.log</string>
</dict>
</plist>
PLIST_TAIL
success "Node LaunchAgent created"

# Guardian plist (every 60s health check)
cat > "$LAUNCH_DIR/ai.openclaw.guardian.plist" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.openclaw.guardian</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${OPENCLAW_DIR}/scripts/guardian-check.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${LAUNCH_PATH}</string>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>OPENCLAW_GATEWAY_PORT</key>
        <string>18789</string>
PLIST_EOF

if [ -n "$DISCORD_WEBHOOK_URL" ]; then
    cat >> "$LAUNCH_DIR/ai.openclaw.guardian.plist" <<PLIST_WEBHOOK
        <key>DISCORD_WEBHOOK_URL</key>
        <string>${DISCORD_WEBHOOK_URL}</string>
PLIST_WEBHOOK
fi

cat >> "$LAUNCH_DIR/ai.openclaw.guardian.plist" <<PLIST_TAIL
    </dict>
    <key>StandardOutPath</key>
    <string>${OPENCLAW_DIR}/logs/guardian-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${OPENCLAW_DIR}/logs/guardian-stderr.log</string>
</dict>
</plist>
PLIST_TAIL
success "Guardian LaunchAgent created"

# Chrome CDP plist (auto-start Chrome with remote debugging on port 9222)
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_DATA_DIR="${HOME}/.openclaw/chrome-profile"
mkdir -p "$CHROME_DATA_DIR"

cat > "$LAUNCH_DIR/ai.openclaw.chrome.plist" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.openclaw.chrome</string>
    <key>ProgramArguments</key>
    <array>
        <string>${CHROME_BIN}</string>
        <string>--remote-debugging-port=9222</string>
        <string>--user-data-dir=${CHROME_DATA_DIR}</string>
        <string>--no-first-run</string>
        <string>--no-default-browser-check</string>
    </array>
    <key>KeepAlive</key>
    <false/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${OPENCLAW_DIR}/logs/chrome-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${OPENCLAW_DIR}/logs/chrome-stderr.log</string>
</dict>
</plist>
PLIST_EOF
success "Chrome CDP LaunchAgent created (port 9222)"

# ============================================================================
# Step 9: Generate CLAUDE.md for OpenClaw init
# ============================================================================
step 9 "Generate CLAUDE.md for OpenClaw initialization"

cat > "$OPENCLAW_DIR/workspace/CLAUDE.md" <<'CLAUDEMD_EOF'
# OpenClaw Workspace

## System

This is an OpenClaw-managed workspace. The AI assistant runs on Amazon Bedrock (Claude models).

## Rules

- Always respond in the user's preferred language
- Be concise and helpful
- For code tasks: read before edit, verify after change
- Never delete files directly — move to trash instead
- When unsure, ask for clarification

## Tools Available

- **Claude Code**: Full coding agent (via ACP)
- **Browser**: Chrome DevTools Protocol on port 9222
- **Shell**: Execute system commands

## Quick Start

After setup, OpenClaw is accessible via:
- Control UI: http://127.0.0.1:18789
- Discord (if configured)
- Terminal: `openclaw chat`
CLAUDEMD_EOF
success "CLAUDE.md written"

# ============================================================================
# Step 10: Start services
# ============================================================================
step 10 "Start OpenClaw services"

# Unload first in case they exist
la_unload "$LAUNCH_DIR/ai.openclaw.chrome.plist"
la_unload "$LAUNCH_DIR/ai.openclaw.gateway.plist"
la_unload "$LAUNCH_DIR/ai.openclaw.node.plist"
la_unload "$LAUNCH_DIR/ai.openclaw.guardian.plist"

sleep 1

# Start Chrome CDP first (MCP servers depend on it)
la_load "$LAUNCH_DIR/ai.openclaw.chrome.plist"
info "Chrome CDP LaunchAgent loaded (port 9222)"

sleep 2

# Load and start OpenClaw services
la_load "$LAUNCH_DIR/ai.openclaw.gateway.plist"
info "Gateway LaunchAgent loaded"

sleep 3

la_load "$LAUNCH_DIR/ai.openclaw.node.plist"
info "Node LaunchAgent loaded"

sleep 2

la_load "$LAUNCH_DIR/ai.openclaw.guardian.plist"
info "Guardian LaunchAgent loaded"

# Wait for gateway to come up
info "Waiting for gateway to start..."
for i in $(seq 1 15); do
    if curl -s -o /dev/null -w "%{http_code}" -m 2 "http://127.0.0.1:18789/" 2>/dev/null | grep -q "200"; then
        success "Gateway is running on port 18789!"
        break
    fi
    sleep 2
    [ "$i" -eq 15 ] && warn "Gateway not responding yet. Check logs: ~/.openclaw/logs/gateway.log"
done

# ============================================================================
# Step 11: Smoke test
# ============================================================================
step 11 "验证安装"

SMOKE_PASS=0
SMOKE_FAIL=0

smoke_check() {
    local name="$1" cmd="$2"
    if eval "$cmd" >/dev/null 2>&1; then
        success "$name"
        SMOKE_PASS=$((SMOKE_PASS + 1))
    else
        warn "$name — 未通过（可稍后手动检查）"
        SMOKE_FAIL=$((SMOKE_FAIL + 1))
    fi
}

smoke_check "AWS CLI 可用" "aws --version"
smoke_check "Claude Code 可用" "claude --version"
smoke_check "OpenClaw 可用" "openclaw --version"
smoke_check "Gateway 端口响应" "curl -s -m 3 http://127.0.0.1:18789/ -o /dev/null"
smoke_check "AWS 凭证有效" "aws sts get-caller-identity"

info "冒烟测试结果：${SMOKE_PASS} 通过，${SMOKE_FAIL} 未通过"
if [ "$SMOKE_FAIL" -gt 0 ]; then
    warn "有未通过的检查项，但不影响大部分功能。可以先继续使用，后续再排查。"
fi

# ============================================================================
# Step 12: Repair script for emergencies
# ============================================================================
step 12 "创建紧急修复脚本"

cat > "$OPENCLAW_DIR/scripts/repair.sh" <<'REPAIR_EOF'
#!/bin/bash
# repair.sh — Emergency repair for OpenClaw
# Double-click in ~/Documents/OneClaw/, or run: bash ~/Documents/OneClaw/repair.command

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "\n${CYAN}${BOLD}=== OpenClaw Emergency Repair ===${NC}\n"

_GUI_UID=$(id -u)
_la_load() {
    local plist="$1" label
    label=$(basename "$plist" .plist)
    if [ "$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)" -ge 13 ] 2>/dev/null; then
        launchctl bootstrap "gui/${_GUI_UID}" "$plist" 2>/dev/null || \
            launchctl kickstart -k "gui/${_GUI_UID}/${label}" 2>/dev/null || true
    else
        launchctl load "$plist" 2>/dev/null || true
    fi
}
_la_unload() {
    local plist="$1" label
    label=$(basename "$plist" .plist)
    if [ "$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)" -ge 13 ] 2>/dev/null; then
        launchctl bootout "gui/${_GUI_UID}/${label}" 2>/dev/null || true
    else
        launchctl unload "$plist" 2>/dev/null || true
    fi
}

echo -e "${YELLOW}[1/5] Stopping all services...${NC}"
_la_unload ~/Library/LaunchAgents/ai.openclaw.chrome.plist
_la_unload ~/Library/LaunchAgents/ai.openclaw.gateway.plist
_la_unload ~/Library/LaunchAgents/ai.openclaw.node.plist
_la_unload ~/Library/LaunchAgents/ai.openclaw.guardian.plist
pkill -f "openclaw gateway" 2>/dev/null || true
pkill -f "openclaw node" 2>/dev/null || true
sleep 2

echo -e "${YELLOW}[2/5] Clearing state files...${NC}"
rm -f /tmp/openclaw-guardian-state.json

echo -e "${YELLOW}[3/5] Running openclaw doctor --fix...${NC}"
openclaw doctor --fix --non-interactive 2>&1 || true
sleep 2

echo -e "${YELLOW}[4/5] Restarting services...${NC}"
_la_load ~/Library/LaunchAgents/ai.openclaw.chrome.plist
sleep 2
_la_load ~/Library/LaunchAgents/ai.openclaw.gateway.plist
sleep 3
_la_load ~/Library/LaunchAgents/ai.openclaw.node.plist
sleep 2
_la_load ~/Library/LaunchAgents/ai.openclaw.guardian.plist

echo -e "${YELLOW}[5/5] Waiting for gateway...${NC}"
for i in $(seq 1 15); do
    if curl -s -o /dev/null -m 2 "http://127.0.0.1:18789/" 2>/dev/null; then
        echo -e "\n${GREEN}${BOLD}Gateway is back online!${NC}"
        echo -e "Control panel: ${CYAN}http://127.0.0.1:18789${NC}\n"
        exit 0
    fi
    sleep 2
done

echo -e "\n${RED}${BOLD}Gateway still not responding.${NC}"
echo -e "Try the AI repair command (copy-paste into terminal):\n"
echo -e "  ${CYAN}bash ~/Documents/OneClaw/ai-repair.command${NC}\n"
echo -e "Or check logs manually:"
echo "  tail -50 ~/.openclaw/logs/gateway.log"
echo "  tail -50 ~/.openclaw/logs/gateway.err.log"
REPAIR_EOF
chmod +x "$OPENCLAW_DIR/scripts/repair.sh"

# Copy repair.sh to ~/Documents/OneClaw/ and create symlink
cp "$OPENCLAW_DIR/scripts/repair.sh" "$HOME/Documents/OneClaw/repair.command"
chmod +x "$HOME/Documents/OneClaw/repair.command"
ln -sf "repair.command" "$HOME/Documents/OneClaw/一键修复.command"
success "Repair script created: ~/Documents/OneClaw/repair.command (一键修复)"

# ============================================================================
# Step 13: Optional — Ghostty terminal config
# ============================================================================
if [ "$INSTALL_GHOSTTY" = "true" ]; then
    step 13 "配置 Ghostty 终端"

    GHOSTTY_DIR="$HOME/.config/ghostty"
    GHOSTTY_THEME_DIR="$GHOSTTY_DIR/themes"
    mkdir -p "$GHOSTTY_THEME_DIR"

    # Write optimized Ghostty config for Claude Code
    cat > "$GHOSTTY_DIR/config" <<'GHOSTTY_EOF'
# Ghostty config — optimized for Claude Code
# https://ghostty.org/docs/config

# Font
font-family = JetBrains Mono
font-size = 14

# Theme — dark
theme = catppuccin-mocha

# Window
window-decoration = true
window-padding-x = 8
window-padding-y = 4
macos-titlebar-style = tabs

# Performance
gtk-single-instance = true

# Shell integration — prompt jumping and semantic regions
shell-integration = zsh
shell-integration-features = cursor,sudo,title

# Scrollback — Claude Code output can be very long
scrollback-limit = 100000

# Terminal type — best compatibility for SSH
term = xterm-256color

# Clipboard
clipboard-read = allow
clipboard-write = allow
copy-on-select = clipboard

# Mouse — reduce conflicts with Claude Code TUI
mouse-hide-while-typing = true

# Image support — Claude Code uses Kitty protocol for images
image-storage-limit = 320000000

# Cursor
cursor-style = block
cursor-style-blink = false

# Window close protection — prevent accidental Claude Code kills
confirm-close-surface = true

# Notifications — task completion alerts
desktop-notifications = true

# Keybindings
keybind = super+t=new_tab
keybind = super+w=close_surface
keybind = super+shift+left_bracket=previous_tab
keybind = super+shift+right_bracket=next_tab

# Fast scrolling for long Claude Code output
keybind = super+shift+k=scroll_page_up
keybind = super+shift+j=scroll_page_down
keybind = super+home=scroll_to_top
keybind = super+end=scroll_to_bottom

# Jump between Claude Code responses
keybind = ctrl+shift+up=jump_to_prompt:-1
keybind = ctrl+shift+down=jump_to_prompt:1
GHOSTTY_EOF

    # Install catppuccin-mocha theme
    cat > "$GHOSTTY_THEME_DIR/catppuccin-mocha" <<'THEME_EOF'
palette = 0=#45475a
palette = 1=#f38ba8
palette = 2=#a6e3a1
palette = 3=#f9e2af
palette = 4=#89b4fa
palette = 5=#f5c2e7
palette = 6=#94e2d5
palette = 7=#bac2de
palette = 8=#585b70
palette = 9=#f38ba8
palette = 10=#a6e3a1
palette = 11=#f9e2af
palette = 12=#89b4fa
palette = 13=#f5c2e7
palette = 14=#94e2d5
palette = 15=#a6adc8
background = 1e1e2e
foreground = cdd6f4
cursor-color = f5e0dc
cursor-text = 1e1e2e
selection-background = 585b70
selection-foreground = cdd6f4
THEME_EOF

    success "Ghostty 配置已写入 ~/.config/ghostty/config"
    info "主题: catppuccin-mocha | 字体: JetBrains Mono 14px"
    info "如果还没安装 Ghostty，可从 https://ghostty.org 下载"
fi

# ============================================================================
# Done!
# ============================================================================
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║            安装完成！🎉                           ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "${BOLD}已安装的组件：${NC}"
echo "  ✅ fnm, Node.js, pnpm, lark-cli, uv, AWS CLI"
echo "  ✅ Claude Code（通过 Bedrock 调用 Claude 模型）"
echo "  ✅ Claude Code Sub-Agents（architect, code-reviewer, researcher 等）"
echo "  ✅ OpenClaw（Gateway + Node + Guardian 守护进程）"
echo "  ✅ MCP 服务器（Chrome DevTools、AWS 文档）"
echo "  ✅ 开机自启动（LaunchAgents）"
echo "  ✅ 健康监控（每 60 秒自动检查）"
echo ""

echo -e "${BOLD}常用命令：${NC}"
echo "  claude                              — 启动 Claude Code（AI 编程助手）"
echo "  openclaw chat                       — 和 OpenClaw 对话"
echo "  openclaw status                     — 查看 OpenClaw 运行状态"
echo "  openclaw doctor                     — 诊断问题"
echo ""

echo -e "${BOLD}出问题了？打开访达 → 文稿 → OneClaw 文件夹，双击运行：${NC}"
echo -e "  📁 ~/Documents/OneClaw/${GREEN}repair.command${NC}       — 重启所有服务（中文别名：一键修复）"
echo -e "  📁 ~/Documents/OneClaw/${GREEN}ai-repair.command${NC}    — AI 自动诊断+修复（中文别名：AI修复）"
echo -e "  📁 ~/Documents/OneClaw/${GREEN}open-claude.command${NC}  — 用中文和 Claude 对话（中文别名：打开Claude对话）"
echo -e "  ${YELLOW}双击即可运行，无需其他操作${NC}"
echo ""

echo -e "${BOLD}控制面板：${NC}"
echo "  http://127.0.0.1:18789              — 在浏览器打开 OpenClaw 控制台"
echo ""
echo -e "${BOLD}Gateway Token（登录控制台时需要，请复制保存）：${NC}"
echo -e "  ${GREEN}${BOLD}${GATEWAY_TOKEN}${NC}"
echo ""


# Make PATH available in the CURRENT shell immediately (no need to open a new terminal)
export PATH="$HOME/.local/bin:$HOME/Library/pnpm:$HOME/.cargo/bin:$PATH"
eval "$(fnm env 2>/dev/null)" || true
hash -r 2>/dev/null || true

echo -e "${YELLOW}${BOLD}接下来做什么：${NC}"
if command -v claude >/dev/null 2>&1; then
    echo -e "  直接在这个终端输入：${CYAN}claude${NC}  然后按回车"
else
    echo -e "  按 ${GREEN}Command + N${NC} 打开一个新的终端窗口"
    echo -e "  在新窗口输入：${CYAN}claude${NC}  然后按回车"
fi
echo -e "  Claude Code 启动后，你可以用中文和它对话，让它帮你写代码、排查问题"
echo ""
echo -e "${BOLD}已装的 Claude Code Skills（放在 ~/.claude/skills/）：${NC}"
echo -e "  coding-standards / security-review / python-patterns / frontend-patterns"
echo -e "  backend-patterns / api-design / docker-patterns / database-migrations"
echo -e "  deployment-patterns / openclaw-upgrade"
echo -e "  ${CYAN}用法示例${NC}：在 Claude Code 里直接说「用 openclaw-upgrade 把 openclaw 升级到 latest」"
echo -e "  完整目录：https://github.com/cncoder/oneclaw/tree/main/skills"
echo ""

if [ -n "$DISCORD_BOT_TOKEN" ]; then
    echo -e "  Discord 机器人已配置，OpenClaw 下次启动时会自动连接。"
fi

# Auto-open OpenClaw control panel in browser (only if gateway is up)
if curl -s -o /dev/null -m 2 "http://127.0.0.1:18789/" 2>/dev/null; then
    info "正在打开 OpenClaw 控制面板..."
    open "http://127.0.0.1:18789"
else
    info "Gateway 尚未就绪，请稍后手动打开: http://127.0.0.1:18789"
fi

echo -e "${CYAN}${BOLD}遇到任何问题？${NC}"
echo ""
echo -e "  打开终端，输入 ${GREEN}${BOLD}claude${NC} 进入 AI 交互模式，直接用中文描述你的问题，比如："
echo -e "  ${CYAN}「OpenClaw 报 AWS 签名错误，帮我修一下」${NC}"
echo -e "  ${CYAN}「Chrome 连不上 OpenClaw」${NC}"
echo -e "  ${CYAN}「帮我检查 AWS 凭证是否正确」${NC}"
echo ""
echo -e "  或者打开访达 → 文稿 → OneClaw，双击脚本让 AI 全自动修复："
echo -e "  ${GREEN}~/Documents/OneClaw/ai-repair.command${NC}    — AI 自动诊断+修复（约 1-3 分钟）"
echo -e "  ${GREEN}~/Documents/OneClaw/repair.command${NC}      — 一键重启所有服务"
echo ""
echo -e "${GREEN}${BOLD}享受你的 AI 编程环境吧！${NC}"
