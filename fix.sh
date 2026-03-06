#!/bin/bash
# fix.sh — OneClaw post-install fixer
# Fixes: Gateway Token missing, Chrome CDP not connecting, services not running
# Usage: bash -c "$(curl -fsSL https://raw.githubusercontent.com/cncoder/oneclaw/main/fix.sh)"

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

OPENCLAW_DIR="$HOME/.openclaw"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
CONFIG="$OPENCLAW_DIR/openclaw.json"

echo -e "\n${BOLD}OneClaw Fix Tool${NC}"
echo -e "Checking and fixing common issues...\n"

# ============================================================================
# 1. Check openclaw.json exists
# ============================================================================
if [ ! -f "$CONFIG" ]; then
    error "openclaw.json not found at $CONFIG. Please run setup.sh first."
fi

# ============================================================================
# 2. Fix Gateway Token
# ============================================================================
info "Checking Gateway Token..."

NEW_TOKEN=$(openssl rand -hex 24)

# Use python3 to reliably read JSON and check/fix token
TOKEN_STATUS=$(python3 -c "
import json, sys
try:
    with open('$CONFIG', 'r') as f:
        cfg = json.load(f)
except json.JSONDecodeError:
    print('BROKEN_JSON')
    sys.exit(0)

token = cfg.get('gateway', {}).get('auth', {}).get('token', '')
# Check if token is empty, placeholder, or missing
if not token or '\${' in token or len(token) < 8:
    # Fix it
    if 'gateway' not in cfg:
        cfg['gateway'] = {}
    if 'auth' not in cfg['gateway']:
        cfg['gateway']['auth'] = {}
    cfg['gateway']['auth']['token'] = '$NEW_TOKEN'
    cfg['gateway']['auth']['mode'] = 'token'
    with open('$CONFIG', 'w') as f:
        json.dump(cfg, f, indent=2)
    print('FIXED')
else:
    print('OK:' + token)
" 2>&1)

case "$TOKEN_STATUS" in
    FIXED)
        success "Gateway Token generated and injected!"
        echo ""
        echo -e "  ${BOLD}${YELLOW}Gateway Token:${NC}"
        echo -e "  ${BOLD}${GREEN}$NEW_TOKEN${NC}"
        echo ""
        echo -e "  ${YELLOW}Please save this token. You need it to log in to the web console.${NC}"
        echo ""
        ;;
    OK:*)
        EXISTING="${TOKEN_STATUS#OK:}"
        success "Gateway Token already set: ${EXISTING:0:8}..."
        echo ""
        echo -e "  ${BOLD}${YELLOW}Your Gateway Token:${NC}"
        echo -e "  ${BOLD}${GREEN}$EXISTING${NC}"
        echo ""
        ;;
    BROKEN_JSON)
        error "openclaw.json is invalid JSON. Please re-run setup.sh."
        ;;
    *)
        warn "Unexpected result: $TOKEN_STATUS"
        ;;
esac

# ============================================================================
# 3. Fix Chrome CDP
# ============================================================================
info "Checking Chrome CDP (port 9222)..."

CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_DATA_DIR="$OPENCLAW_DIR/chrome-profile"

if [ ! -f "$CHROME_BIN" ]; then
    warn "Google Chrome not found. Please install Chrome first."
else
    # Check if Chrome CDP is running
    if curl -s --connect-timeout 2 http://127.0.0.1:9222/json/version &>/dev/null; then
        success "Chrome CDP already running on port 9222"
    else
        info "Chrome CDP not responding, fixing..."

        # Kill any stuck Chrome CDP processes (only the openclaw profile ones)
        pkill -f "remote-debugging-port=9222" 2>/dev/null || true
        sleep 1

        # Ensure chrome-profile directory exists
        mkdir -p "$CHROME_DATA_DIR"

        # Recreate LaunchAgent plist
        mkdir -p "$LAUNCH_DIR"
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

        # Load LaunchAgent
        launchctl unload "$LAUNCH_DIR/ai.openclaw.chrome.plist" 2>/dev/null || true
        launchctl load "$LAUNCH_DIR/ai.openclaw.chrome.plist"

        # Wait for Chrome to start
        sleep 3

        if curl -s --connect-timeout 3 http://127.0.0.1:9222/json/version &>/dev/null; then
            success "Chrome CDP started successfully on port 9222"
        else
            warn "Chrome CDP failed to start. Try manually:"
            echo -e "  ${CYAN}\"$CHROME_BIN\" --remote-debugging-port=9222 --user-data-dir=$CHROME_DATA_DIR --no-first-run &${NC}"
        fi
    fi
fi

# ============================================================================
# 4. Restart OpenClaw services
# ============================================================================
info "Restarting OpenClaw services..."

for svc in gateway node guardian; do
    PLIST="$LAUNCH_DIR/ai.openclaw.${svc}.plist"
    if [ -f "$PLIST" ]; then
        launchctl unload "$PLIST" 2>/dev/null || true
        launchctl load "$PLIST"
        success "Restarted $svc"
    else
        warn "$svc plist not found at $PLIST"
    fi
done

sleep 3

# ============================================================================
# 5. Verify everything
# ============================================================================
echo -e "\n${BOLD}--- Verification ---${NC}\n"

# Gateway
if curl -s --connect-timeout 3 http://127.0.0.1:18789 &>/dev/null; then
    success "Gateway running on port 18789"
else
    warn "Gateway not responding on port 18789"
    echo -e "  Check logs: ${CYAN}tail -20 ~/.openclaw/logs/gateway.err.log${NC}"
fi

# Chrome CDP
if curl -s --connect-timeout 3 http://127.0.0.1:9222/json/version &>/dev/null; then
    success "Chrome CDP running on port 9222"
else
    warn "Chrome CDP not responding on port 9222"
    echo -e "  Check logs: ${CYAN}tail -20 ~/.openclaw/logs/chrome-stderr.log${NC}"
fi

# OpenClaw status
if command -v openclaw &>/dev/null; then
    echo ""
    info "Running openclaw status..."
    openclaw status 2>/dev/null || warn "openclaw status failed"
fi

echo -e "\n${GREEN}${BOLD}Fix complete!${NC}"
echo -e "Open ${CYAN}http://127.0.0.1:18789${NC} in your browser to access OpenClaw.\n"

# ============================================================================
# 6. Fix plist entrypoint mismatch (common cause of "service does not match install")
# ============================================================================
info "Checking plist entrypoint paths..."

ACTUAL_OPENCLAW=$(command -v openclaw 2>/dev/null || echo "")
if [ -z "$ACTUAL_OPENCLAW" ]; then
    # Try common paths
    for p in "$HOME/.local/bin/openclaw" "/opt/homebrew/bin/openclaw" "/usr/local/bin/openclaw"; do
        if [ -x "$p" ]; then
            ACTUAL_OPENCLAW="$p"
            break
        fi
    done
fi

if [ -z "$ACTUAL_OPENCLAW" ]; then
    warn "openclaw binary not found — skipping plist fix"
else
    FIXED_PLISTS=0
    for svc in gateway node; do
        PLIST="$LAUNCH_DIR/ai.openclaw.${svc}.plist"
        if [ -f "$PLIST" ]; then
            # Check if plist references a stale path
            if grep -q "ProgramArguments" "$PLIST"; then
                PLIST_BIN=$(python3 -c "
import plistlib, sys
with open('$PLIST','rb') as f:
    pl = plistlib.load(f)
args = pl.get('ProgramArguments', [])
print(args[0] if args else '')
" 2>/dev/null || echo "")
                if [ -n "$PLIST_BIN" ] && [ "$PLIST_BIN" != "$ACTUAL_OPENCLAW" ]; then
                    warn "Plist $svc: stale path $PLIST_BIN → fixing to $ACTUAL_OPENCLAW"
                    python3 -c "
import plistlib
with open('$PLIST','rb') as f:
    pl = plistlib.load(f)
pl['ProgramArguments'][0] = '$ACTUAL_OPENCLAW'
with open('$PLIST','wb') as f:
    plistlib.dump(pl, f)
print('fixed')
" 2>/dev/null && FIXED_PLISTS=$((FIXED_PLISTS+1))
                else
                    success "Plist $svc path OK: $PLIST_BIN"
                fi
            fi
        fi
    done
    [ "$FIXED_PLISTS" -gt 0 ] && success "Fixed $FIXED_PLISTS plist(s). Services will reload below."
fi

# ============================================================================
# 7. Check AWS credentials validity
# ============================================================================
info "Checking AWS credentials..."

if ! command -v aws &>/dev/null; then
    warn "AWS CLI not found — skipping credential check"
elif aws sts get-caller-identity &>/dev/null 2>&1; then
    ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "unknown")
    success "AWS credentials valid (Account: $ACCOUNT)"
else
    warn "AWS credentials invalid or expired!"
    echo ""
    echo -e "  ${YELLOW}Please re-enter your AWS credentials:${NC}"
    echo -e "  Run: ${CYAN}aws configure${NC}"
    echo -e "  Or update: ${CYAN}~/.aws/credentials${NC}"
    echo ""
fi

# ============================================================================
# 8. Restore desktop repair scripts (for users with older installs)
# ============================================================================
info "Checking desktop repair scripts..."

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# AI修复.command
mkdir -p "$HOME/Documents/OneClaw"
if [ ! -f "$HOME/Documents/OneClaw/AI修复.command" ] || ! grep -q "dangerously-skip-permissions" "$HOME/Documents/OneClaw/AI修复.command" 2>/dev/null; then
    info "Creating AI修复.command in ~/Documents/OneClaw/..."
    cat > "$HOME/Documents/OneClaw/AI修复.command" <<'AIREPAIR_EOF'
#!/bin/bash
# ai-repair.sh — Let Claude Code diagnose and fix OpenClaw automatically

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

if ! command -v claude >/dev/null 2>&1; then
    echo -e "${RED}Claude Code not found.${NC} Please run: source ~/.zshrc"
    exit 1
fi

echo ""
echo -e "${CYAN}${BOLD}AI Repair — Claude will automatically diagnose and fix OpenClaw${NC}"
echo -e "${YELLOW}This usually takes 1-3 minutes. Claude will run commands automatically.${NC}"
echo ""

REPAIR_PROMPT='You are an expert at diagnosing and fixing OpenClaw issues on macOS.

## Your Task
Diagnose and fix OpenClaw automatically. Follow these steps:

1. Run `openclaw status` and `openclaw doctor`
2. Read logs:
   - `tail -50 ~/.openclaw/logs/gateway.log`
   - `tail -50 ~/.openclaw/logs/gateway.err.log`
   - `tail -50 ~/.openclaw/logs/node.err.log`
   - `tail -30 ~/.openclaw/logs/guardian.log`
3. Check ports: `curl -s http://127.0.0.1:18789` and `curl -s http://127.0.0.1:9222/json/version`
4. Fix any issues found:
   - If plist entrypoint mismatch: update plist ProgramArguments[0] to the actual openclaw binary path
   - If services not running: `launchctl unload` then `launchctl load` each plist
   - If gateway token missing: generate one and inject into ~/.openclaw/openclaw.json
5. Reload services:
   `launchctl unload ~/Library/LaunchAgents/ai.openclaw.gateway.plist` → wait 2s
   `launchctl load ~/Library/LaunchAgents/ai.openclaw.gateway.plist` → wait 3s
   `launchctl unload ~/Library/LaunchAgents/ai.openclaw.node.plist` → wait 2s
   `launchctl load ~/Library/LaunchAgents/ai.openclaw.node.plist` → wait 2s
   `launchctl unload ~/Library/LaunchAgents/ai.openclaw.guardian.plist`
   `launchctl load ~/Library/LaunchAgents/ai.openclaw.guardian.plist`
6. Verify: `curl -s http://127.0.0.1:18789/` should return 200

## Output
Print a clear summary in Chinese of what you found and what you fixed.'

claude --dangerously-skip-permissions -p "$REPAIR_PROMPT" --output-format text 2>&1

echo ""
echo -e "${GREEN}${BOLD}AI repair complete.${NC}"
echo -e "If issues persist, check: ${CYAN}https://github.com/cncoder/oneclaw/issues${NC}"
echo ""
AIREPAIR_EOF
    chmod +x "$HOME/Documents/OneClaw/AI修复.command"
    success "Created ~/Documents/OneClaw/AI修复.command"
else
    success "AI修复.command already up to date"
fi

# 打开Claude对话.command
if [ ! -f "$HOME/Documents/OneClaw/打开Claude对话.command" ]; then
    info "Creating 打开Claude对话.command in ~/Documents/OneClaw/..."
    cat > "$HOME/Documents/OneClaw/打开Claude对话.command" <<'ASKCLAUDE_EOF'
#!/bin/bash
# 打开Claude对话.command — Open Claude Code in interactive mode

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v claude >/dev/null 2>&1; then
    echo "Claude Code not found. Please run: source ~/.zshrc"
    exit 1
fi

echo ""
echo "  正在启动 Claude Code..."
echo "  用中文描述你的问题，例如："
echo "    「OpenClaw 报 AWS 签名错误，帮我修一下」"
echo "    「Chrome 连不上」"
echo "    「帮我看看日志哪里出错了」"
echo ""

cd ~/.openclaw/workspace 2>/dev/null || cd ~
claude
ASKCLAUDE_EOF
    chmod +x "$HOME/Documents/OneClaw/打开Claude对话.command"
    success "Created ~/Documents/OneClaw/打开Claude对话.command"
else
    success "打开Claude对话.command already exists"
fi

echo ""
echo -e "${BOLD}快捷方式位置：访达 → 文稿 → OneClaw${NC}"
echo -e "  ${GREEN}AI修复.command${NC}         — AI 全自动诊断+修复（约 1-3 分钟，双击运行）"
echo -e "  ${GREEN}打开Claude对话.command${NC} — 打开 Claude 对话，用中文描述任何问题"
echo ""
