# TTS 模块细节

## 引擎

`scripts/podcast_tts.py` 是 TTS 引擎包装。核心做的事：

1. 按【Host_A】/【Host_B】切分脚本 → chunks（每段 ≤290 字）
2. 加载 `mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit` 模型
3. 用 `assets/voices/host_female_10s.wav` / `host_male_12s.wav` 作为声音参考
4. 逐段合成 WAV，立体声 pan 分配左右耳，crossfade 200ms 拼接
5. ffmpeg 压缩成 192kbps MP3

## 断点续传

中间 WAV 存 `output/{date}/{slug}/_tts_chunks/`，`_progress.json` 记录已完成。中断后 `--rebuild` 自动跳过已完成片段。

## 跨日缓存

`tts_cache/` 按 `sha256(voice_name:text).wav` 缓存 chunk。相同声音 + 相同文本自动复用——固定句式（开场白、转场、语气词）容易命中。跨期播客都受益。

## ASR 回检（可选）

`--enable-asr` 开启。每个 chunk 合成后用 `mlx-community/Qwen3-ASR-0.6B-8bit` 转录回文字，与原文对比，相似度 < 55% 时重试。

默认关闭，因为 Qwen3-ASR 对 TTS 合成音频存在幻觉，不如基于音频时长/RMS 的评分稳定。

## 并发限制

TTS 必须严格串行。Apple Silicon 统一内存架构下，并行 TTS 会 GPU 争抢，音频抖动断裂，OOM 风险极高。一期完成再启动下一期。

## 单独调用（不走 one_shot）

```bash
python3.12 $SKILL/podcast_tts.py script.txt output.mp3
python3.12 $SKILL/podcast_tts.py script.txt output.mp3 --enable-asr
```

脚本必须是【Host_A】/【Host_B】交替的对话格式。
