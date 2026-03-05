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
- **~5 GB free disk space** (Homebrew, Node.js, Chrome, OpenClaw, etc.)
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

## OpenClaw Skills (Recommended)

The `skills/` directory in this repo contains four pre-built Skills that significantly enhance OpenClaw + Claude Code:

| Skill | Description |
|-------|-------------|
| `claude-code` | Teaches OpenClaw how to effectively dispatch Claude Code: task splitting, progressive delivery, Slot Machine recovery, terminal interaction, debugging workflow |
| `aws-infra` | AWS infrastructure queries, auditing, and monitoring via AWS CLI — read-only by default, write actions require confirmation |
| `chrome-devtools` | Browser automation via Chrome DevTools Protocol (CDP): UI verification, web scraping, screenshot-based debugging, frontend testing |
| `skill-vetting` | Security review tool for vetting third-party Skills from ClawHub before installation, with automated scanner and prompt injection defense |

### Installation

Open Claude Code in your terminal and ask it to install:

```bash
claude
```

Then type:

```
Install the four skills (claude-code, aws-infra, chrome-devtools, skill-vetting) from
https://github.com/cncoder/oneclaw into OpenClaw.
Copy each skill directory to ~/.openclaw/workspace/skills/.
```

Or install manually:

```bash
git clone --depth 1 https://github.com/cncoder/oneclaw.git /tmp/oneclaw
cp -r /tmp/oneclaw/skills/claude-code ~/.openclaw/workspace/skills/
cp -r /tmp/oneclaw/skills/aws-infra ~/.openclaw/workspace/skills/
cp -r /tmp/oneclaw/skills/chrome-devtools ~/.openclaw/workspace/skills/
cp -r /tmp/oneclaw/skills/skill-vetting ~/.openclaw/workspace/skills/
rm -rf /tmp/oneclaw
```

## Uninstall

To completely remove OneClaw and all its components:

```bash
# 1. Stop and remove LaunchAgents
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.openclaw.*.plist 2>/dev/null
rm -f ~/Library/LaunchAgents/ai.openclaw.*.plist

# 2. Remove OpenClaw
openclaw uninstall 2>/dev/null   # if supported by your version
rm -rf ~/.openclaw

# 3. Remove desktop shortcuts
rm -f ~/Desktop/repair-openclaw.sh ~/Desktop/ai-repair-openclaw.sh

# 4. (Optional) Remove Claude Code
npm uninstall -g @anthropic-ai/claude-code 2>/dev/null

# 5. (Optional) Remove MCP config added by setup
# Review and edit ~/.mcp.json — remove the entries added by OneClaw
```

> Homebrew, Node.js, AWS CLI, and uv are shared tools — only remove them if no other project depends on them.

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
