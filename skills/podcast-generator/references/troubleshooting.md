# 故障排查

## TTS Server 未启动 / 8880 端口冲突

tts-proxy（Rust）可能占用 8880：

```bash
lsof -i :8880 | grep LISTEN    # 查看占用进程
kill <PID>                      # 停掉占用者
cd $PROJECT_DIR && python3.12 -m src.tts_server
```

## python3.14 不兼容

mlx 依赖 Python 3.12 的 C API。3.14 改了 ABI 导致编译失败。必须用 `python3.12`：

```bash
python3.12 --version    # 应输出 Python 3.12.x
which python3.12        # 通常 /opt/homebrew/bin/python3.12
```

## CDP 9222 不可用

```bash
curl 127.0.0.1:9222/json    # 返回 JSON 数组 = 正常
```

不可用原因：Chrome 未以调试模式启动。需要 `--remote-debugging-port=9222` 参数。OpenClaw 环境下由框架管理 Chrome 生命周期。

## TTS 超时（脚本过长）

脚本超过 20000 字时 TTS 容易超时。断点续传会自动恢复：

```bash
cd $PROJECT_DIR
python3.12 -m src.roundtable.generate --rebuild --topic "话题" --skip-upload
```

`_tts_chunks/` 中已完成的片段会自动跳过。

## TTS 音频质量差

症状：吞字、重复、静音段过长。

排查步骤：
1. 检查参考音频质量（是否太短、有背景噪音）
2. 单独用 tts-clone.sh 测试短文本，确认模型本身正常
3. 检查是否有并行 TTS 任务在跑（`ps aux | grep python3.12`）
4. 尝试 `--enable-asr` 开启 ASR 回检

## MP3 太大无法发 Discord / Telegram

上限 16MB，30min 播客约 30MB：

```bash
ffmpeg -i podcast.mp3 -b:a 64k podcast_compressed.mp3
```

或发 CloudFront 播放链接。

## Iris QA 审计 FAIL

查看详细报告：

```bash
cat $OUTPUT_DIR/roundtable/{date}/{slug}/iris_audit.json | python3.12 -m json.tool
```

常见原因：

| FAIL 原因 | 修复方法 |
|-----------|---------|
| TTS 完整度 < 0.85 | 音频过短 → `--rebuild` 重跑 |
| 真名安全性 FAIL | 脚本含真实人名 → 编辑 script.txt 替换后 `--rebuild` |
| 脚本质量 < 7 | 话题太窄或数据不足 → 加 `--context` 补充背景 |

## Bedrock 权限不足

验证是否有 Opus + Haiku 访问权限：

```bash
aws bedrock list-foundation-models --region us-west-2 \
  --query "modelSummaries[?contains(modelId,'claude')]" --output table
```

需要 `us.anthropic.claude-opus-4-6` 和 `us.anthropic.claude-haiku-4-5` 的 inference profile 权限。

## 内存不足 (OOM)

Qwen3-TTS 8bit 模型占用约 1.2GB 统一内存。如果同时运行其他大模型（如 Stable Diffusion），可能触发 OOM。关闭其他模型后重试。
