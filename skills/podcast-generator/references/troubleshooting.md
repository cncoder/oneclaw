# 故障排查

## python3.14 不兼容

mlx 依赖 Python 3.12 的 C API。3.14 改了 ABI 导致编译失败。必须用 `python3.12`：

```bash
python3.12 --version    # 应输出 Python 3.12.x
which python3.12        # 通常 /opt/homebrew/bin/python3.12
```

## TTS 超时（脚本过长）

脚本超过 20000 字时 TTS 容易超时。断点续传会自动恢复：

```bash
python3.12 $SKILL/one_shot.py "话题" --rebuild
```

`output/{date}/{slug}/_tts_chunks/` 中已完成的片段会自动跳过。

## TTS 音频质量差

症状：吞字、重复、静音段过长。

排查：

1. 确认没有并行 TTS 任务：`ps aux | grep python3.12`（Apple Silicon 统一内存，并行会 GPU 争抢）
2. 短文本单独测试，排除模型异常
3. 加 `--enable-asr` 开启 ASR 回检（慢但更稳）

## MP3 太大无法发 Discord / Telegram

Discord 上限 25MB（Nitro 500MB），Telegram 50MB。30min 播客约 30MB：

```bash
ffmpeg -i podcast.mp3 -b:a 64k podcast_compressed.mp3
```

或发 CloudFront 播放链接（见 SKILL.md 发布章节）。

## 内存不足 (OOM)

Qwen3-TTS 8bit 模型占用约 1.2GB 统一内存。如果同时运行其他大模型（如 Stable Diffusion），可能触发 OOM。关闭其他模型后重试。

