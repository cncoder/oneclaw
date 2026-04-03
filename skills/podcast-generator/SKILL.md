---
name: podcast-generator
description: "生成播客时必须使用此 skill。本地 AI 播客生成 + TTS 语音合成系统。支持圆桌派和每日日报。当用户提到播客、podcast、圆桌派、roundtable、TTS、语音合成、voice clone、生成音频时触发。基于 Qwen3-TTS mlx + Bedrock Opus，含 Iris QA 审计。"
metadata:
  openclaw:
    emoji: "🎙️"
    requires:
      bins: ["python3.12", "ffprobe", "ffmpeg", "aws"]
---

# Skill: podcast-generator

> 仅支持 Apple Silicon (M1/M2/M3/M4)。mlx 不支持 Intel Mac 或 Linux。

本地 AI 播客生成系统。两种模式：**圆桌派**（用户指定话题，深度聚焦）+ **每日日报**（全板块自动采集）。

TTS 模块作为独立可复用组件，也可供有声书、语音合成等其他项目调用。

**环境变量**（请根据实际安装路径设置）：

```bash
export PROJECT_DIR=~/Documents/ccdev/local-mactts   # 项目根目录
export OUTPUT_DIR=~/Documents/ccdev/podcasts          # 播客输出目录
export VOICES_DIR=~/.tts-voices                       # 参考音频目录
```

---

## Trigger（触发条件）

触发词：**圆桌派**、**roundtable**、**做一期播客**、**生成播客**、**podcast**、**TTS**、**语音合成**、**voice clone**、**生成音频**

自然语言示例：

```text
"帮我做一期关于AI安全的圆桌派"
→ topic="AI安全", duration=30min, style=deep_dive

"roundtable: 量子计算, 15分钟, casual"
→ topic="量子计算", duration=15min, style=casual

"深聊一下 Web3 的现状，辩论风格"
→ topic="Web3", duration=30min, style=debate

"用小周的声音读一段文字"
→ 直接调用 TTS 模块（不走播客 pipeline）
```

---

## 系统架构

```
用户指定话题
    │
    ▼
数据采集（Google CDP + 递归爬取 3 层 + digest 关键词匹配）
    │
    ▼
脚本生成（AWS Bedrock Opus 4.6，分批处理）
    │   ~10000 字 ≈ 27min 音频
    ▼
TTS 合成（Qwen3-TTS mlx，localhost:8880，断点续传）← 可独立调用
    │
    ▼
网站生成（暗色主题单页 HTML + 播放器）
    │
    ▼
QA 审计（Iris 6 维度评分，total ≥ 7.0 且真名安全性通过才 PASS）
    │
    ▼
上传（可选，S3 + CloudFront）
```

### 技术栈

| 组件 | 技术 |
|------|------|
| Python | python3.12（**不能用 3.14**，mlx 不兼容） |
| TTS 模型 | mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit |
| TTS Server | localhost:8880 (FastAPI + mlx_audio) |
| 脚本生成 | AWS Bedrock Opus 4.6 (us-west-2) |
| QA 评分 | AWS Bedrock Haiku 4.5 + Qwen3-ASR |
| 浏览器采集 | Chrome CDP 9222 |

### 模式决策

| | 圆桌派 | 每日日报 |
|---|---|---|
| 触发 | 用户按需 | 每天 07:00 cron |
| 话题 | 用户指定 | 全部板块 |
| 时长 | 15-120min | 45-50min |
| 风格 | 5 种可选 | 固定 |
| 数据 | Google 搜索 + digest 抽取 | 当天全采集 |

---

## TTS 独立模块（可复用）

> 此模块可独立于播客 pipeline 使用，适用于：有声书、通知语音、独立语音合成任务。

### 启动 TTS Server

**独立 TTS 调用（API/tts-clone.sh）需要先启动 TTS Server。播客 pipeline 不依赖 TTS Server，它使用进程隔离 worker 直接加载模型。**

```bash
# 在项目根目录启动
cd $PROJECT_DIR
python3.12 -m src.tts_server
# 首次加载模型约 30s，之后常驻内存
```

健康检查：

```bash
curl -s http://127.0.0.1:8880/health
# 返回: {"status": "ok", "model_loaded": true}
```

### 独立调用 TTS API

不依赖播客 pipeline，直接 POST 合成音频：

```bash
curl -s -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "input": "要合成的文字内容",
    "voice": "zhouxun",
    "response_format": "mp3",
    "speed": 1.0
  }' \
  -o output.mp3
```

**Payload 字段：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `input` | string | 必填 | 要合成的文本 |
| `voice` | string | `zhouxun` | 声音 ID（见下表） |
| `response_format` | string | `mp3` | 输出格式（mp3/wav） |
| `speed` | float | `1.0` | 语速（0.5-2.0） |

### 通过 tts-clone.sh 调用

适合 shell 脚本集成，内置 ASR 质量检查（相似度 < 50% 自动重试），输出 MP3 128k：

```bash
# tts-clone.sh 已包含在本 skill 的 scripts/ 目录
VOICES_DIR=$VOICES_DIR TTS_VOICE=zhouxun bash scripts/tts-clone.sh "文本内容" output.mp3
VOICES_DIR=$VOICES_DIR TTS_VOICE=douwendao bash scripts/tts-clone.sh "文本" output.mp3
```

特点：直接加载模型推理（不走 TTS Server），内置 ASR 质量回检（相似度 < 50% 自动重试），输出 MP3 128k。适合单次调用场景。

### 声音列表

| 声音 ID | 角色 | 参考音频文件 |
|---------|------|-------------|
| `zhouxun` | 小周（默认，女声） | `$VOICES_DIR/zhouxun_mandarin_10s.wav` |
| `douwendao` | 涛哥（男声） | `$VOICES_DIR/douwendao_mandarin_12s.wav` |
| `luyu` | 备选女声 | `$VOICES_DIR/luyu_mandarin_12s.wav` |

### 参考音频要求

参考音频需用户自备，**不随 repo 分发**（版权保护，仅供个人研究使用）。

格式要求：
- 格式：WAV，16kHz 单声道（或 24kHz）
- 时长：10-30s，效果最佳
- 内容：安静环境录制，无背景噪音
- 放置路径：`$VOICES_DIR/`

### ASR 质量回检

每个 TTS chunk 生成后，使用 Qwen3-ASR 模型将音频转录回文字，与原文对比相似度：

```
原文 → TTS 合成 → 音频 → ASR 转录 → 对比原文
                                      ↓
                              相似度 < 阈值 → 自动重试（最多 3 次）
```

| 参数 | 值 | 说明 |
|------|-----|------|
| ASR 模型 | mlx-community/Qwen3-ASR-0.6B-8bit | 本地推理，不消耗 API |
| 阈值（pipeline） | 55% | loqui.tts 引擎默认 |
| 阈值（tts-clone.sh） | 50% | 独立脚本默认 |
| 重试次数（pipeline） | 最多 2 次 | loqui.tts 引擎默认 max_retries=2 |
| 重试次数（tts-clone.sh） | 1 次 | 独立脚本简化版 |

ASR 回检可以捕获：
- 吞字/漏字（模型跳过了部分文字）
- 乱码音频（噪音、重复、静音段过长）
- 声音错配（用错了参考音频）

> pipeline 模式中 ASR 默认关闭（`enable_asr=False`），通过 `--enable-asr` 开启。tts-clone.sh 默认开启。

### 断点续传机制

播客 pipeline 中 TTS 中间结果保存到 `_tts_chunks/` 目录。中断后重新执行会自动跳过已完成片段。

查看进度：

```bash
ls $OUTPUT_DIR/roundtable/{date}/{slug}/_tts_chunks/*.wav 2>/dev/null | wc -l
```

### 跨日缓存

`$PROJECT_DIR/data/tts_cache/` 目录按 `sha256(voice_name + ":" + normalized_text).wav` 缓存已合成的 chunk。相同声音 + 相同文本的 chunk 会直接复用，不再调用 TTS 模型。

脚本中的固定句式（开场白、转场、收尾、语气词）会自动命中缓存，显著加速重复生成。

### 并发限制（严格串行，不可并行）

> **警告：TTS 生成必须严格串行，绝不能并行运行多个 TTS 任务。**

并行 TTS 会导致：
- **音频抖动**：GPU 资源争抢导致推理不稳定，生成的语音出现卡顿、断裂、节奏异常
- **质量严重下降**：ASR 回检相似度从 90%+ 骤降到 30-50%，大量 chunk 需要重试
- **OOM 崩溃**：多个模型实例同时占用统一内存，极易触发系统 OOM

正确做法：一期播客 TTS 完成后再启动下一期。批量生成多期时用串行队列。

---

## 快速开始

### Step 0：环境确认

```bash
# 播客 pipeline 不需要 TTS Server，直接运行即可
# 如果要用独立 TTS API，才需启动 Server：
curl -s http://127.0.0.1:8880/health  # 检查 Server 是否在跑
# 未运行则：cd $PROJECT_DIR && python3.12 -m src.tts_server
```

### 圆桌派

```bash
cd $PROJECT_DIR
python3.12 -m src.roundtable.generate \
  --topic "话题" \
  --duration 30min \
  --style deep_dive \
  --skip-upload
```

参数说明：

| 参数 | 可选值 | 说明 |
|------|--------|------|
| `--topic` | 任意字符串 | 播客话题（必填） |
| `--duration` | 15min / 30min / 45min / 60min / 90min / 120min | 目标时长 |
| `--style` | debate / deep_dive / casual / interview / tutorial | 对话风格 |
| `--skip-upload` | — | 跳过 S3 上传（本地调试用） |
| `--skip-tts` | — | 跳过 TTS，只生成脚本 |
| `--skip-research` | — | 跳过数据采集，用已有研究数据 |
| `--rebuild` | — | 跳过脚本生成，直接重跑 TTS |
| `--sources` | URL 列表 | 手动指定参考来源 |
| `--context` | 字符串 | 额外背景信息注入 |

### 每日日报

```bash
cd $PROJECT_DIR
python3.12 -u -m src.daily
```

无参数，全自动。

---

## Pipeline 6 步详解

### Step 1 数据采集

**输入**：topic 字符串 / 无（日报模式）
**输出**：`structured_research.json`

- Google CDP 搜索（Chrome 9222 port）
- 多层深度爬取：3 层递归，最多 24000+ 字素材
- 日报模式额外匹配近 7 天 `data/digests/{date}/digest.json`
- CDP 不可用时自动降级到 DuckDuckGo

### Step 2 脚本生成

**输入**：`structured_research.json`
**输出**：`script.txt`

- 模型：AWS Bedrock Opus 4.6 (us-west-2)
- ≤ 15000 字：单次生成
- > 15000 字：分批生成（12000 字/批），上下文衔接（传最后 6 行）
- 对话格式：涛哥 / 小周轮流发言

参考字数：~10000 字 ≈ 27min 音频

### Step 3 TTS 合成

**输入**：`script.txt`
**输出**：`_tts_chunks/*.wav` → `podcast.mp3`

播客 pipeline 使用**进程隔离 worker 模式**（不走 HTTP server），由 `loqui.tts` 库驱动：

1. **Worker 启动**：子进程加载 Qwen3-TTS 模型（一次加载，stdin/stdout JSON 循环通信）
2. **对话解析**：`script.txt` 按 `【涛哥】` `【小周】` 标记拆分，每段硬限 290 字（按 。！？；\n 断句后贪心合并）
3. **逐段合成**：每个 chunk 发给 worker，返回 WAV + 质量指标
4. **质量检查**：RMS 音量、重复检测、异常静音（>1.5s）、ASR 回检
5. **断点续传**：`_tts_chunks/_progress.json` 记录已完成 chunks，中断后自动跳过
6. **跨天缓存**：`data/tts_cache/` 按 sha256(voice+text) 缓存 WAV，相同文本复用
7. **高级合并**：
   - 短 chunk（<3s）轻微加速 1.05-1.10x + 与前段叠加模拟"抢话筒"
   - 尾部软压缩 + 200ms crossfade
   - stereo pan（小周偏左 L=1.0/R=0.7，涛哥偏右 L=0.7/R=1.0）
   - 说话人切换时插入合成呼吸声
   - pink noise -40dB 底噪增加质感
   - LUFS -16 响度标准化（pyloudnorm）
   - 合并超时 300s 自动 fallback 到 ffmpeg 简单拼接
8. **编码**：ffmpeg WAV → MP3 192k（日报）/ 128k（tts-clone.sh）

> **日报 vs 圆桌派差异**：日报通过 `_tts_runner.py` subprocess 隔离运行（便于超时控制 + 日志分离），`enable_asr=True`；圆桌派同步直调 `tts_engine.synthesize()`，`enable_asr=False`（更快）。

合成速率约 1:1（30min 音频需约 30min，M4 芯片）

> **注意**：TTS Server (8880) 是独立的轻量 HTTP 接口，供外部单次调用。播客 pipeline 不走 HTTP，直接进程内调用 loqui.tts。

### Step 4 网站生成

**输入**：`podcast.mp3` + `script.txt`
**输出**：`index.html`

- 暗色主题单页 HTML
- 内嵌音频播放器 + 对话文字稿
- 移动端适配

### Step 5 QA 质检（Iris 审计官）

**输入**：`podcast.mp3` + `script.txt` + `index.html`
**输出**：`iris_audit.json` + `qa_report.json`

PASS 条件：**total ≥ 7.0** 且 **真名安全性通过**（强制阻断 gate，不参与加权）

| 维度 | 权重 | 检测方法 | 阈值 |
|------|------|---------|------|
| 脚本质量 | 30% | Haiku LLM 评分 | ≥ 7 |
| TTS 完整度 | 30% | ffprobe 时长比 + ASR 相似度 | ≥ 0.85 |
| 工程完整度 | 25% | HTML/CDN/MP3 文件检查 | 100% |
| 逻辑一致性 | 15% | Haiku 抽样检查 | 无 critical |
| 真名安全性 | Gate | 正则扫描（0 leaks 才通过） | 强制阻断 |

### Step 6 上传（可选）

**输入**：`index.html` + `podcast.mp3`
**输出**：CloudFront URL

- S3 存储 + CloudFront 分发
- 加 `--skip-upload` 跳过

---

## 输出目录结构

```
$OUTPUT_DIR/roundtable/{date}/{slug}/
├── script.txt                # 对话脚本（涛哥/小周格式）
├── podcast.mp3               # 最终音频（~30MB/30min）
├── index.html                # 静态播客网站
├── metadata.json             # 元数据（话题、时长、声音等）
├── structured_research.json  # 研究数据
├── iris_audit.json           # Iris 审计详细结果
├── qa_report.json            # QA 报告
└── _tts_chunks/              # TTS 中间文件（断点续传，勿删！）
```

---

## 前置依赖

### 系统依赖

```bash
# Python 依赖（必须 python3.12）
cd $PROJECT_DIR
pip3.12 install -r requirements.txt

# 媒体工具
brew install ffmpeg  # 包含 ffprobe
```

### 服务依赖

| 服务 | 说明 |
|------|------|
| Chrome CDP 9222 | 需以 `--remote-debugging-port=9222` 启动 Chrome |
| AWS Bedrock | us-west-2，需 Opus 4.6 + Haiku 4.5 权限。验证：`aws bedrock list-foundation-models --region us-west-2 --query "modelSummaries[?contains(modelId,'claude')]" --output table` |
| TTS Server | 127.0.0.1:8880，需提前启动（见上方） |

---

## 费用估算

| 场景 | 模型 | 费用参考 |
|------|------|---------|
| 30min 圆桌派 | Opus 4.6 脚本生成 | ~$1.5-2.2 |
| 15min 短播客 | Sonnet 4.6 降级 | ~$0.3 |
| Haiku QA 审计 | Haiku 4.5 | ~$0.02/期（可忽略） |

**降本策略：**
- ≤ 15min 播客 → 改用 Sonnet 4.6（`--model sonnet`）
- 开启 prompt cache（重复 research 场景节省 50%+）
- 复用已有 research 数据（`--skip-research`）

---

## 故障排查

### TTS Server 未启动 / 8880 端口冲突

tts-proxy（Rust）可能占用 8880：

```bash
# 如果有其他进程占用 8880 端口，先停掉
lsof -i :8880 | grep LISTEN  # 查看占用进程
kill <PID>                    # 杀掉占用进程

# 再启动 TTS Server
cd $PROJECT_DIR && python3.12 -m src.tts_server
```

### python3.14 不兼容

mlx 只支持 python3.12，必须用 `python3.12` 而非 `python3`：

```bash
python3.12 --version  # 应输出 Python 3.12.x
```

### CDP 9222 不可用导致采集失败

```bash
curl 127.0.0.1:9222/json       # 验证 CDP 可用
pgrep -la "Google Chrome"      # 确认 Chrome 在运行
```

CDP 不可用通常是 Chrome 未以调试模式启动，重启 Chrome 并加 `--remote-debugging-port=9222`。

### TTS 超时（脚本过长）

脚本超过 20000 字时 TTS 容易超时，用 `--rebuild` 重跑：

```bash
cd $PROJECT_DIR
python3.12 -m src.roundtable.generate --rebuild --topic "话题" --skip-upload
```

`_tts_chunks/` 断点续传会自动跳过已完成片段。

### MP3 太大无法发 Discord / Telegram

上限 16MB，30min 播客约 30MB，压缩到 64kbps：

```bash
ffmpeg -i podcast.mp3 -b:a 64k podcast_compressed.mp3
```

或改发 CloudFront 播放链接。

### Iris QA 审计 FAIL

```bash
cat $OUTPUT_DIR/roundtable/{date}/{slug}/iris_audit.json | python3.12 -m json.tool
```

常见原因：
- `TTS 完整度 < 0.85`：音频过短 → `--rebuild` 重跑 TTS
- `真名安全性 FAIL`：脚本含真实人名 → 手动编辑 `script.txt` 后 `--rebuild`

---

## 典型示例

```bash
# 30min AI 行业深度圆桌（本地调试）
cd $PROJECT_DIR
python3.12 -m src.roundtable.generate \
  --topic "2026 年 AI Agent 的商业化困境" \
  --duration 30min \
  --style deep_dive \
  --skip-upload

# 每日日报（全自动）
python3.12 -u -m src.daily

# 脚本已生成，只重跑 TTS（调音质用）
python3.12 -m src.roundtable.generate \
  --topic "话题" \
  --rebuild \
  --skip-upload

# 独立 TTS（不走播客 pipeline）
curl -s -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "今日资讯摘要", "voice": "zhouxun"}' \
  -o daily_summary.mp3
```
