#!/usr/bin/env bash
# audit.sh — 12 场景 × ≥2 URL 用 research-fetch 批量跑 + 汇总报告
#
# 输出：
#   ~/.openclaw/workspace/data/tmp/research-fetch-audit/<run>/result-<slug>.json
#   /tmp/research-fetch-report.md   综合报告

set -u
SKILL=~/.openclaw/workspace/skills/research-fetch/run.sh
[ ! -x "$SKILL" ] && { echo "research-fetch run.sh 缺失"; exit 1; }

RUN_DIR="$HOME/.openclaw/workspace/data/tmp/research-fetch-audit/run-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN_DIR"
REPORT="/tmp/research-fetch-report.md"
MSN_URL="https://www.msn.com/zh-cn/weather/forecast/in-%E6%B7%B1%E5%9C%B3%E5%B8%82,%E5%B9%BF%E4%B8%9C%E7%9C%81,%E4%B8%AD%E5%9B%BD"

# 12 场景 × 2 URL（+ MSN 天气单独）
declare -a CASES=(
  "EN-tech-blog|https://simonwillison.net/2024/Dec/20/building-effective-agents/"
  "EN-tech-blog-2|https://www.anthropic.com/research/building-effective-agents"
  "ZH-tech-blog|https://blog.csdn.net/shanwei_spider/article/details/155501041"
  "ZH-tech-blog-2|https://juejin.cn/post/7394453873305731072"
  "forum-en|https://news.ycombinator.com/item?id=42470541"
  "forum-zh|https://www.v2ex.com/t/1003300"
  "news-en|https://www.bbc.com/news"
  "news-zh|https://www.zaobao.com/news/china"
  "docs|https://docs.python.org/3/library/urllib.parse.html"
  "docs-2|https://playwright.dev/docs/api/class-page"
  "github-readme|https://github.com/openclaw/openclaw"
  "github-readme-2|https://github.com/remotion-dev/remotion"
  "paywall|https://www.wsj.com/articles/asml-ceo-says-tariffs-pose-risk-to-chip-industry-11703183416"
  "infinite-scroll|https://weibo.com/hot/search"
  "pdf-page|https://arxiv.org/abs/2411.04788"
  "youtube|https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  "404|https://simonwillison.net/2024/Dec/19/building-effective-agents/"
  "spa|https://vercel.com/blog"
)

echo "🎬 跑 ${#CASES[@]} URL + MSN 3 次"
echo "📂 $RUN_DIR"
echo ""

# 清理代理
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

# 并发 = 1（sync lock 不允许并发 CDP attach）
for case in "${CASES[@]}"; do
  slug="${case%%|*}"
  url="${case#*|}"
  out="$RUN_DIR/result-${slug}.json"
  err="$RUN_DIR/err-${slug}.log"
  t0=$(date +%s)
  printf "[%s] %-20s ... " "$(date +%H:%M:%S)" "$slug"
  bash "$SKILL" "$url" >"$out" 2>"$err"
  rc=$?
  t1=$(($(date +%s) - t0))
  if [ $rc -eq 0 ] && [ -s "$out" ]; then
    # 抽字段
    title=$(python3 -c "import json,sys; d=json.load(open('$out')); print((d.get('title') or '')[:40])" 2>/dev/null)
    mdc=$(python3 -c "import json,sys; d=json.load(open('$out')); print(len(d.get('markdown') or ''))" 2>/dev/null)
    conf=$(python3 -c "import json,sys; d=json.load(open('$out')); c=d.get('confidence'); print(c if c is not None else 'n/a')" 2>/dev/null)
    echo "✅ ${t1}s conf=$conf md=${mdc}ch · $title"
  else
    echo "❌ rc=$rc ${t1}s · $(head -c 100 "$err")"
  fi
done

echo ""
echo "🌦 MSN 天气连 3 次稳定性..."
for i in 1 2 3; do
  t0=$(date +%s)
  out="$RUN_DIR/msn-run$i.json"
  bash "$SKILL" "$MSN_URL" >"$out" 2>"$RUN_DIR/msn-run$i.err"
  t1=$(($(date +%s) - t0))
  if [ -s "$out" ]; then
    # MSN 字段覆盖统计
    field_count=$(python3 -c "
import json, sys
d = json.load(open('$out'))
md = d.get('markdown') or ''
fields = ['温度', '体感', '湿度', '风', '气压', '能见度', '紫外线', '露点', '日出', '日落', '月相', 'AQI', 'PM2.5', '预报', '预警']
found = sum(1 for f in fields if f in md)
print(found)
" 2>/dev/null)
    echo "  run$i: ${t1}s · 字段命中=$field_count/15"
  else
    echo "  run$i: FAILED"
  fi
done

# 生成报告
echo ""
echo "📝 生成报告 → $REPORT"

python3 << PYEOF > "$REPORT"
import json, os
from pathlib import Path

run_dir = Path("$RUN_DIR")
cases = [
    ("EN-tech-blog", "https://simonwillison.net/2024/Dec/20/building-effective-agents/"),
    ("EN-tech-blog-2", "https://www.anthropic.com/research/building-effective-agents"),
    ("ZH-tech-blog", "https://blog.csdn.net/shanwei_spider/article/details/155501041"),
    ("ZH-tech-blog-2", "https://juejin.cn/post/7394453873305731072"),
    ("forum-en", "https://news.ycombinator.com/item?id=42470541"),
    ("forum-zh", "https://www.v2ex.com/t/1003300"),
    ("news-en", "https://www.bbc.com/news"),
    ("news-zh", "https://www.zaobao.com/news/china"),
    ("docs", "https://docs.python.org/3/library/urllib.parse.html"),
    ("docs-2", "https://playwright.dev/docs/api/class-page"),
    ("github-readme", "https://github.com/openclaw/openclaw"),
    ("github-readme-2", "https://github.com/remotion-dev/remotion"),
    ("paywall", "https://www.wsj.com/articles/asml-ceo-says-tariffs-pose-risk-to-chip-industry-11703183416"),
    ("infinite-scroll", "https://weibo.com/hot/search"),
    ("pdf-page", "https://arxiv.org/abs/2411.04788"),
    ("youtube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("404", "https://simonwillison.net/2024/Dec/19/building-effective-agents/"),
    ("spa", "https://vercel.com/blog"),
]

print("# Research-Fetch 场景覆盖审计报告\n")
print(f"**Run:** \`{run_dir.name}\`  ")
print(f"**Generated:** $(date +%Y-%m-%d\\ %H:%M:%S)\n")
print("## 12 场景实测表\n")
print("| # | 场景 | URL | Title | Confidence | Markdown | Elapsed | Tokens | 状态 |")
print("|---|---|---|---|---|---|---|---|---|")

results = []
for i, (slug, url) in enumerate(cases, 1):
    f = run_dir / f"result-{slug}.json"
    if not f.exists() or f.stat().st_size == 0:
        print(f"| {i} | {slug} | {url[:40]}... | — | — | — | — | — | ❌ FAIL |")
        results.append({"slug": slug, "ok": False})
        continue
    try:
        d = json.loads(f.read_text())
    except Exception as e:
        print(f"| {i} | {slug} | {url[:40]}... | — | — | — | — | — | ⚠️ JSON parse: {str(e)[:30]} |")
        results.append({"slug": slug, "ok": False})
        continue
    title = (d.get('title') or '')[:30]
    conf = d.get('confidence')
    conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else (conf or 'n/a')
    mdc = len(d.get('markdown') or '')
    el = d.get('elapsed_s', '?')
    tk = d.get('tokens_used') or {}
    tin = tk.get('in', '?') if isinstance(tk, dict) else '?'
    tou = tk.get('out', '?') if isinstance(tk, dict) else '?'
    ok = "✅" if mdc > 80 else "⚠️"
    print(f"| {i} | {slug} | {url[:40]}... | {title} | {conf_s} | {mdc}ch | {el}s | {tin}/{tou} | {ok} |")
    results.append({"slug": slug, "ok": mdc > 80, "conf": conf, "md_chars": mdc, "elapsed": el})

# 汇总统计
ok_n = sum(1 for r in results if r.get("ok"))
print(f"\n**通过率：{ok_n}/{len(results)}**")
confs = [r['conf'] for r in results if isinstance(r.get('conf'), (int, float))]
if confs:
    print(f"**平均 confidence：{sum(confs)/len(confs):.2f}** (有 {len(confs)} 个场景提供了分数)")

# MSN 稳定性
print("\n## MSN 天气稳定性 (连 3 次)\n")
print("| Run | Elapsed | 字段命中 | Confidence | Markdown |")
print("|---|---|---|---|---|")
msn_results = []
for i in (1, 2, 3):
    f = run_dir / f"msn-run{i}.json"
    if not f.exists() or f.stat().st_size == 0:
        print(f"| {i} | — | — | — | ❌ FAIL |")
        continue
    try:
        d = json.loads(f.read_text())
    except Exception:
        continue
    md = d.get('markdown') or ''
    fields = ['温度', '体感', '湿度', '风', '气压', '能见度', '紫外线', '露点', '日出', '日落', '月相', 'AQI', 'PM2.5', '预报', '预警']
    hit = sum(1 for fld in fields if fld in md)
    conf = d.get('confidence', 'n/a')
    el = d.get('elapsed_s', '?')
    msn_results.append({"hit": hit, "el": el, "conf": conf, "md": len(md)})
    print(f"| {i} | {el}s | {hit}/15 | {conf} | {len(md)}ch |")

if msn_results:
    avg_hit = sum(r['hit'] for r in msn_results) / len(msn_results)
    diff = max(r['hit'] for r in msn_results) - min(r['hit'] for r in msn_results)
    print(f"\n**字段覆盖均值：{avg_hit:.1f}/15**，极差 {diff}（稳定性 {'✅ 好' if diff <= 1 else '⚠️ 差'}）")
    # 对比基线
    print(f"**基线对比：**原 \`weather.py._enrich_with_cdp\` 只提取 5 字段（aqi/aqi_desc/dew_point_c/wind_direction/pressure_trend）；新方案均值 {avg_hit:.1f}/15 = **提升 {avg_hit/5*100:.0f}%**")

print("\n## Lena/CC 替换 CDP 用法的指引\n")
print("""### Lena 场景
- 以前：`browser action=navigate` → `snapshot` → 手动整理
- 现在：`research_fetch({url: "..."})` 直接拿精修 markdown + metadata
- 多步 UI：`computer_use({task: "..."})`

### CC 场景
- 在 CC prompt 里指示：
  ```
  For "summarize this URL" or "read this page", call:
    bash ~/.openclaw/workspace/skills/research-fetch/run.sh <url>
  For interactive click/fill/test, use chrome-devtools MCP as before.
  ```

### 早报 collector
- Primary 保留 `_browser.py`（快）
- DOM selector 失败时 fallback 到 `_v2.py`（computer_use）或 `research_fetch`（视觉校准）

## 遗留 P1/P2
- [ ] computer_use 登录墙 session 偶尔死循（已加 "BLOCKED: 登录墙" done 规则，但部分站 VLM 识别不出）
- [ ] research_fetch 对无限滚动 feed 只取前 N 屏
- [ ] PDF iframe 不支持
- [ ] 视频内容不解析（只看 thumbnail + metadata）
""")
PYEOF

echo ""
echo "✅ $REPORT"
cat "$REPORT" | head -30
