# OneClaw

One-click setup for **Claude Code + OpenClaw + AWS** on Mac Apple Silicon.

Zero technical knowledge required — open Terminal, paste one command, enter your AWS keys, done.

[中文文档](README.zh.md)

## Quick Start

Open **Terminal** and run:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/cncoder/oneclaw/main/setup.sh)"
```

Or download first, then run:

```bash
curl -O https://raw.githubusercontent.com/cncoder/oneclaw/main/setup.sh
bash setup.sh
```

## Prerequisites

| Item | Required? | Description |
|------|-----------|-------------|
| AWS Access Key + Secret Key | Yes | For accessing Bedrock Claude models |
| Discord Bot Token | No | Connect OpenClaw to Discord chat |
| Discord Webhook URL | No | Alert notifications on system errors |

## What Gets Installed

- **Homebrew** — macOS package manager
- **Node.js** — JavaScript runtime
- **pnpm** — Fast package manager
- **uv / uvx** — Python package manager (for MCP servers)
- **AWS CLI** — AWS command-line tools
- **Claude Code** — AI coding assistant (via Bedrock)
- **OpenClaw** — AI Agent framework (Gateway + Node)
- **MCP Servers** — Chrome DevTools, AWS Documentation
- **Guardian Daemon** — Health check every 60s + auto-repair
- **LaunchAgents** — Auto-start on boot

## Usage

```bash
claude                              # Launch Claude Code
openclaw chat                       # Chat with OpenClaw
openclaw status                     # Check OpenClaw status
openclaw doctor                     # Diagnose issues
```

## Web Dashboard

After installation, open http://127.0.0.1:18789 in your browser for the OpenClaw control panel.

## Manual Install (if one-click fails)

If the script fails at a specific step, you can install the prerequisites manually and re-run the script — it will skip anything already installed.

```bash
# 1. Xcode Command Line Tools
xcode-select --install

# 2. Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zshrc
eval "$(/opt/homebrew/bin/brew shellenv)"

# 3. Node.js + pnpm
brew install node
npm install -g pnpm

# 4. uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 5. AWS CLI
brew install awscli

# 6. Claude Code
curl -fsSL https://claude.ai/install.sh | bash

# 7. OpenClaw
curl -fsSL https://openclaw.ai/install.sh | bash
```

After installing the prerequisites, re-run the setup script to configure everything:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/cncoder/oneclaw/main/setup.sh)"
```

## Troubleshooting

### Option 1: One-Click Repair (Desktop Shortcut)

Two repair scripts are placed on your Desktop after installation:

```bash
bash ~/Desktop/repair-openclaw.sh       # Stop → clean → restart (fixes 99% of issues)
```

### Option 2: AI-Powered Repair (Recommended)

Let Claude Code automatically read logs, diagnose issues, and fix them:

```bash
bash ~/Desktop/ai-repair-openclaw.sh    # Claude auto-diagnoses + fixes (~1-3 min)
```

This launches Claude Code which will automatically:
- Run `openclaw status` and `openclaw doctor`
- Read gateway/node/chrome error logs
- Check LaunchAgent and port status
- Verify AWS credentials
- **Auto-fix any issues found**
- Restart all services and verify

### Option 3: Check Logs

```bash
tail -50 ~/.openclaw/logs/gateway.log      # Gateway log
tail -50 ~/.openclaw/logs/gateway.err.log  # Gateway error log
tail -50 ~/.openclaw/logs/guardian.log     # Guardian daemon log
```

### Option 4: Reinstall

Just run `setup.sh` again — already-installed components will be skipped.

## Security

- AWS credentials stay local in `~/.aws/credentials`, never uploaded
- Gateway token is auto-generated, bound to loopback (localhost only)
- No hardcoded secrets in the script
- All services listen on 127.0.0.1 only

## File Layout

```
~/Desktop/
├── repair-openclaw.sh          One-click repair (desktop shortcut)
└── ai-repair-openclaw.sh       AI-powered repair (desktop shortcut)
~/.aws/                         AWS credentials
~/.claude/settings.json         Claude Code config
~/.mcp.json                     MCP server config
~/.openclaw/
├── openclaw.json               OpenClaw main config
├── chrome-profile/             Chrome CDP data directory
├── logs/                       All logs
├── scripts/
│   ├── guardian-check.sh       Guardian daemon script
│   ├── repair.sh              Emergency repair script
│   └── ai-repair.sh           AI-powered repair script
└── workspace/                  OpenClaw workspace
    └── CLAUDE.md              Workspace instructions
~/Library/LaunchAgents/
├── ai.openclaw.chrome.plist    Chrome CDP auto-start (port 9222)
├── ai.openclaw.gateway.plist   Gateway auto-start
├── ai.openclaw.node.plist      Node auto-start
└── ai.openclaw.guardian.plist  Guardian daemon auto-start
```

## License

MIT
