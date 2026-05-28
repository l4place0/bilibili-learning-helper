## Context

当前 pipeline: URL → download → transcribe(纯文本) → classify → summarize(自由文本) → Review Doc(Q&A cards)

问题：
- 转写稿在 pipeline 中被拼成纯文本，丢失了 Whisper 输出的 segment 时间戳
- 总结是自由文本，无法追溯到原始转写稿位置
- 复习只有 Q&A flashcard 一种形式，缺乏主动学习机制
- 每个视频独立处理，无法跨视频综合分析

## Goals / Non-Goals

**Goals:**
- 总结的每个要点必须可追溯到转写稿的 segment 级位置
- 复习系统从单一 Q&A 扩展为多层题型体系
- 支持多视频一次性提交并生成综合对比分析
- Review Doc 引用可点击跳转到转写稿对应位置

**Non-Goals:**
- 不做实时视频流处理
- 不做自动视频推荐/学习路径规划
- 不做跨设备同步（localStorage 保持本地）
- 不做开放式题目的 AI 自动评分（只做自我评估）

## Decisions

### Decision 1: 转写稿 segment 数据保留方式

**选择**: 在 pipeline 中保留 Whisper 输出的 `segments` 列表（每个 segment 含 start, end, text），与纯文本 transcript 并行存储。

**替代方案**: 只保留纯文本，事后用时间戳重新对齐 → 不可靠，Whisper 的 segment 边界不保证可复现。

**存储**: 新增 `transcript_segments` 字段（JSON 数组），存入 task metadata。传给 LLM 时格式化为 `[S0 @00:00] text [S1 @00:15] text ...`。

### Decision 2: 引用标注的 LLM 指令设计

**选择**: 在总结 prompt 中注入引用规则，要求 LLM 在每个要点后标注 `[Sn]` 或 `[Sn-Sm]`。不强制要求 100% 覆盖（有些总结性语句没有单一来源），但关键事实必须有引用。

**替代方案**: 让 LLM 输出结构化 JSON 每条带引用 → 过于复杂，降低输出质量。

**格式**: `[S12]` 单段引用，`[S12-S15]` 连续段引用，`[S12,S15]` 离散段引用。引用放在句末。

### Decision 3: 题型数据结构

**选择**: 统一题型 JSON schema，所有题型共享基础字段（id, type, difficulty, source_refs），每种题型有扩展字段。

```
基础: {id, type, difficulty, bloom_level, source_refs: [segment_ids], frame_ref}
QA:   + {question, answer}
判断: + {statement, correct: bool, explanation}
选择: + {question, options: [], correct_index, explanation}
填空: + {template: "___是___", blanks: [{position, answer}]}
排序: + {items: [], correct_order}
配对: + {pairs: [{left, right}]}
代码: + {context, missing_code, answer, language}
场景: + {scenario, question, sample_answer, key_points}
解释: + {concept, prompt, evaluation_criteria}
```

**替代方案**: 每种题型独立数据结构 → 增加前端渲染复杂度，不便于统一调度。

### Decision 4: 主动学习题型生成策略

**选择**: 在总结 prompt 之后追加一个独立的"题型生成"prompt 调用，输入为总结结果 + 精简 transcript segments。不与总结合并，避免总结质量下降。

**题型选择**: 根据 content_type 自动选择适合的题型组合（tutorial 偏步骤排序+代码补全，tech_talk 偏对比题+为什么题）。

**数量**: 每个视频生成 15-20 题，覆盖 3-4 种题型。

### Decision 5: 多文稿综合分析架构

**选择**: 两阶段流水线。阶段一：3 个视频各自独立跑完整 pipeline（包括总结+题型生成）。阶段二：用 3 份总结 + 3 份精简 transcript 做综合分析调用。

**Token 控制**: 综合分析阶段不用完整 transcript，而是用：(1) 3 份完整总结 (2) 每个 transcript 的 top-20% 关键 segments（按信息密度排序或取前 N 个 segment）。

**任务关联**: 新增 `group_id` 字段关联同一组多文稿任务，综合分析结果作为 group 级别的 task 存储。

### Decision 6: Review Doc 引用跳转实现

**选择**: 总结文本中的 `[S12]` 渲染为可点击的锚链接，点击后跳转到 Transcript tab 的对应 segment 并高亮。纯前端实现，不需要额外 API。

**帧关联**: 如果 segment 有关联的关键帧，在跳转时同时显示该帧缩略图。

## Risks / Trade-offs

- **[Token 消耗增加]** 引用标注 + 题型生成 + 多文稿综合分析会显著增加 LLM 调用次数和 token 用量。→ 通过精简输入（只传 top segments）、分步调用（不一次性全量）来控制。用户可选择性开启。
- **[LLM 引用准确性]** LLM 可能生成不准确的引用（幻觉引用）。→ 引用是辅助定位，不作为精确索引。前端跳转时做模糊匹配。
- **[题型质量参差]** 自动生成的题目质量取决于视频内容密度和 LLM 能力。→ 提供题型难度标签，用户可跳过低质量题。
- **[多文稿综合分析复杂度]** 3 个长 transcript 的综合分析可能超出 context window。→ 使用精简 summary + top segments，控制输入在 8K tokens 以内。
- **[Review Doc 体积]** 多题型 + 帧图片会增大 HTML 文件体积。→ 帧图片保持 base64 内嵌（已有），题型 JSON 体积可控。

## Open Questions

- 题型生成是否支持用户自定义（类似现有的 prompt 自定义机制）？
- 多文稿综合分析是否支持 2 个或 4+ 个视频，还是固定 3 个？
- "用自己的话解释"题是否需要 LLM 评分，还是只做自我评估？
