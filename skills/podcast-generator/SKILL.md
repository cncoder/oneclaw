---
name: podcast-generator
description: "本地 AI 中文双人播客生成系统（Apple Silicon only）。主题一句话 → 自动调研 → 脚本 → TTS 合成 → 液体玻璃播放器 HTML。自带一男一女两位预制主持人声音，开箱即用。当用户提到播客、podcast、圆桌派、roundtable、做一期节目、生成音频、把文章变成语音、读一下这段话、有声书、做个音频节目时触发。"
metadata:
  openclaw:
    emoji: "🎙️"
    requires:
      bins: ["python3.12", "ffprobe", "ffmpeg"]
---

# Skill: podcast-generator

> Apple Silicon only (M1/M2/M3/M4)。mlx 不支持 Intel Mac / Linux / Windows。

中文双人对话式播客生成系统（圆桌派风格）。两位预制主持人交替发言，自动左右声道分离，一条命令出完整播客。

**能做什么：**
- 给一个主题，自动调研 → 写稿 → 合成 MP3 → 生成单文件 HTML 播放器
- 立体声双人对话，MP3 192kbps
- 断点续传（长播客不怕中断）
- 可选一键发布到你自己的私有 CloudFront

**性能参考（M4 芯片实测）：**
- 首次下载 Qwen3-TTS MLX 8bit 量化模型 ~800MB（约 2-5 分钟），之后离线可用
- 合成速率约 1:1（30 分钟音频 ≈ 30 分钟生成）
- 中文语速约 387 字/分钟（5,800 字 ≈ 15 分钟）

## 前置安装（只做一次）

```bash
pip3.12 install mlx mlx-audio numpy soundfile pydub pyloudnorm pyyaml boto3
brew install ffmpeg python@3.12   # 已有可跳过

# 定位 scripts 目录，选一条合适的导出
export SKILL="<path-to>/podcast-generator/scripts"
```

后续命令都用 `$SKILL/xxx.py` 引用。

## 一键生成（推荐）

```bash
# 0. 环境自检（1 秒）
python3.12 $SKILL/doctor.py

# 1. 一键生成
python3.12 $SKILL/one_shot.py "AI 能否取代程序员" --duration 5min --style debate

# 2. 打开 HTML 播放
open output/*/*/index.html
```

输出：`output/YYYY-MM-DD/{slug}/{script.txt, podcast.mp3, index.html, metadata.json}`

**LLM 后端**：本机装了 `claude` CLI（Claude Code）或设了 `ANTHROPIC_API_KEY` 即自动使用。都没有？脚本会打印 prompt 让你手动贴给任意 LLM（ChatGPT / Gemini / 通义），再贴回回答文件路径继续——不卡死。

### 参数

| 参数 | 选项 | 默认 |
|------|------|------|
| `--duration` | `5min / 10min / 15min / 30min / 45min / 60min` | `15min` |
| `--style` | `debate / deep_dive / casual / interview / tutorial` | `deep_dive` |
| `--rebuild` | 复用已有 `script.txt`，只重跑 TTS/HTML | — |
| `--skip-research` | 跳过调研，LLM 凭自身知识写 | — |
| `--skip-tts` / `--skip-html` | 只出脚本 / 不做网页 | — |
| `--publish` | 直接上传到你的 CloudFront（需先 `provision`，见下） | — |

## 声音

skill 自带一男一女两位中文主持人（`assets/voices/host_female_10s.wav`、`host_male_12s.wav`）。脚本里用`【Host_A】`（女声，偏左耳）和`【Host_B】`（男声，偏右耳）交替发言即可，无需任何配置。

## 双人对话音质优化（写稿前必读）

> 音质 80% 取决于脚本怎么写，20% 才是 TTS 参数。以下是累计跑过几百期 30 分钟双人播客的生产实测值。

### 段落长度

引擎 `chunk_hard_limit = 290` 字。超过会在非句末断开产生合并痕迹。

| 段落长度 | 效果 | 建议占比 |
|---|---|---|
| **30-80 字** | 最自然，整句一 chunk | 70% |
| 80-150 字 | 完整，句末断开 | 20% |
| 150-290 字 | 边界在句号，尚可 | 10% |
| >290 字 | ⚠ 被切 + crossfade 拼接，可听出痕迹 | 避免 |

### 脚本写法

| 做法 | 效果 |
|------|------|
| 穿插语气词：嗯、对、哈哈、其实、你看、我觉得 | TTS 带停顿韵律，像真人 |
| 打断/接话："你这么一说我想起来…" / "等等，那个…" | 自带过渡感 |
| 口语化："然而"→"不过"、"此外"→"还有" | 别用书面语 |
| **提问—回答—追问—展开** 四拍循环 | 制造张力 |
| 一人主讲 + 另一人抛梗/质疑 | 分工明确 = 信息密度 |

**推荐段落结构**：

```
【Host_A】开场钩子（30字，抛反直觉结论）
【Host_B】追问 / 质疑（30字）
【Host_A】展开 1（80-120字，事实或案例）
【Host_B】接话 + 补充 / 对比（60-100字）
【Host_A】转折或延伸（60-100字）
【Host_B】收束 / 下一话题引出（30-60字）
```

### TTS 参数（生产实测默认值，不建议改）

| 参数 | 生产值 | 为什么 |
|---|---|---|
| `chunk_hard_limit` | 290 | 超过会二次拆分，产生合并痕迹 |
| `min_rms` (女声) | 0.07 | 过高误判静音、过低放过吞字 |
| `min_rms` (男声) | 0.03 | 男声 RMS 本身低，阈值同女声会误重试 |
| `max_retries` | 2 | 5 次重试会放大音色偏差 |
| `crossfade_ms` | 200 | chunk 间淡入淡出，消除硬拼接痕迹 |
| `max_audio_sec_per_char` | 0.25 | 超过判定拖长/胡言重试 |
| `mp3_bitrate` | 192k | 双人立体声最佳点 |

**立体声声道分离**（增益格式 `(left, right)`）：

```python
VOICE_PAN = {
    "Host_A": (1.0, 0.7),   # 左耳足量，右耳衰减 30%
    "Host_B": (0.7, 1.0),   # 右耳足量，左耳衰减 30%
}
```

1.0 = 100% 原声，0.7 = 70%。**别用 `(1.0, 0.0)`**（彻底左/右）会像单声道电话。

**让 LLM 帮你写稿**：见 `references/script-prompt.md` 的 prompt 模板。

## 数据源与调研方法

脚本质量 = 信息密度。**写稿前先调研**，不要让 LLM 凭空编。

### 调研五步（压缩版）

1. **Scope** — 一句话写清这期回答什么问题
2. **Multi-source** — 至少 3 个独立来源，不信单一信源
3. **Freshness** — AI/科技优先近 3 个月；金融看当周
4. **Cross-Validation** — 关键数字两处对得上，对不上标"有争议"讲出来
5. **Synthesis** — 提炼 3-5 条洞察，细节挂上去

更完整方法论见 [deep-research skill](https://github.com/cncoder/oneclaw/tree/main/skills/deep-research)。`one_shot.py` 已内置简化版（LLM 分解话题 → 输出结构化 JSON → 喂给脚本生成）。

### 常用数据源（按题材）

| 题材 | 推荐源 |
|---|---|
| AI / 科技 | Hacker News、GitHub Trending、Product Hunt、arXiv、Reddit r/LocalLLaMA |
| 财经 / 市场 | Yahoo Finance、Bloomberg、WSJ、Perplexity Finance |
| 国际时事 | world_news API、Reuters、BBC RSSHub |
| 网络安全 | CVE、krebsonsecurity RSS、HN security |
| 社交热点 | X/Twitter RSSHub、Reddit 热榜、Threads |
| 深度技术 | GitHub 源码（本地 clone + Grep）、官方 docs、Context7 MCP |

## 生成网页播放器

如果你不走 `one_shot.py`，想单独把 MP3 + 脚本拼成播放器：

```bash
python3.12 $SKILL/generate_player_html.py /tmp/demo.mp3 /tmp/demo.txt /tmp/demo.html \
  --title "AI 能不能取代程序员"
```

**特性**：液体玻璃暗/亮主题；对话气泡点击跳转音频位置；底部播放器含 ±15/30s / 倍速（0.75-2x）；LocalStorage 缓存播放进度 + 主题偏好；`--embed` 可把 MP3 base64 内联成真·单文件 HTML。

## 发布到自己的 CloudFront（可选）

把 MP3 + 网页发布到**你自己的 AWS 账号**，得到可分享的链接。

**安全铁律**（脚本内置强制检查）：
- S3 bucket Public Access Block **四项必须全部 True**
- BucketOwnerEnforced（不允许 ACL）
- Bucket policy 只允许指定 CloudFront distribution 访问（`AWS:SourceArn` 条件）
- 本 skill 绝不把任何 object 或 bucket 设为 public

### 首次发布（约 15 分钟，主要等 CloudFront 部署）

```bash
# 1. 检查 AWS 凭证
python3.12 $SKILL/publish_to_cdn.py check

# 2. 起全球唯一 bucket 名
BUCKET="my-podcast-cdn-$(whoami)-$(date +%s)"
python3.12 $SKILL/publish_to_cdn.py provision --bucket "$BUCKET" --region us-east-1
# 配置自动缓存到 ~/.podcast-generator/publish.json

# 3. 等 CloudFront Deployed 后发布
python3.12 $SKILL/publish_to_cdn.py publish \
  --mp3 podcast.mp3 --html index.html --slug ai-vs-programmers
```

或直接 `one_shot.py --publish` 一条命令搞定。

以后每次发布只需 `publish` 子命令，bucket 信息从 `~/.podcast-generator/publish.json` 读取。

**IAM 权限**：首次 `provision` 需要 `s3:CreateBucket / PutBucketPolicy / PutBucketOwnershipControls / PutPublicAccessBlock`、`cloudfront:CreateDistribution / CreateOriginAccessControl / ListOriginAccessControls`。

## 技术栈

| 组件 | 技术 |
|------|------|
| TTS 模型 | [`mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit`](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit) ~800MB |
| ASR（可选） | [`mlx-community/Qwen3-ASR-0.6B-8bit`](https://huggingface.co/mlx-community/Qwen3-ASR-0.6B-8bit)，`--enable-asr` 开启 |
| 推理框架 | [mlx-audio](https://github.com/ml-explore/mlx-audio)（Apple MLX，仅 Apple Silicon） |
| 音频处理 | numpy + soundfile + pyloudnorm + ffmpeg |
| Python | 3.12（mlx 依赖 3.12 C API，3.14 ABI 不兼容） |

## 重要约束

- **TTS 必须串行**。并行会 GPU 争抢导致音频抖动。一期完成再做下一期。
- **python3.14 不兼容**。必须 `python3.12`。

## 故障排查

| 症状 | 修复 |
|------|------|
| TTS 超时 | 重新运行，断点续传自动恢复（复用 `_tts_chunks/`） |
| 音频质量差 | 确认无并行 TTS（`ps aux \| grep python3.12`） |
| python3.12 找不到 | `brew install python@3.12` |
| ffmpeg 找不到 | `brew install ffmpeg` |
| MP3 太大发不出去 | `ffmpeg -i podcast.mp3 -b:a 64k compressed.mp3` |

更多见 `references/troubleshooting.md`。

## References

| 文件 | 何时读取 |
|------|---------|
| `references/script-prompt.md` | 自己用 LLM 写稿时的 prompt 模板 |
| `references/data-sources.md` | 调研数据源方法论 |
| `references/tts-module.md` | TTS 引擎细节、单独调用、ASR 回检 |
| `references/troubleshooting.md` | 遇到故障时 |
