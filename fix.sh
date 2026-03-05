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
if grep -q '"token": ""' "$CONFIG" 2>/dev/null || ! grep -q '"token"' "$CONFIG" 2>/dev/null; then
    NEW_TOKEN=$(openssl rand -hex 24)
    info "Generating new Gateway Token..."

    if command -v python3 &>/dev/null; then
        python3 -c "
import json, sys
with open('$CONFIG', 'r') as f:
    cfg = json.load(f)
if 'gateway' not in cfg:
    cfg['gateway'] = {}
if 'auth' not in cfg['gateway']:
    cfg['gateway']['auth'] = {}
cfg['gateway']['auth']['token'] = '$NEW_TOKEN'
cfg['gateway']['auth']['mode'] = 'token'
with open('$CONFIG', 'w') as f:
    json.dump(cfg, f, indent=2)
"
    else
        # Fallback: sed replace
        if grep -q '"token":' "$CONFIG"; then
            sed -i '' "s/\"token\": *\"[^\"]*\"/\"token\": \"$NEW_TOKEN\"/" "$CONFIG"
        else
            warn "Cannot auto-fix token without python3. Manual fix needed."
            echo -e "  Add this to gateway.auth in $CONFIG:"
            echo -e "  \"token\": \"$NEW_TOKEN\""
        fi
    fi
    success "Gateway Token set: ${NEW_TOKEN:0:8}..."
    echo -e "  ${YELLOW}Save this token if you need it for manual access:${NC}"
    echo -e "  ${BOLD}$NEW_TOKEN${NC}\n"
else
    EXISTING=$(grep -o '"token": *"[^"]*"' "$CONFIG" | head -1 | sed 's/"token": *"//' | sed 's/"//')
    if [ -n "$EXISTING" ] && [ "$EXISTING" != '${GATEWAY_TOKEN}' ]; then
        success "Gateway Token already set: ${EXISTING:0:8}..."
    else
        # Token contains unexpanded variable ${GATEWAY_TOKEN}
        NEW_TOKEN=$(openssl rand -hex 24)
        info "Token contains placeholder, generating real token..."
        if command -v python3 &>/dev/null; then
            python3 -c "
import json
with open('$CONFIG', 'r') as f:
    cfg = json.load(f)
cfg['gateway']['auth']['token'] = '$NEW_TOKEN'
with open('$CONFIG', 'w') as f:
    json.dump(cfg, f, indent=2)
"
        else
            sed -i '' "s/\\\${GATEWAY_TOKEN}/$NEW_TOKEN/" "$CONFIG"
        fi
        success "Gateway Token generated: ${NEW_TOKEN:0:8}..."
        echo -e "  ${BOLD}$NEW_TOKEN${NC}\n"
    fi
fi

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
