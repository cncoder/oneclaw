---
name: claude-code
description: "调度 Claude Code 执行编程任务。适用场景：写代码、调试、重构、研究、自动化脚本、多文件改动、构建功能、跑测试等任何需要代码执行能力的任务。有编程任务就用这个 skill，不要自己写代码替代 Claude Code。"
metadata:
  openclaw:
    emoji: "⚡"
    requires:
      bins: ["tmux", "claude"]
---

# Skill: claude-code

Claude Code 是完整的自主编程 Agent，不只是代码生成器。把它当超级队友来用。

---

## 模式选择

| 场景 | 模式 |
|------|------|
| 多文件改动、>5 分钟、需要看到进度 | **Interactive（首选）** |
| 单文件、<2 分钟、输出预期明确 | **Background one-shot** |
| 需自我迭代纠错的完整功能开发 | **ralph-loop** |

**接到任务先判断类型**（来自 Anthropic 内部报告）：

| 类型 | 示例 | 策略 |
|------|------|------|
| **外围/异步** | 原型、可视化、测试生成、重构、不熟悉的代码库 | ralph-loop 或 auto-accept，放手让它跑 |
| **核心/同步** | 核心业务逻辑、安全修改、配置变更、多组件联动 | Interactive 模式，同步监督 |

---

## ⚠️ tmux 交互核心规则

**Claude Code 用 Ink TUI 框架。通过 tmux session 管理，比 osascript 更稳定、更可编程。**

### Session 管理架构

**核心机制**：每个 CC 任务一个 tmux session（`cc-{task}`），通过 `/tmp/cc-active-tab` 文件追踪最近启动的 session。

**三个脚本**：
| 脚本 | 用途 | 核心 |
|------|------|------|
| `cc-start.sh` | 创建 tmux session + 启动 CC | 写 `/tmp/cc-active-tab` |
| `cc-send.sh` | 发消息到正确 session | 读 `/tmp/cc-active-tab` |
| `cc-read.sh` | 读取终端输出 | tmux capture-pane |

### 启动新 CC 任务（必须用 cc-start.sh）

```bash
# 标准启动（默认后台，--bare 提速，--max-turns 200 防无限循环）
scripts/cc-start.sh daily-digest

# 指定工作目录
scripts/cc-start.sh tts-fix ~/projects/my-app

# 前台启动（想实时观察时）
scripts/cc-start.sh daily-digest --foreground
scripts/cc-start.sh daily-digest -f

# 自定义 max-turns（大型任务）
scripts/cc-start.sh big-refactor ~/project --max-turns 50

# 不用 --bare（需要 MCP/skills/hooks 时）
scripts/cc-start.sh complex-task ~/project --no-bare

# 查看/接入后台 session
tmux attach -t cc-daily-digest   # Ctrl+B, D 退出回后台
tmux ls  # 列出所有 session
```

**❌ 禁止直接 `tmux new-session` 启动 CC** — 必须用 cc-start.sh，否则 `/tmp/cc-active-tab` 不更新。

### 发送消息

```bash
# 自动发到最近启动的 CC session
scripts/cc-send.sh "你的任务指令"

# 精确指定 session（多 CC session 并存时）
scripts/cc-send.sh --session cc-daily "你的任务指令"

# 多行消息
scripts/cc-send.sh <<'MSG'
读 src/main.py，
告诉我数据采集的流程和关键函数
MSG
```

**Session 定位优先级**（三级 fallback，确保不发错）：
1. `--session <name>` → 精确指定 tmux session
2. `/tmp/cc-active-tab` → cc-start.sh 记录的最近启动 session（带验证）
3. 遍历找**最后一个** cc-* session → 兜底

### 读取终端输出

```bash
scripts/cc-read.sh                       # 自动定位
scripts/cc-read.sh --session cc-daily    # 按 session name
scripts/cc-read.sh --lines 100           # 最近 100 行
scripts/cc-read.sh --full                # 完整 scrollback
```

### 判断 CC 状态

| 终端内容 | 状态 | 行动 |
|----------|------|------|
| `❯` 空提示符 | 完成，等待输入 | 发下一个子任务 |
| `Bootstrapping…` / `Cogitating…` | Context 压缩/思考中 | **等它完成，不要打断，不要 /clear** |
| `Enter to confirm` | 等待确认 | `tmux send-keys -t <session> Enter` |
| `Error` / `failed` | 出错 | 评估是否打断重来 |
| 5 分钟无变化 | 可能卡住 | 上报用户 |

### ❌ 绝对不要做的事

1. **不要手动 /clear** — Claude Code 有 auto-compact，bootstrap 就是它在压缩 context
2. **不要在 Claude Code 正在工作时发新消息** — 会被排队，导致混乱
3. **不要让 Claude Code 一次读超大文件（>10K 字符）** — 分段读
4. **不要直接 tmux new-session** — 必须用 cc-start.sh

---

## CC Session 保护

Claude Code tmux session 不会被误关（tmux 持久化），比终端 tab 更可靠。

### 检测逻辑（可集成到 heartbeat）

```bash
# 检查 CC tmux session
CC_SESSIONS=$(tmux ls -F '#{session_name}' 2>/dev/null | grep '^cc-' || true)
CC_PROC=$(pgrep -f "claude --danger" | head -1)

if [ -z "$CC_SESSIONS" ] && [ -z "$CC_PROC" ]; then
    echo "CC 未运行（无 session 无进程）"
elif [ -z "$CC_SESSIONS" ] && [ -n "$CC_PROC" ]; then
    echo "⚠️ CC 进程在但 tmux session 丢失"
elif [ -n "$CC_SESSIONS" ] && [ -z "$CC_PROC" ]; then
    echo "⚠️ tmux session 在但 CC 进程已退出"
fi
```

---

## 模式一：Interactive（终端 + tmux）

### 渐进式任务交付（核心流程）

**拆分原则**（来自 Anthropic 报告）：

- 按**依赖关系 + 验证节点**切割
- 每个子任务有**明确的完成信号**
- 单个子任务 < 30 分钟
- 不超过 3 个文件
- 核心逻辑 / 边缘功能 / 重构分开

**渐进式流程**：

```
Step 1: 探索 — "读 X 文件，告诉我数据结构 / 代码架构"
  → 完成信号：输出结构描述
  → 检查：结构对吗？理解对吗？

Step 2: 设计 — "基于上面的理解，提出方案"
  → 完成信号：方案文本
  → 检查：方案合理吗？人工确认

Step 3: 小批量验证 — "先处理 20 条 / 实现核心函数"
  → 完成信号：代码/数据可验证
  → 检查：build + test + 抽样 ← 最关键检查点

Step 4: 全量执行 — "按验证通过的方式处理全部"
  → git commit checkpoint
  → 检查：抽查 + 整体验证

Step 5: 打磨 — "检查并修正问题"
  → 完成信号：无明显问题
```

### 每步检查输出（三层验证）

| 层级 | 方法 | 目的 |
|------|------|------|
| 语法层 | `build` / `compile` 通过 | 没有明显错误 |
| 逻辑层 | `test` / `lint` 通过 | 符合规范 |
| 效果层 | 截图 / 日志 / 抽样对比 | 真的符合预期 |

### 打断信号（不要等跑完）

| 信号 | 行动 |
|------|------|
| 搞复杂嵌套方案（3 层以上逻辑） | 打断："找更简单的方法" |
| 同一工具调用失败 3 次 | 打断，换方案 |
| 偏离主目标，在解决副产物 | 打断，重新对焦 |
| 超过预估时间 2x | **Slot Machine：git reset --hard 重来** |
| 输出质量逐步变差 | 回滚到上一个 checkpoint |

**Slot Machine 协议**（Anthropic Data Science 团队验证）：
> 先 `git commit` → 放手让 Claude 跑 → 成功 merge，失败 `git reset --hard` 重来。
> **重来比修复跑偏的中间状态成功率更高。**

---

## 模式二：Background One-Shot

适合简单、输出明确的单次任务：

```bash
# 注意：在 OpenClaw agent 环境内需要 unset CLAUDECODE
unset CLAUDECODE && claude --dangerously-skip-permissions -p "具体任务描述"
```

**注意**：
- 此模式无法中途纠正
- 在 OpenClaw session 内执行时必须 `unset CLAUDECODE`（否则报嵌套错误）
- 只用于 < 2 分钟的明确任务

---

## 模式三：ralph-loop（大型自主任务）

**启动前必须 checkpoint**（Slot Machine 标准流程）：

```bash
# 1. 强制 checkpoint
git add -A && git commit -m "checkpoint: before ralph-loop attempt"

# 2. 启动 ralph-loop
/ralph-loop "Build X. Output <promise>DONE</promise> when tests pass." --completion-promise "DONE" --max-iterations 15
```

- 成功 → merge
- 失败 → `git reset --hard HEAD~1` + 修改 prompt 重来
- 取消：`/cancel-ralph`

---

## CLAUDE.md 工具调用纠正规则

每次遇到重复性错误，加一条规则到项目的 CLAUDE.md（来自 Anthropic RL 团队实践）：

```markdown
# 工具调用规范
- pytest: `pytest tests/ -v`，不要 `python -m pytest`，不要先 cd
- 删除文件: `mv` 到回收目录，不要 `rm`
- Bash 失败 → 先诊断原因，不要 retry 同一命令
- 不要无谓 cd — 用绝对路径
- 长文本用 heredoc 或写文件，不要单行超长命令
```

---

## 两阶段工作法（复杂任务）

来自 Anthropic Legal + Growth Marketing 团队：

1. **规划阶段**：在对话中头脑风暴，生成结构化 prompt：
   ```markdown
   ## 目标
   [一句话]
   ## 约束
   - [限制]
   ## 步骤
   1. [具体可验证的步骤]
   ## 验收标准
   - [可用命令验证的条件]
   ```

2. **执行阶段**：把结构化 prompt 交给 Claude Code

**不要把口语化需求直接丢给 Claude Code** — 先规划再执行。

---

## Claude Code 的能力（别自己做这些）

| 能力 | 说明 |
|------|------|
| **编程** | 任何语言，写/改/调试/重构/测试 |
| **自主纠错** | 构建失败自动修复，直到通过 |
| **Skill 插件** | TDD、code-review、security-review、E2E、frontend-design（50+ skills）|
| **子代理团队** | researcher + coder + reviewer 并行工作 |
| **浏览器控制** | chrome-devtools MCP（CDP）|
| **文档查询** | context7 MCP（最新 API 文档）|

---

## 反模式（血泪教训）

- ❌ 一次性给 500 字需求文档（拆小拆细）
- ❌ 自己替 Claude Code 写代码
- ❌ 同时启动多个 Claude Code 操作同一个 repo
- ❌ 复杂任务用 background one-shot
- ❌ 不验证就说"完成了"
- ❌ 试图修复 Claude 跑偏的中间状态（应该 reset 重来）
- ❌ 等 Claude 跑完才评价（偏了就立刻打断）
- ❌ **手动 /clear**（让 auto-compact 自行处理）
- ❌ **直接 tmux new-session**（必须用 cc-start.sh）
- ❌ **发完不确认就追问**（必须读终端确认提交成功再发下一条）
- ❌ **让 Claude Code 一次读 >10K 字符文件**（context 很快溢出，分段读）
