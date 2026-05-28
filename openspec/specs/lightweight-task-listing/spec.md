## ADDED Requirements

### Requirement: Lightweight task list query
系统 SHALL 提供不包含 transcript/summary/error 的轻量列表查询。

#### Scenario: History page loads task list
- **WHEN** 前端请求任务列表
- **THEN** 响应不包含 transcript、summary、error 字段
- **AND** 响应大小 < 10KB（50 个任务）

#### Scenario: View single task detail
- **WHEN** 前端请求单个任务详情
- **THEN** 响应包含所有字段（含 transcript/summary）

### Requirement: Database index for task listing
系统 SHALL 为常用查询字段添加索引。

#### Scenario: List tasks ordered by created_at
- **WHEN** 查询任务列表（ORDER BY created_at DESC）
- **THEN** 使用索引排序，不扫描全表

### Requirement: Lightweight polling endpoint
系统 SHALL 提供仅返回 status/progress 的轻量轮询端点。

#### Scenario: Poll task status during processing
- **WHEN** 前端轮询任务状态
- **THEN** 仅返回 task_id, status, progress（< 200 bytes）
