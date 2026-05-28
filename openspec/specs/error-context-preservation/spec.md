## ADDED Requirements

### Requirement: Pipeline error logging preserves traceback
系统 SHALL 在 pipeline 错误日志中保留完整 traceback。

#### Scenario: Pipeline exception
- **WHEN** pipeline 执行过程中抛出异常
- **THEN** 日志记录包含完整 traceback（通过 logger.exception 或 exc_info=True）

#### Scenario: Error stored in task
- **WHEN** pipeline 失败
- **THEN** task.error 字段包含异常类型和消息（str(e)）

### Requirement: ffprobe failure logging
系统 SHALL 在 ffprobe 失败时记录日志。

#### Scenario: ffprobe returns error
- **WHEN** ffprobe 命令执行失败或返回无效 JSON
- **THEN** 记录 warning 级别日志，包含 stderr 内容

#### Scenario: ffprobe timeout
- **WHEN** ffprobe 超过 10 秒未响应
- **THEN** 记录 warning 级别日志，返回 duration=0

### Requirement: Classification error type distinction
系统 SHALL 区分分类阶段的不同错误类型并分别处理。

#### Scenario: JSON decode error
- **WHEN** LLM 返回非 JSON 内容
- **THEN** 记录 LLM 原始响应内容，重试（最多 3 次）

#### Scenario: Network error
- **WHEN** LLM API 请求超时或连接失败
- **THEN** 记录网络错误详情，重试（指数退避）

#### Scenario: LLM rate limit
- **WHEN** LLM API 返回 429
- **THEN** 记录 rate limit 错误，等待后重试

### Requirement: Consistent error logging patterns
系统 SHALL 在所有 LLM 调用中使用一致的错误日志模式。

#### Scenario: OpenAI API error
- **WHEN** OpenAI API 返回错误
- **THEN** 日志包含 provider 名称、错误类型、请求参数摘要

#### Scenario: Claude API error
- **WHEN** Claude API 返回错误
- **THEN** 日志包含 provider 名称、错误类型、请求参数摘要
