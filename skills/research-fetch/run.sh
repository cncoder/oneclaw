#!/usr/bin/env bash
# run.sh — research-fetch entrypoint
#
# Usage:
#   bash run.sh <url> [--no-vlm] [--no-cdp] [--viewport-only] [--md-only]
#
# Flags:
#   --no-vlm          Skip LLM reconciliation (Trafilatura only, ~3s, 85-90% accuracy)
#   --no-cdp          Launch headless Chromium instead of attaching to your Chrome
#   --viewport-only   Screenshot only the first viewport (faster but may miss tail)
#   --md-only         Print markdown only, no JSON wrapper
#
# First-time setup: bash setup.sh

set -euo pipefail

URL="${1:-}"
if [ -z "$URL" ] || [[ "$URL" == -* ]]; then
  echo "Usage: $0 <url> [--no-vlm] [--no-cdp] [--viewport-only] [--md-only]" >&2
  exit 1
fi
shift

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$SKILL_DIR/.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
  echo "❌ venv not found at $VENV_PY" >&2
  echo "   Run: bash $SKILL_DIR/setup.sh" >&2
  exit 2
fi

# Local CDP connections don't go through a proxy; strip proxy env by default.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY NO_PROXY no_proxy

# If --no-cdp is passed we may need the proxy again to download Chromium assets.
for a in "$@"; do
  if [ "$a" = "--no-cdp" ] && [ -n "${FORCE_PROXY:-}" ]; then
    export https_proxy="$FORCE_PROXY" http_proxy="$FORCE_PROXY"
    break
  fi
done

exec "$VENV_PY" "$SKILL_DIR/fetch.py" "$URL" "$@"
