## ADDED Requirements

### Requirement: Retry failed tasks
系统 SHALL 支持对失败任务一键重试，复用相同 task_id 重新执行 pipeline。

#### Scenario: Retry a failed task
- **WHEN** 用户对 status=failed 的任务点击 "Retry" 按钮
- **THEN** 系统将任务 status 重置为 "pending"
- **AND** 清空 summary、transcript、error、completed_at 字段
- **AND** 保留 metadata、url、platform、favorite 字段
- **AND** 启动新的 pipeline 后台线程

#### Scenario: Retry button visibility
- **WHEN** 任务 status 为 "failed"
- **THEN** 结果区域显示 "Retry" 按钮
- **WHEN** 任务 status 为非 "failed"
- **THEN** 不显示 "Retry" 按钮

#### Scenario: Retry updates progress
- **WHEN** 重试的 pipeline 开始执行
- **THEN** 前端通过轮询看到 status 从 "pending" 开始逐步更新

### Requirement: Retry API endpoint
系统 SHALL 提供 `POST /api/tasks/{task_id}/retry` 端点。

#### Scenario: Successful retry request
- **WHEN** POST /api/tasks/{task_id}/retry 且任务 status 为 "failed"
- **THEN** 返回 202 和 task_id
- **AND** 后台启动新的 pipeline

#### Scenario: Retry non-failed task
- **WHEN** POST /api/tasks/{task_id}/retry 且任务 status 非 "failed"
- **THEN** 返回 400 错误
