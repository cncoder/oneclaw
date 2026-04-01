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

## System Requirements

- **macOS 13 (Ventura)** or later
- **Apple Silicon** (M1 / M2 / M3 / M4) — Intel Macs are not supported
- **16 GB RAM** recommended (8 GB minimum)
- **~5 GB free disk space** (Node.js, Chrome, OpenClaw, etc.)
- Internet connection during installation

## Prerequisites

| Item | Required? | Description |
|------|-----------|-------------|
| AWS Access Key + Secret Key | Yes | For accessing Bedrock Claude models |
| Discord Bot Token | No | Connect OpenClaw to Discord chat |
| Discord Webhook URL | No | Alert notifications on system errors |

### IAM Permissions Required

The AWS IAM user needs the following permissions:

**Easiest**: Attach the AWS managed policy `AmazonBedrockFullAccess`

**Least-privilege policy** (recommended for production):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:ListFoundationModels",
        "bedrock:GetFoundationModel"
      ],
      "Resource": "arn:aws:bedrock:*::foundation-model/*"
    }
  ]
}
```

> **You also need to enable model access in the Bedrock console**: AWS Console → Bedrock → Model access → Select all Anthropic Claude models → Save changes

## What Gets Installed

- **fnm** — Fast Node Manager (manages Node.js versions)
- **Node.js** — JavaScript runtime (installed via fnm)
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

# 2. fnm + Node.js
curl -fsSL https://fnm.vercel.app/install | bash
source ~/.zshrc
fnm install --lts

# 3. pnpm
corepack enable && corepack prepare pnpm@latest --activate
# or: npm install -g pnpm

# 4. uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 5. AWS CLI (official installer)
curl -fsSL "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o /tmp/AWSCLIV2.pkg
sudo installer -pkg /tmp/AWSCLIV2.pkg -target /

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

### Option 1: One-Click Repair

Open **Finder → Documents → OneClaw** and double-click:

- **`一键修复.command`** — Stop → clean → restart all services (fixes 99% of issues)

### Option 2: AI-Powered Repair (Recommended)

Open **Finder → Documents → OneClaw** and double-click:

- **`AI修复.command`** — Claude auto-diagnoses + fixes (~1-3 min)

Claude Code will automatically:
- Run `openclaw status` and `openclaw doctor`
- Read gateway/node/chrome error logs
- Check LaunchAgent and port status
- Verify AWS credentials
- **Auto-fix any issues found**
- Restart all services and verify

### Option 3: Chat with Claude

Open **Finder → Documents → OneClaw** and double-click:

- **`打开Claude对话.command`** — Describe your problem in Chinese, Claude will help

### Option 4: Upgrade (existing users)

If you installed an older version, run this once to get the latest shortcuts:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/cncoder/oneclaw/main/fix.sh)"
```

### Option 5: Check Logs

```bash
tail -50 ~/.openclaw/logs/gateway.log      # Gateway log
tail -50 ~/.openclaw/logs/gateway.err.log  # Gateway error log
tail -50 ~/.openclaw/logs/guardian.log     # Guardian daemon log
```

### Option 6: Reinstall

Just run `setup.sh` again — already-installed components will be skipped.

## Skills

The `skills/` directory contains 9 pre-built Skills covering every core Claude Code use case — from browser automation to infrastructure ops.

See [skills/README.md](skills/README.md) for the full catalog of 9 skills covering every Claude Code use case.

## Uninstall

To completely remove OneClaw and all its components:

```bash
# 1. Stop and remove LaunchAgents
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.*.plist 2>/dev/null
rm -f ~/Library/LaunchAgents/ai.openclaw.*.plist

# 2. Remove OpenClaw
openclaw uninstall 2>/dev/null   # if supported by your version
rm -rf ~/.openclaw

# 3. Remove OneClaw shortcuts
rm -rf ~/Documents/OneClaw

# 4. (Optional) Remove Claude Code
npm uninstall -g @anthropic-ai/claude-code 2>/dev/null

# 5. (Optional) Remove MCP config added by setup
# Review and edit ~/.mcp.json — remove the entries added by OneClaw
```

> fnm, Node.js, AWS CLI, and uv are shared tools — only remove them if no other project depends on them.

## Security

- AWS credentials stay local in `~/.aws/credentials`, never uploaded
- Gateway token is auto-generated, bound to loopback (localhost only)
- No hardcoded secrets in the script
- All services listen on 127.0.0.1 only

## File Layout

```
~/Documents/OneClaw/
├── 一键修复.command             One-click repair (double-click to run)
├── AI修复.command               AI-powered repair (double-click to run)
└── 打开Claude对话.command       Open Claude Code chat (double-click to run)
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
