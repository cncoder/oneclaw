#!/usr/bin/env bash
# 在新 Mac 上一键安装 agentcore-deepsearch MCP server。
#
# 背景：brain 同步系统只搬 ~/.claude 下的 skill/agent/command（含本 server 的 SKILL.md），
# 但不搬 MCP server 源码、也不搬 ~/.claude.json 的 MCP 注册（brain 硬排除）。
# 这个脚本补齐 brain 管不到的三件事：装依赖(venv)、注册 MCP、冒烟验证。
#
# 前置：
#   1. 已在新机跑过 brain 接入（skill 已到位），或不关心 skill 只要工具能用。
#   2. 本 server 目录已随源码搬到新机（连同这个脚本）。
#   3. AWS 凭证可用（~/.aws/credentials 的 default），且已在自己账号建好 us-east-1 的
#      websearch Gateway（见 ../SETUP-AGENTCORE.md 第 1 步；未建则自动回退 DuckDuckGo）。
#   4. 已装 python3、uv 或 pip。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[setup] server 目录: $HERE"

# --- 1. 建 venv 并装依赖 ---
if [ ! -d "$HERE/.venv" ]; then
  echo "[setup] 创建 venv ..."
  python3 -m venv "$HERE/.venv"
fi
PY="$HERE/.venv/bin/python"
echo "[setup] 安装依赖 ..."
"$PY" -m pip install --quiet --upgrade pip
if [ -f "$HERE/pyproject.toml" ]; then
  "$PY" -m pip install --quiet -e "$HERE"
else
  # 兜底：最小依赖集（与 server 实际 import 对齐）
  "$PY" -m pip install --quiet "mcp[cli]" boto3 botocore ddgs playwright bedrock-agentcore
fi

# --- 2. 注册到 Claude Code 的 ~/.claude.json ---
# 用 claude CLI 注册最稳（避免手改 JSON）。command 用当前机器的绝对路径。
CLAUDE_JSON="$HOME/.claude.json"
CMD="$PY"
echo "[setup] 注册 MCP server 到 $CLAUDE_JSON ..."
if command -v claude >/dev/null 2>&1; then
  claude mcp remove agentcore-deepsearch 2>/dev/null || true
  claude mcp add agentcore-deepsearch \
    --scope user \
    --env AGENTCORE_REGION=us-west-2 \
    --env AGENTCORE_BROWSER_ID=aws.browser.v1 \
    --env AGENTCORE_SESSION_TIMEOUT=600 \
    --env DEEPSEARCH_MAX_CHARS=50000 \
    --env DEEPSEARCH_FETCH_CONCURRENCY=4 \
    -- "$CMD" -m agentcore_deepsearch.server
  echo "[setup] 已用 claude CLI 注册。"
else
  echo "[setup] 未找到 claude CLI。请手动把下面这段加到 $CLAUDE_JSON 的 mcpServers："
  cat <<EOF
  "agentcore-deepsearch": {
    "type": "stdio",
    "command": "$CMD",
    "args": ["-m", "agentcore_deepsearch.server"],
    "env": {
      "AGENTCORE_REGION": "us-west-2",
      "AGENTCORE_BROWSER_ID": "aws.browser.v1",
      "AGENTCORE_SESSION_TIMEOUT": "600",
      "DEEPSEARCH_MAX_CHARS": "50000",
      "DEEPSEARCH_FETCH_CONCURRENCY": "4"
    }
  }
EOF
fi

# --- 3. 冒烟验证：真跑一次 agentcore 搜索 ---
echo "[setup] 冒烟验证（真调 AgentCore Web Search）..."
cd "$HERE"
"$PY" - <<'PYEOF'
import asyncio
from agentcore_deepsearch import search
async def main():
    r = await search.web_search("Amazon Bedrock AgentCore", num_results=3, engine="agentcore")
    src = r[0].source if r else "EMPTY"
    print(f"  结果数={len(r)} 实际引擎={src}")
    if src == "agentcore":
        print("  OK: 真 AgentCore Web Search 已生效。")
    elif src == "duckduckgo":
        print("  注意: 回退到了 DuckDuckGo —— 检查 AWS 凭证/Gateway 权限（us-east-1 websearch-gw）。")
    else:
        print("  警告: 无结果，检查网络与凭证。")
asyncio.run(main())
PYEOF

echo "[setup] 完成。重启 Claude Code 让 MCP 生效。"
