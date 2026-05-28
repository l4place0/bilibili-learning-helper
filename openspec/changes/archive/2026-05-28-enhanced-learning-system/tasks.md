## 1. 转写稿 segment 数据保留

- [x] 1.1 修改 ASR 模块（inprocess/local/openai）返回 segments 列表（start, end, text）
- [x] 1.2 修改 pipeline 存储 transcript_segments 到 task metadata
- [x] 1.3 修改缓存复用逻辑，同步复制 transcript_segments
- [x] 1.4 新增 segment 格式化工具函数：segments → `[S{n} @MM:SS] text` 格式

## 2. 证据引用式总结 Prompt

- [x] 2.1 修改所有 content_type 的 summary prompt，注入引用指令规则
- [x] 2.2 修改 get_summary_prompt 传入格式化后的 segments（替换原纯文本 transcript）
- [x] 2.3 修改 pipeline 调用链路：获取 segments → 格式化 → 传入 prompt
- [x] 2.4 测试各 content_type 总结是否正确包含 `[Sn]` 引用

## 3. Review Doc 引用跳转

- [x] 3.1 修改 review_doc.py：总结文本中的 `[Sn]` 渲染为可点击锚链接
- [x] 3.2 修改 transcript tab：按 segment 分行显示，每行带时间戳和 id 属性
- [x] 3.3 实现点击引用跳转到 Transcript tab 对应 segment 并高亮 3 秒
- [x] 3.4 实现引用 hover 显示时间戳 tooltip
- [x] 3.5 Transcript segment 附近显示关联帧缩略图（如有）

## 4. 主动学习题型数据结构

- [x] 4.1 定义统一题型 JSON schema（base fields + type-specific extensions）
- [x] 4.2 实现题型解析函数：从 LLM JSON 输出解析为结构化题型列表
- [x] 4.3 修改 review_doc.py 中 parse_review_cards 支持新 schema

## 5. 主动学习 Prompt

- [x] 5.1 编写题型生成 prompt（输入：总结 + 格式化 segments，输出：多题型 JSON）
- [x] 5.2 实现 content_type → 题型组合映射（tutorial 偏步骤/代码，tech_talk 偏概念/对比）
- [x] 5.3 在 pipeline 中新增题型生成阶段（总结完成后独立 LLM 调用）
- [x] 5.4 题型生成结果存入 task metadata（questions 字段）
- [x] 5.5 测试各 content_type 生成的题型质量和数量

## 6. Review Doc 多题型渲染

- [x] 6.1 实现判断题 UI 组件（对/错/不确定 三按钮 + 解释展开）
- [x] 6.2 实现选择题 UI 组件（4 选项单选 + 解释展开）
- [x] 6.3 实现填空题 UI 组件（文本输入 + 即时判分 + 正确答案显示）
- [x] 6.4 实现排序题 UI 组件（拖拽排序 + 判分）
- [x] 6.5 实现配对题 UI 组件（连线或拖拽配对 + 判分）
- [x] 6.6 实现代码补全 UI 组件（代码编辑区 + 判分）
- [x] 6.7 实现场景题/解释题 UI 组件（文本输入 + 自我评估按钮）
- [x] 6.8 实现帧关联题 UI 组件（显示帧图片 + 问题）
- [x] 6.9 实现题型过滤器（按类型筛选题目）
- [x] 6.10 SM-2 调度扩展到所有题型（不只是 QA）

## 7. 多文稿提交与任务关联

- [x] 7.1 数据库新增 group_id 字段（task metadata 或新表）
- [x] 7.2 实现 POST /api/summarize/group API 端点
- [x] 7.3 实现 GET /api/groups/{group_id} API 端点
- [x] 7.4 实现 group 状态追踪（pending/partial/complete/failed）
- [x] 7.5 Web UI 多行 URL 输入支持"作为组处理"选项
- [x] 7.6 Web UI 组进度显示（每个任务独立进度 + 综合状态）

## 8. 多文稿综合分析

- [x] 8.1 实现综合分析 prompt（输入：3 份总结 + top segments，输出：结构化综合文档）
- [x] 8.2 实现 token 控制逻辑：summary 全量 + transcript top 20% segments
- [x] 8.3 实现 Stage 2 触发逻辑：所有组任务 done 后自动启动综合分析
- [x] 8.4 综合分析结果存储为 group 级别的 task
- [x] 8.5 综合复习卡片生成（跨视频对比题）
- [x] 8.6 综合 Review Doc 生成（包含所有单视频题 + 综合题）
- [x] 8.7 Web UI "查看综合"按钮和综合 Review Doc 展示
- [x] 8.8 测试多文稿全流程：提交 → 独立处理 → 综合分析 → Review Doc
