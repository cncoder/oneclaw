#!/usr/bin/env bash
# setup.sh — one-time install for research-fetch
#
# Creates .venv/ next to this script and installs all Python deps,
# including the Playwright Chromium runtime.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SKILL_DIR"

if [ ! -d .venv ]; then
  echo "📦 Creating .venv/ (Python 3)"
  python3 -m venv .venv
fi

echo "📥 Installing Python dependencies"
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "🌐 Installing Playwright Chromium"
.venv/bin/python -m playwright install chromium

echo ""
echo "✅ research-fetch ready"
echo ""
echo "   Test it:"
echo "     bash $SKILL_DIR/run.sh https://example.com"
echo ""
echo "   Configure (optional):"
echo "     export LITELLM_BASE_URL=http://localhost:4000/v1"
echo "     export LITELLM_KEY=sk-..."
echo "     export RF_VLM_MODEL=claude-sonnet-4-6"
