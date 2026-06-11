---
name: ai-search
description: 用本机已登录的 Perplexity / Gemini 做 AI 深度搜索,直接拿带引用的综合报告。当需要快速拿一个话题的多源综述、对比、"现在最好的 X 是什么"、带引用的事实核查,且想省去自己拼 web_search+抓取时使用。走 CDP 驱动本机 Chrome(9222,已登录 Pro)。NOT for 抓指定单个 URL 的正文(用 fetch_page),NOT for 需要自己控制每个来源的严谨调研(用 deep-search-protocol + agentcore-deepsearch)。
---

# AI Search — Perplexity / Gemini 拿报告

本机 Chrome（9222,`your-chrome-profile` profile)已登录 Perplexity 和 Gemini(含 Pro)。
用 CDP 驱动它们提问,直接拿**它们自己做完"先广后深 + 多源综合 + 带引用"的成品报告**,比自己拼搜索省事。

这是 `deep-search-protocol` 搜索体系的一档:**要快速综述/对比时优先用它拿初稿,再按需用 `agentcore-deepsearch` 对关键结论纵深核验。**

## 用法

```bash
PY=~/.claude/skills/agentcore-deepsearch/.venv/bin/python   # 任何带 websocket-client 的 python 都行
$PY ~/.claude/skills/ai-search/ask.py perplexity "你的问题"
$PY ~/.claude/skills/ai-search/ask.py gemini     "你的问题"
$PY ~/.claude/skills/ai-search/ask.py perplexity "复杂问题" --wait 35   # 给更久生成时间
$PY ~/.claude/skills/ai-search/ask.py gemini "重大调研" --deep          # Gemini Deep Research 深度报告模式(跑几分钟,默认 wait 120s)
```

**`--deep`（Gemini Deep Research，⚠️ 实验性）**：脚本能自动开 Deep Research、提交、点"Start research"确认（实测 `start=STARTED` 成功）。**但拿不到程序化报告**——实测确认:Gemini 点完开始研究后,当前 tab 永远停在"Researching websites..."静止页,报告在后台异步生成、出现在独立视图,轮询当前 tab 抓不到。所以 `--deep` 会:启动研究 + 不关 tab + 返回"报告在 Chrome tab 里,几分钟后去看"。
- **要程序化深度报告,优先用普通 ai-search(Perplexity/Gemini 不带 --deep)或 `agentcore-deepsearch` 纵深抓**,别指望 `--deep` 自动取回正文。
- `--deep` 的价值:替你在本机 Chrome 里把 Deep Research 跑起来,你过几分钟自己去那个 tab 看成品报告。

输出:AI 生成的报告正文(含来源标注,如 `github +2` / `aws.amazon.com`)。

## 两个源怎么选

- **Perplexity**:默认首选。检索快、引用密、答案结构化,最适合"现在最好的 X""A vs B""某事实核查"。实测 25s 出带引用报告。
- **Gemini**:需要更长推理、Google 生态信息、或 Perplexity 答得不好时换它。生成稍慢(~30s)。

两个都拿一遍交叉对照,是最稳的——它们检索源不同,矛盾点恰恰是该深挖的地方。

## 与其他搜索工具的关系（搜索体系全景）

| 场景 | 用什么 |
|---|---|
| 快速拿一个话题的综述/对比报告 | **本 skill**(Perplexity/Gemini 成品报告) |
| 自己控制来源、要纵深抓多个原文交叉验证 | `agentcore-deepsearch` 的 `deep_search` |
| 抓指定单个 URL 正文 | `agentcore-deepsearch` 的 `fetch_page`(自动选 http/云端/CDP) |
| 封闭源(Reddit/X/知乎) | `fetch_page` 会自动走 CDP 本机登录态 |
| 方法论/执行顺序 | `deep-search-protocol` skill |

## 注意

- **依赖登录态**:本机 Chrome 必须已登录目标站。没登录会拿到空答案或登录页,脚本会报"没拿到答案"。
- **开新 tab、抓完自动关**,不动 Abel 当前 tab。
- 拿到的是 AI 二手综合,**重要结论仍要点开它引用的原始来源核对**(URL 只能用它实际给出的,别自己编)。
- 失败回退:某个源拿不到 → 换另一个源 → 还不行退回 `agentcore-deepsearch` 自己搜。
