---
name: context-engineering
description: 主动管理 context 质量与信噪比，确保决策基于可信、新鲜、相关的信息
---

# Context Engineering

主动管理上下文质量的实践框架。核心原则：**不是所有 context 都平等——验证胜过记忆，新鲜胜过陈旧，精准胜过冗余。**

---

## 1. 五层信任层级 (5-Layer Context Hierarchy)

从最可信到最不可信：

| Layer | 来源 | 信任度 | 处理方式 |
|-------|------|--------|----------|
| **L1** | Tool-verified facts | ★★★★★ | 直接使用，grep/API/file 输出即事实 |
| **L2** | User-stated requirements | ★★★★☆ | 遵循执行，有歧义时确认 |
| **L3** | Loaded skills/docs | ★★★☆☆ | 参考但验证，可能已过时 |
| **L4** | Memory entries | ★★☆☆☆ | 作为线索，需 re-verify 关键细节 |
| **L5** | Training data | ★☆☆☆☆ | 仅作推理辅助，**绝不引用为来源** |

### 决策规则

```
当 L1 与 L4 冲突 → 信任 L1（工具输出 > 记忆）
当 L2 与 L3 冲突 → 信任 L2（用户指令 > 文档）
当 L5 是唯一来源 → 明确标注"基于一般知识，未经验证"
```

---

## 2. Anti-Patterns 识别清单

### 🚨 Starvation（信息饥饿）
- **症状**：关键信息被大量无关 context 淹没
- **检测**：做决策时发现核心依据在 20+ messages 之前
- **修复**：重新加载关键信息，放到决策点附近

### 🚨 Flooding（信息洪泛）
- **症状**：单次加载 3+ skills 或大量文件内容
- **检测**：context 使用率快速逼近 threshold
- **修复**：卸载非必要 context，只保留当前步骤所需

### 🚨 Stale Context（陈旧上下文）
- **症状**：基于早期加载的信息做决策，但源可能已变
- **检测**：用户说"我们之前讨论过"；引用 20+ messages 前的信息
- **修复**：用工具 re-verify（重新读文件、重新调 API）

### 🚨 Trust Confusion（信任混淆）
- **症状**：把 training data 当作已验证事实引用
- **检测**：输出中包含未经工具验证的具体数字/路径/配置
- **修复**：降级为假设，立即用工具验证

### 🚨 Context Leakage（上下文泄漏）
- **症状**：敏感数据（token、密码）在不需要时仍留在 context 中
- **检测**：压缩后敏感信息是否仍在摘要中
- **修复**：不将敏感值写入 memory；处理完立即停止引用

---

## 3. 主动管理技术

### Prune（修剪）
```
加载 skill 前问自己：
□ 这个 skill 对当前步骤是否必需？
□ 能否用 1-2 句话替代整个 skill 的加载？
□ 是否已有足够信息完成任务？

如果任一为否 → 不加载
```

### Verify（验证）
```
需要 re-verify 的信号：
□ 引用的文件内容是 10+ messages 前读取的
□ 基于 memory entry 做具体操作（路径、配置值）
□ 用户暗示情况可能已变（"我改了..."、"现在..."）

验证方法：read_file / search_files / API call
```

### Prioritize（优先级排序）
```
信息放置原则：
- 最高影响信息 → 紧贴决策点（最近的 message）
- 背景/历史 → 可以在早期 context 中（允许被压缩）
- 一次性参考 → 用完即弃，不写入 memory
```

### Segregate（隔离）
```
隔离规则：
- 用户数据 vs 系统 prompt → 不混合处理
- 不同任务的 context → 切换任务时主动声明边界
- 敏感值 → 仅在使用时引用，不 echo back
```

### Refresh（刷新）
```
触发条件：context 使用 > 50% window
执行步骤：
1. 识别当前活跃目标（用户最近在做什么）
2. 列出仍然相关的关键事实
3. 标记可以丢弃的历史细节
4. 主动向用户确认："我理解当前目标是 X，需要保留 Y 信息，对吗？"
```

---

## 4. Trigger Conditions（触发条件）

当以下情况出现时，**激活 context engineering 思维**：

| 触发信号 | 风险 | 动作 |
|----------|------|------|
| Context 接近 compression threshold (0.75) | 信息丢失 | 主动 summarize，保护关键事实 |
| 单次加载 3+ skills | Flooding | 评估是否每个都必要 |
| 引用 20+ messages 前的信息做决策 | Stale context | 用工具 re-verify |
| 用户说"我们之前讨论过" | Stale/missing | 检查 memory 或请用户重述 |
| 输出包含未验证的具体值 | Trust confusion | 标注或验证 |
| 任务切换（新话题） | Leakage | 声明边界，释放旧 context |

---

## 5. 实操 Decision Tree

```
收到用户请求时：

1. 我需要什么信息来完成这个？
   ├─ 已在 context 中 → 检查 freshness（多久前加载？）
   │   ├─ < 5 messages → 直接使用
   │   └─ > 20 messages → re-verify with tool
   └─ 不在 context 中 → 需要加载
       ├─ 能用工具获取 (L1) → 优先工具
       ├─ 需要加载 skill (L3) → 评估必要性
       └─ 只有 training data (L5) → 标注不确定性

2. 我的 context 健康吗？
   ├─ 使用率 < 50% → 正常
   ├─ 使用率 50-75% → 开始规划 prune
   └─ 使用率 > 75% → 立即执行 refresh
       └─ protect_last_n: 40 messages 不动
       └─ 压缩早期内容，保留关键事实摘要

3. 我即将输出的内容基于什么？
   ├─ L1/L2 → 高置信度输出
   ├─ L3/L4 → 加验证caveat 或先 verify
   └─ L5 → 明确标注 "based on general knowledge"
```

---

## 6. 与系统集成

### Compression 配置协同
- **threshold: 0.75** — 在达到前主动管理，不要等系统强制压缩
- **protect_last_n: 40** — 最近 40 条消息安全，更早的随时可能被压缩
- **实践**：关键事实如果在 40 条之外，写入 memory 或重新加载

### Source-Driven 原则协同
- 所有具体操作建议必须有 L1/L2 来源支撑
- Memory 中的信息用作导航线索，不作为最终依据
- 输出时标注信息来源层级（当不确定时）

---

## 7. Quick Reference Checklist

每次复杂任务开始前：
- [ ] 当前 context 中有哪些是 L1 verified？
- [ ] 有没有加载了但用不上的 skills？（→ prune）
- [ ] 关键假设是否需要 re-verify？
- [ ] 敏感信息是否最小化暴露？
- [ ] Context 使用率是否健康？

每次输出前：
- [ ] 结论基于哪一层信息？
- [ ] 如果基于 L3-L5，是否标注了不确定性？
- [ ] 是否有更好的方式获取 L1 验证？
