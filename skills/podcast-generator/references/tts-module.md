# TTS 独立模块

TTS 模块可独立于播客 pipeline 使用，适用于有声书、通知语音、独立语音合成。

## 架构

播客系统有三层 TTS 调用路径：

| 层 | 文件 | 职责 | 谁调用 |
|----|------|------|--------|
| 核心引擎 | `loqui/tts/engine.py` | 模型加载、chunk 合成、质量检测、断点续传、merge | 被下层包装调用 |
| 项目包装 | `src/daily/tts_engine.py` | voice 配置（ref_audio/ref_text）、真名脱敏、stereo pan | 圆桌派 + 日报共用 |
| HTTP 服务 | `src/tts_server.py` | OpenAI 兼容 REST API，单次合成 | OpenClaw 等外部客户端 |

圆桌派的 `generate.py` 直接 import `src.daily.tts_engine.synthesize`，所以两者共用同一个引擎和 voice 配置。

## TTS Server

启动后常驻内存，OpenAI 兼容接口：

```bash
cd $PROJECT_DIR && python3.12 -m src.tts_server
# 健康检查
curl -s http://127.0.0.1:8880/health
```

### API

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

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `input` | string | 必填 | 文本 |
| `voice` | string | `zhouxun` | 声音 ID |
| `response_format` | string | `mp3` | mp3 / wav |
| `speed` | float | `1.0` | 语速 0.5-2.0 |

## tts-clone.sh

独立 bash 脚本，不需要 TTS Server，每次调用直接加载模型。内置 ASR 质量回检。

```bash
VOICES_DIR=$VOICES_DIR TTS_VOICE=zhouxun bash scripts/tts-clone.sh "文本" output.mp3
```

适合单次调用。批量场景建议用 TTS Server 避免重复加载模型。

## 声音配置

| 声音 ID | 角色 | 参考音频 | 参考文本（ref_text） |
|---------|------|----------|---------------------|
| `zhouxun` | 小周（默认，女声） | `zhouxun_mandarin_10s.wav` | "我觉得我刚开始小时候的时候……就是到了人群里边，我就想让大家开心。" |
| `douwendao` | 涛哥（男声） | `douwendao_mandarin_12s.wav` | "我觉得这是我最想生在的时代……起码这时代有空调啊，对吧？" |
| `luyu` | 鲁豫（女声） | `luyu_mandarin_12s.wav` | "我跟许志远认识很久了……那是二零二四年的冬天……" |

参考音频放在 `$VOICES_DIR/`（默认 `~/.openclaw/workspace/voices/`）。

### 参考音频要求

- 格式：WAV，16kHz 或 24kHz 单声道
- 时长：10-30s 效果最佳
- 内容：安静环境，无背景噪音
- **不随 repo 分发**（版权保护，仅供个人研究）

## ASR 质量回检

每个 TTS chunk 生成后可选 ASR 转录回文字，与原文对比：

```
原文 → TTS → 音频 → ASR 转录 → 对比 → 相似度 < 阈值 → 重试
```

| 参数 | pipeline 默认 | tts-clone.sh |
|------|--------------|--------------|
| ASR 模型 | Qwen3-ASR-0.6B-8bit | 同左 |
| 相似度阈值 | 55% | 50% |
| 重试次数 | 2 | 1 |
| 默认状态 | 关闭（`enable_asr=False`） | 开启 |

播客 pipeline 中 ASR 默认关闭，因为 Qwen3-ASR 对 TTS 合成音频存在幻觉问题（识别率不稳定），已改用基于时长的评分替代。通过 `--enable-asr` 可手动开启。

## 断点续传

TTS 中间结果保存到 `_tts_chunks/` 目录，`_progress.json` 记录已完成 chunks。中断后重新执行自动跳过已完成片段。

## 跨日缓存

`$PROJECT_DIR/data/tts_cache/` 按 `sha256(voice_name:text).wav` 缓存。相同声音 + 相同文本自动复用，固定句式（开场白、转场、语气词）会命中缓存。

## 并发限制

TTS 必须严格串行。Apple Silicon 统一内存架构下，并行 TTS 导致 GPU 争抢，音频抖动断裂，OOM 风险极高。一期完成后再启动下一期。
