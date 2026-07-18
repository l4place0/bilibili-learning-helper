## Context

当前 pipeline 是线性的：下载 → 转录 → 分类 → 生成摘要 → 生成问题。摘要是一段 Markdown 文字，问题是从摘要中抽取的 Q&A 卡片。用户得到的是"一篇文章"，不是"学习材料"。

现有架构的关键约束：
- LLM 调用是 pipeline 中最贵的环节（时间 + token），当前分类和摘要各一次调用
- 转录文本带有 segment 级时间戳（Whisper 输出 start_time/end_time），但摘要生成时时间信息被丢弃
- Review Doc 已有 Tab 结构（summary/cards/timeline），可以复用
- 平台适配层（BilibiliPlatform/YouTubePlatform）已抽象，URL 构建外链容易

## Goals / Non-Goals

**Goals:**
- 一次 LLM 调用同时生成预习、索引、总结三份结构化材料
- 索引中的每个知识点带时间戳，可外链跳转到原视频对应位置
- 预习阶段给框架和问题但不剧透核心解答
- 总结阶段保留现有知识卡片和复习测验功能
- UI 以三 Tab 呈现，体验连贯

**Non-Goals:**
- 不做内嵌视频播放器
- 不扩展内容源（文章、播客、PDF）
- 不做跨视频知识关联
- 不追求时间戳 100% 精确（±10s 可接受）

## Decisions

### D1: 单次 LLM 调用生成三段式 JSON

**选择**: 一次调用，prompt 要求 LLM 返回结构化 JSON，包含 preview、index、summary 三个字段。

**替代方案**: 三次独立调用（preview/index/summary 各一次）。

**理由**:
- 省 token：共享同一份转录上下文，不需要重复传入
- 省时间：一次调用 vs 三次
- 输出一致性：同一份上下文生成的三份材料风格和深度更统一
- 风险：输出更长，可能截断。缓解：prompt 中控制各部分长度，summary 部分允许流式追加

**JSON 结构**:
```json
{
  "preview": {
    "overview": "2-3 句概述",
    "questions": ["核心问题1", "核心问题2", "..."],
    "pre_quiz": [
      {"question": "...", "options": ["A","B","C","D"], "answer": "A", "explanation": "..."}
    ]
  },
  "index": [
    {"time_seconds": 225, "time_display": "03:45", "label": "知识点标题", "detail": "一句话说明"}
  ],
  "summary": {
    "text": "完整总结文本（Markdown）",
    "cards": [
      {"question": "...", "answer": "...", "difficulty": 3, "bloom_level": "understand"}
    ],
    "post_quiz": [
      {"question": "...", "options": ["A","B","C","D"], "answer": "B", "explanation": "..."}
    ],
    "weak_points": ["薄弱知识点1", "..."]
  }
}
```

### D2: 时间戳从 Whisper segments 映射

**选择**: LLM 在 index 中输出 time_seconds（秒数），后端校验其落在合理 segment 范围内（±10s 容差）。前端用 time_seconds 构建外链。

**替代方案**: 让 LLM 直接输出 B站/YouTube 的 URL。

**理由**:
- 平台无关：同一个 time_seconds 可以构建不同平台的外链
- 后端校验简单：只需检查 time_seconds 在 0 到 duration 之间
- 前端灵活：根据 platform 类型拼接不同的 URL 格式

**外链格式**:
- YouTube: `https://youtube.com/watch?v={id}&t={seconds}`
- Bilibili: `https://bilibili.com/video/{bvid}?t={seconds}`

### D3: 预习与总结的 prompt 策略

**选择**: 在同一个 prompt 中明确区分三份输出的风格要求：
- preview: "只给框架和问题，不要给出核心解答"
- index: "每个知识点用一句话概括，标注时间点"
- summary: "完整展开，保留细节"

**理由**: 80% 效果即可，不需要过度工程化。LLM 对"不要剧透"的遵从度约 80%，可接受。

### D4: Pipeline 集成方式

**选择**: 在现有 pipeline 的 summarize 阶段替换为三段式生成，不新增 pipeline 阶段。

**替代方案**: 新增 preview/index/summary 三个独立阶段。

**理由**:
- 减少 pipeline 改动量
- 一次 LLM 调用天然对应一个阶段
- 分类阶段保留不变（用于 prompt 路由）
- 问题生成阶段可以移除（已内嵌到三段式输出中）

**Pipeline 变化**:
```
旧: download → transcribe → classify → summarize → generate_questions
新: download → transcribe → classify → generate_three_stage
```

### D5: Review Doc UI 改造

**选择**: 复用现有 Review Doc 的 Tab 结构，重新定义三个 Tab：
- Tab 1 "预习": preview 内容 + 看前测验
- Tab 2 "索引": 知识点列表 + 时间戳外链
- Tab 3 "总结": 完整总结 + 知识卡片 + 复习测验 + 薄弱点

**理由**: Review Doc 已有 Tab 切换、卡片翻转、SRS 等交互组件，复用成本低。

## Risks / Trade-offs

**[R1] LLM 输出 JSON 格式不稳定** → 使用 JSON mode（如果 provider 支持）+ 后端解析容错（正则提取 fallback）。已有 classify 阶段的 JSON 解析经验。

**[R2] 单次调用输出太长导致截断** → prompt 中限制各部分长度（preview ≤ 500字, index ≤ 20条, summary ≤ 2000字）。如果仍然截断，index 和 preview 优先，summary 可以流式补完。

**[R3] 时间戳精度不够** → 接受 ±10s 偏差。前端显示 time_display（格式化时间），外链用 time_seconds。用户体验上，跳转后手动找几秒可以接受。

**[R4] 预习内容剧透** → prompt 约束 + 80% 效果即可。如果 LLM 偶尔剧透，不影响核心体验。

**[R5] 向后兼容** → 旧任务数据没有 preview/index 字段，前端需要处理缺失情况（只显示 summary Tab）。
