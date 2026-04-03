---
name: podcast-generator
description: "本地 AI 播客生成 + TTS 语音克隆系统（Apple Silicon only）。包含完整可运行的 TTS 引擎代码和参考音频。当用户提到播客、podcast、圆桌派、roundtable、做一期节目、生成音频、TTS、语音合成、voice clone、把文章变成语音、读一下这段话、有声书、做个音频节目时触发。也适用于调试 TTS 质量、管理播客输出等场景。"
metadata:
  openclaw:
    emoji: "🎙️"
    requires:
      bins: ["python3.12", "ffprobe", "ffmpeg"]
---

# Skill: podcast-generator

> Apple Silicon only (M1/M2/M3/M4)。mlx 不支持 Intel Mac 或 Linux。

本地**中文** AI 播客系统。包含完整可运行的 TTS 引擎和参考音频，开箱即用。

**核心能力：**
- 中文对话式播客生成（双主持人，stereo 立体声，MP3 192kbps）
- 单段文字语音合成（独立 TTS 调用，MP3 128kbps）
- 断点续传 + 跨日缓存（长播客不怕中断）
- **自带两个 demo 声音**（男声 + 女声参考音频，`assets/voices/`），装好依赖即可直接跑

**性能参考（M4 芯片）：**
- 首次运行自动下载模型（~800MB，约 2-5 分钟，之后缓存）
- 模型加载：~30s（首次）/ ~5s（已缓存）
- 合成速率：约 1:1（30 分钟音频 ≈ 30 分钟生成时间）
- 10000 字脚本 ≈ 27 分钟音频

## 目录结构

```
podcast-generator/
├── SKILL.md                          # 本文件
├── scripts/
│   ├── podcast_tts.py                # 播客 TTS 入口（可配置 voice/model）
│   ├── tts-clone.sh                  # 独立单句 TTS（bash 脚本）
│   └── loqui_tts/                    # TTS 核心引擎库
│       ├── __init__.py
│       ├── config.py                 # TTSConfig / VoiceConfig
│       ├── chunker.py                # 文本清理 + 按句断 chunk
│       ├── dialogue.py               # 【角色】标记解析
│       └── engine.py                 # 进程隔离 worker + 质量检测 + 合并
├── assets/voices/
│   ├── host_female_10s.wav           # 女声参考音频（10s, 24kHz mono）
│   └── host_male_12s.wav             # 男声参考音频（12s, 24kHz mono）
└── references/
    ├── tts-module.md                 # TTS 详细文档（Server API、ASR、缓存）
    ├── data-sources.md               # 数据源板块详情
    └── troubleshooting.md            # 故障排查
```

## 30 秒快速启动

只需 3 步，复制粘贴即可：

```bash
# Step 1: 安装依赖（约 1 分钟）
pip3.12 install mlx mlx-audio numpy soundfile pydub pyloudnorm pyyaml
brew install ffmpeg   # 如果没装过

# Step 2: 写一个最简脚本
cat > /tmp/demo.txt << 'EOF'
【Host_A】今天我们来聊一个特别有意思的话题，就是AI到底能不能取代程序员。
【Host_B】这个问题太好了，我觉得短期内肯定不行，但长期来看变化会很大。
【Host_A】对，但你让AI从零设计一个分布式系统，它还是会犯一些很基础的错误。
EOF

# Step 3: 生成播客（首次运行自动下载模型 ~800MB）
cd <skill-path>/scripts
python3.12 podcast_tts.py /tmp/demo.txt /tmp/demo_podcast.mp3
# 完成后用 open /tmp/demo_podcast.mp3 播放
```

## 更多用法

### 单句 TTS（最快体验）

```bash
cd <skill-path>/scripts
bash tts-clone.sh "今天天气不错" /tmp/hello.mp3
TTS_VOICE=host_male bash tts-clone.sh "大家好" /tmp/greeting.mp3
```

### 完整播客脚本

脚本格式：UTF-8 编码，【角色】标记，每段建议 100-300 字。角色名必须和 `podcast_tts.py` 中 `build_voices()` 的 key 一致（默认 `Host_A` / `Host_B`）。

```bash
python3.12 podcast_tts.py script.txt podcast.mp3 [--enable-asr] [--voices-dir /path/to/voices]
```

### 自定义声音

准备自己的参考音频（10-30s WAV，安静环境，24kHz mono），两种方式：

**快速方式**（tts-clone.sh + 环境变量）：
```bash
TTS_VOICE=my_voice TTS_REF_TEXT="参考音频的文字内容" \
  VOICES_DIR=/path/to/voices bash tts-clone.sh "你好" output.mp3
```

**永久方式**（编辑 podcast_tts.py）：在 `build_voices()` 函数中添加新声音配置。

## 技术栈

| 组件 | 技术 | 可替换 |
|------|------|--------|
| TTS 模型 | Qwen3-TTS-12Hz-0.6B-Base-8bit (mlx) | 改 `MODEL_ID`，可选 [mlx-community TTS 模型](https://huggingface.co/collections/mlx-community/) |
| ASR 模型 | Qwen3-ASR-0.6B-8bit (mlx) | 改 `ASR_MODEL_ID`，或禁用 |
| 音频处理 | numpy + soundfile + pyloudnorm | — |
| 编码 | ffmpeg (WAV → MP3) | — |
| Python | 3.12（mlx 依赖 3.12 C API） | 不可替换 |

**关于脚本生成**：本 skill 只包含 TTS 引擎，不包含脚本生成（LLM 对话编写）。脚本生成依赖 LLM（Bedrock/OpenAI/MiniMax 等均可），你可以用任何 LLM 生成 `【角色A】...【角色B】...` 格式的对话脚本，然后喂给 TTS。

## 核心代码说明

### podcast_tts.py — 播客 TTS 入口

可配置的包装层，定义 voice 配置后调用 loqui_tts 引擎。用户主要编辑这个文件：
- `build_voices()` — 添加/修改声音
- `DISPLAY_NAMES` — 真名 → 昵称映射（防止 TTS 读出真名）
- `VOICE_PAN` — 立体声左右声道分配
- `MODEL_ID` — 切换 TTS 模型

### loqui_tts/engine.py — TTS 核心引擎

进程隔离 worker 架构：模型在子进程加载一次，主进程通过 stdin/stdout JSON 通信。这样设计是因为 mlx 模型加载后无法释放内存，子进程退出时 OS 自动回收。

质量检测 4 层：
1. **RMS 音量** < 阈值 → 重试（太安静/静音）
2. **重复检测** autocorrelation > 0.9 → 重试
3. **异常静音** 连续 >1.5s → 重试
4. **ASR 回检** 相似度 < 55% → 重试（吞字/乱码，需 `--enable-asr`）

高级音频合并：
- 200ms crossfade（消除拼接痕迹）
- 短 chunk（<3s）加速 1.05x + 与前段叠加（模拟"抢话筒"自然感）
- stereo pan（角色空间分离）
- pink noise -40dB 底噪（增加质感，消除数字静音的不自然感）
- LUFS -16 响度标准化

### tts-clone.sh — 独立单句 TTS

不依赖 loqui_tts，直接加载 mlx 模型推理。内置 ASR 质量回检。适合一次性调用，批量场景建议用 `podcast_tts.py`（模型只加载一次）。

## 重要约束

**TTS 必须串行运行**。Apple Silicon 统一内存架构下，并行 TTS 会导致 GPU 争抢，音频抖动断裂，ASR 相似度骤降。一期做完再做下一期。

**python3.14 不兼容**。mlx 编译依赖 3.12 的 C API，3.14 改了 ABI。必须用 `python3.12`。

## 参考音频要求

`assets/voices/` 已内置两个参考音频，可直接使用。添加自己的声音时：

- 格式：WAV，24kHz 单声道（16bit PCM）
- 时长：10-30s，效果最佳
- 内容：安静环境，无背景噪音，正常语速
- 需配套 ref_text（参考音频的精确文字转录）

## 故障排查

详见 `references/troubleshooting.md`。常见问题：

| 症状 | 修复 |
|------|------|
| TTS 超时 | 重新运行，断点续传自动恢复 |
| 音频质量差 | 检查参考音频质量 + 确认无并行 TTS |
| python3.12 找不到 | `brew install python@3.12` |
| ffmpeg 找不到 | `brew install ffmpeg` |
| 模型下载慢 | `HF_ENDPOINT=https://hf-mirror.com` 设置镜像 |

## Reference 文件

| 文件 | 何时读取 |
|------|---------|
| `references/tts-module.md` | TTS Server HTTP API、ASR 回检细节、缓存机制 |
| `references/data-sources.md` | 每日日报板块配置（用于完整播客 pipeline） |
| `references/troubleshooting.md` | 遇到故障时 |
