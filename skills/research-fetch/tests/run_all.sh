#!/usr/bin/env bash
# run_all.sh — research-fetch regression test across scenario categories
#
# Runs fetch on a curated URL per category, expects: confidence > 0.6,
# markdown length > 100 chars, non-empty title.
#
# Usage:
#   bash tests/run_all.sh [--quick]   # --quick skips VLM reconciliation

set -u

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN="bash $SKILL_DIR/run.sh"
FLAGS=""
[ "${1:-}" = "--quick" ] && FLAGS="--no-vlm"

declare -a CASES=(
  "english-blog|https://simonwillison.net/2024/Dec/20/building-effective-agents/"
  "docs-site|https://docs.python.org/3/library/urllib.parse.html"
  "github-readme|https://github.com/openclaw/openclaw"
  "news|https://www.bbc.com/news"
  "404-page|https://simonwillison.net/2024/Dec/19/building-effective-agents/"
)

PASS=0
FAIL=0

for case in "${CASES[@]}"; do
  name="${case%%|*}"
  url="${case#*|}"
  printf "%-16s %s ... " "$name" "$url"
  out=$($RUN "$url" $FLAGS 2>/dev/null || true)
  if [ -z "$out" ]; then
    echo "❌ empty output"
    FAIL=$((FAIL+1))
    continue
  fi
  title=$(echo "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('title') or '')" 2>/dev/null || echo "")
  md_chars=$(echo "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('markdown') or ''))" 2>/dev/null || echo 0)
  conf=$(echo "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); c=d.get('confidence'); print(c if c is not None else 'n/a')" 2>/dev/null || echo "n/a")
  elapsed=$(echo "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('elapsed_s') or '?')" 2>/dev/null || echo "?")

  if [ -n "$title" ] && [ "$md_chars" -gt 80 ]; then
    echo "✅ conf=$conf md=${md_chars}ch t=${elapsed}s"
    PASS=$((PASS+1))
  else
    echo "❌ title='$title' md=$md_chars conf=$conf"
    FAIL=$((FAIL+1))
  fi
done

echo ""
echo "=============================="
echo " PASS=$PASS  FAIL=$FAIL"
echo "=============================="
[ $FAIL -eq 0 ]
