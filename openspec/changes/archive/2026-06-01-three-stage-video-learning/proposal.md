## Why

当前系统输出一段摘要文字，用户看完就忘。作为视频学习工具，缺少结构化的学习体验——没有预习引导、没有可导航的知识索引、没有巩固机制。用户粘贴 URL 后得到的是一坨文字，不是学习材料。

## What Changes

将视频学习体验重构为三阶段结构，一次 LLM 调用生成三份结构化材料：

**预习（Preview）**
- 视频概述（不剧透核心解答）
- 核心问题列表（带着问题去看）
- 看前测验（3-5 题，检验前置知识）

**索引（Index）**
- 知识点列表，每条带时间戳
- 时间戳链接到原视频（外链跳转 B站/YouTube 对应时间点）
- 精度要求：80% 即可，允许 ±10s 偏差

**总结（Summary）**
- 完整内容总结
- 知识卡片（保留现有）
- 复习测验（保留现有，区分"看前"和"看后"）
- 薄弱点标记

UI 以三个 Tab 呈现，视频播放器区域保留在页面上。

## Capabilities

### New Capabilities
- `three-stage-learning`: 三阶段视频学习体验——预习摘要、时间轴索引（外链跳转）、看后总结，一次 LLM 调用生成结构化 JSON 输出

### Modified Capabilities
- `review-doc`: 交互式复习文档重构为三 Tab 结构（预习/索引/总结），知识卡片和测验归入总结 Tab

## Non-goals

- 不扩展内容源（不做文章、播客、PDF）
- 不做社交/协作功能
- 不做内嵌视频播放器（用外链跳转，保持简单）
- 不做跨视频知识图谱（后续提案）

## Impact

- **core/llm/prompts.py**: 新增三合一 prompt，输出结构化 JSON（preview + index + summary）
- **core/pipeline.py**: 单次 LLM 调用产出三份材料，pipeline 输出格式变更
- **core/review_doc.py + templates/**: 重构为三 Tab 结构，索引 Tab 带时间戳外链
- **core/web/app.js + index.html + style.css**: Tab 切换交互、索引时间戳渲染、外链跳转
- **core/api/routes.py**: 返回数据结构变更为三段式
- **core/storage/db.py**: 存储结构适配三段式输出
