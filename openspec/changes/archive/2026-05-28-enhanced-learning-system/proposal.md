## Why

当前系统是"视频处理管道"——下载、转录、总结、发布。但作为学习辅助工具，它缺乏三个关键能力：总结无法追溯到原始转写稿（无法验证）、只有被动的 Q&A 卡片（没有主动学习机制）、无法跨视频综合分析（知识是孤岛）。这些差距直接限制了学习效果。

## What Changes

- 总结输出增加 segment 级引用标注（如 `[S12 @02:15]`），每条要点可追溯到转写稿原始位置
- 转写稿保留 segment 级结构化数据（start_time, end_time, text），不再丢失时间信息
- Review Doc 中引用可点击跳转到对应转写稿段落
- 复习卡片从单一 Q&A 扩展为多层题型：判断题、选择题、填空题、排序题、配对题、代码补全、场景题、调试题、"用自己的话解释"、对比题
- 结合关键帧生成看图说话题、视觉推理题
- 结合转写稿生成情境还原题
- 支持多 URL 一次性提交，分别总结后生成综合对比分析
- 综合分析输出：统一理解、各视角独特贡献、共识与分歧、最佳实践提炼、综合复习卡片

## Capabilities

### New Capabilities
- `evidence-citation`: 证据引用式总结——转写稿 segment 保留、LLM 引用标注、Review Doc 引用跳转
- `active-learning`: 主动学习题型——多层题型体系（识别/回忆/应用/分析/综合）、多模态素材题型、自动判分与自我评估
- `multi-source-synthesis`: 多文稿对比总结——多 URL 提交、两阶段流水线（独立总结→综合分析）、跨视频知识整合

### Modified Capabilities
- (无现有 spec 需要修改)

## Impact

- **core/asr/**: Whisper 输出需要保留 segment 级结构化数据，pipeline 传递数据格式变更
- **core/llm/prompts.py**: 所有总结 prompt 需增加引用指令，新增题型生成 prompt，新增综合分析 prompt
- **core/pipeline.py**: 支持多任务关联处理（多文稿场景），新增综合分析阶段
- **core/review_doc.py + templates/review_doc.html**: 扩展题型数据结构和渲染组件，引用跳转交互
- **core/api/routes.py**: 新增多文稿提交 API，题型数据结构变更
- **core/web/app.js + index.html**: 多 URL 提交 UI，题型展示交互
- **core/storage/db.py**: 任务关联关系（多文稿组），题型存储结构
- **Token 消耗**: 多文稿综合分析会显著增加 LLM 调用成本，需要精简策略
