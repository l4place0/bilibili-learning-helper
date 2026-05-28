## ADDED Requirements

### Requirement: Path traversal prevention in frame serving
系统 SHALL 防止通过文件名参数进行路径穿越攻击。

#### Scenario: Normal frame request
- **WHEN** 用户请求 `/api/tasks/{id}/frames/frame_001.jpg`
- **THEN** 系统在 task 的 output_dir 内查找并返回该文件

#### Scenario: Path traversal attempt
- **WHEN** 用户请求 `/api/tasks/{id}/frames/../../etc/passwd`
- **THEN** 系统返回 404 错误，不泄露系统文件

#### Scenario: Filename with special characters
- **WHEN** 文件名包含 `../`, `..\\`, 或绝对路径
- **THEN** 系统提取纯文件名后在 output_dir 内查找，找不到则返回 404

### Requirement: Column name whitelist in database updates
系统 SHALL 限制 update_task 只能更新预定义的列。

#### Scenario: Valid column update
- **WHEN** 调用 `update_task(task_id, status="done", summary="text")`
- **THEN** 成功更新 status 和 summary 字段

#### Scenario: Invalid column name
- **WHEN** 调用 `update_task(task_id, malicious_column="value")`
- **THEN** 抛出 ValueError，不执行 SQL

#### Scenario: Column name injection
- **WHEN** 调用 `update_task(task_id, **{"1=1; DROP TABLE tasks--": "value"})`
- **THEN** 抛出 ValueError，不执行 SQL

### Requirement: Pydantic input validation for favorite endpoint
系统 SHALL 使用 Pydantic model 验证 set_task_favorite 的输入。

#### Scenario: Valid favorite request
- **WHEN** POST `/api/tasks/{id}/favorite` 带 `{"favorite": true}`
- **THEN** 成功更新任务收藏状态

#### Scenario: Invalid request body
- **WHEN** POST `/api/tasks/{id}/favorite` 带 `{"favorite": "not_bool"}`
- **THEN** 返回 422 Validation Error

#### Scenario: Missing required field
- **WHEN** POST `/api/tasks/{id}/favorite` 带 `{}`
- **THEN** 返回 422 Validation Error
