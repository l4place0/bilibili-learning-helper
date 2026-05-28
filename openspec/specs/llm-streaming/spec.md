## ADDED Requirements

### Requirement: Streaming LLM response
系统 SHALL 支持 LLM 流式响应，实时推送到前端。

#### Scenario: Summarize with streaming
- **WHEN** pipeline 执行 summarize 阶段
- **THEN** LLM 响应以流式方式传输
- **AND** 前端逐步显示摘要内容

#### Scenario: SSE connection for streaming
- **WHEN** 前端请求流式任务结果
- **THEN** 通过 SSE (Server-Sent Events) 接收增量更新

#### Scenario: Streaming fallback
- **WHEN** LLM provider 不支持 streaming
- **THEN** 回退到同步模式，行为与当前一致
