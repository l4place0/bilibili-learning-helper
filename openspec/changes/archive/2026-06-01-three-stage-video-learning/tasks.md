## 1. LLM Prompt 与输出解析

- [x] 1.1 在 `core/llm/prompts.py` 中新增三合一 prompt（THREE_STAGE_PROMPT），要求 LLM 返回包含 preview/index/summary 的结构化 JSON，中英文各一版
- [x] 1.2 在 `core/llm/base.py`（或合适位置）新增 `generate_three_stage()` 方法，调用 LLM 并解析 JSON 输出，包含正则 fallback 解析逻辑
- [x] 1.3 添加单元测试：验证正常 JSON 解析、malformed JSON fallback、各字段完整性校验

## 2. Pipeline 改造

- [x] 2.1 修改 `core/pipeline.py`，将 summarize + generate_questions 两个阶段合并为 `generate_three_stage` 阶段
- [x] 2.2 调整 pipeline 状态更新：新增 `generating_three_stage` 状态，移除 `generating_questions` 状态
- [x] 2.3 保持 streaming 支持：summary.text 部分通过 SSE 流式推送，preview/index 在最终结果中返回
- [x] 2.4 更新 `core/storage/db.py`，任务结果存储结构适配 preview/index/summary 三段式字段

## 3. API 层适配

- [x] 3.1 修改 `core/api/routes.py`，任务详情接口返回数据包含 preview、index、summary 三个字段
- [x] 3.2 确保旧任务（无 preview/index 字段）返回时这些字段为 null，不报错

## 4. 外链构建

- [x] 4.1 新增工具函数 `build_video_url(platform, video_id, time_seconds)`，根据平台类型构建带时间戳的外链（YouTube/Bilibili）
- [x] 4.2 添加单元测试：YouTube URL 格式、Bilibili URL 格式、未知平台 fallback

## 5. Review Doc UI 改造

- [x] 5.1 修改 `core/templates/review_doc.html`，将现有 Tab 结构重构为"预习/索引/总结"三个 Tab
- [x] 5.2 实现预习 Tab：渲染 overview、questions 列表、pre_quiz 测验（选项 + 判定 + 解释）
- [x] 5.3 实现索引 Tab：渲染知识点列表，每条显示 time_display + label + detail，点击跳转外链（新窗口）
- [x] 5.4 实现总结 Tab：渲染完整 Markdown 总结、知识卡片（翻转交互）、post_quiz 测验、weak_points 高亮
- [x] 5.5 处理向后兼容：旧任务无 preview/index 数据时，隐藏预习和索引 Tab，只显示总结

## 6. Web UI 同步（可选）

- [x] 6.1 检查 `core/web/index.html` 和 `core/web/app.js` 是否需要同步更新以展示三段式结果（如果 Web UI 也展示任务详情）

## 7. 集成测试

- [x] 7.1 端到端测试：提交视频 URL → pipeline 运行 → 验证返回数据包含完整的 preview/index/summary
- [x] 7.2 测试旧任务兼容性：已存在的任务数据仍能正常展示
- [x] 7.3 测试外链跳转：验证 YouTube/Bilibili URL 格式正确
