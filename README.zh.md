# OneClaw

一键安装 Claude Code + OpenClaw + AWS 全家桶，专为 Mac Apple Silicon 设计。

**完全不懂技术的小白也能用** — 打开终端，粘贴一行命令，按提示输入 AWS 密钥即可。

[English](README.md)

## 使用方法

打开「终端」（Terminal），粘贴运行：

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/cncoder/oneclaw/main/setup.sh)"
```

或者先下载再运行：

```bash
curl -O https://raw.githubusercontent.com/cncoder/oneclaw/main/setup.sh
bash setup.sh
```

## 你需要准备什么

| 项目 | 必须？ | 说明 |
|------|--------|------|
| AWS Access Key + Secret Key | ✅ 必须 | 用于访问 Bedrock Claude 模型 |
| Discord Bot Token | ❌ 可选 | 让 OpenClaw 连接 Discord 聊天 |
| Discord Webhook URL | ❌ 可选 | 系统异常时发通知 |

### IAM 权限要求

AWS IAM 用户需要以下权限才能正常使用：

**最简方式**：附加 AWS 托管策略 `AmazonBedrockFullAccess`

**最小权限策略**（推荐生产环境使用）：

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

> **还需要在 Bedrock 控制台开启模型访问**：AWS Console → Bedrock → Model access → 勾选 Anthropic Claude 全系列 → Save changes

## 自动安装的组件

- **Homebrew** — macOS 包管理器
- **Node.js** — JavaScript 运行时
- **pnpm** — 快速包管理器
- **uv / uvx** — Python 包管理（MCP 服务器需要）
- **AWS CLI** — AWS 命令行工具
- **Claude Code** — AI 编程助手（通过 Bedrock）
- **OpenClaw** — AI Agent 框架（Gateway + Node）
- **MCP 服务器** — Chrome DevTools、AWS 文档
- **Guardian 守护进程** — 每 60 秒健康检查 + 自动修复
- **LaunchAgent** — 开机自启动

## 安装后可用命令

```bash
claude                              # 启动 Claude Code
openclaw chat                       # 和 OpenClaw 对话
openclaw status                     # 查看 OpenClaw 状态
openclaw doctor                     # 诊断问题
```

## Web 控制台

安装完成后访问 http://127.0.0.1:18789 打开 OpenClaw 控制面板。

## 手动安装（一键脚本失败时）

如果脚本在某一步失败了，可以手动安装对应组件后重新运行脚本——已安装的会自动跳过。

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

# 4. uv（Python 包管理器）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 5. AWS CLI
brew install awscli

# 6. Claude Code
curl -fsSL https://claude.ai/install.sh | bash

# 7. OpenClaw
curl -fsSL https://openclaw.ai/install.sh | bash
```

手动装完后，重新运行脚本完成配置：

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/cncoder/oneclaw/main/setup.sh)"
```

## 出了问题怎么办

### 方案 1: 一键修复（桌面快捷方式）

安装后桌面会有两个修复脚本，双击终端图标运行即可：

```bash
bash ~/Desktop/repair-openclaw.sh       # 停止→清理→重启（解决 99% 的问题）
```

### 方案 2: AI 智能修复（推荐）

让 Claude Code 自动读日志、诊断问题、修复故障：

```bash
bash ~/Desktop/ai-repair-openclaw.sh    # Claude 自动排查+修复，约 1-3 分钟
```

这会启动 Claude Code，它会自动执行以下操作：
- 检查 `openclaw status` 和 `openclaw doctor`
- 读取 gateway/node/chrome 的错误日志
- 检查 LaunchAgent 和端口状态
- 验证 AWS 凭证
- **自动修复发现的问题**
- 重启所有服务并验证

### 方案 3: 查看日志

```bash
tail -50 ~/.openclaw/logs/gateway.log      # Gateway 日志
tail -50 ~/.openclaw/logs/gateway.err.log  # Gateway 错误日志
tail -50 ~/.openclaw/logs/guardian.log     # 守护进程日志
```

### 方案 4: 重新安装

再跑一次 setup.sh 即可，已安装的组件会自动跳过。

## 安全说明

- AWS 密钥只存在本地 `~/.aws/credentials`，不会上传
- Gateway Token 自动生成，绑定 loopback（只能本机访问）
- 不包含任何硬编码密钥
- 所有服务只监听 127.0.0.1

## 文件结构

```
~/Desktop/
├── repair-openclaw.sh          一键修复脚本（桌面快捷方式）
└── ai-repair-openclaw.sh       AI 智能修复脚本（桌面快捷方式）
~/.aws/                         AWS 凭证
~/.claude/settings.json         Claude Code 配置
~/.mcp.json                     MCP 服务器配置
~/.openclaw/
├── openclaw.json               OpenClaw 主配置
├── chrome-profile/             Chrome CDP 专用数据目录
├── logs/                       所有日志
├── scripts/
│   ├── guardian-check.sh       守护进程脚本
│   ├── repair.sh              紧急修复脚本
│   └── ai-repair.sh           AI 智能修复脚本
└── workspace/                  OpenClaw 工作区
    └── CLAUDE.md              工作区说明
~/Library/LaunchAgents/
├── ai.openclaw.chrome.plist    Chrome CDP 自启动（端口 9222）
├── ai.openclaw.gateway.plist   Gateway 自启动
├── ai.openclaw.node.plist      Node 自启动
└── ai.openclaw.guardian.plist  守护进程自启动
```

## 许可证

MIT
