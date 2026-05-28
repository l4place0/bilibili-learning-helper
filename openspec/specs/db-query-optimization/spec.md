## ADDED Requirements

### Requirement: video_id indexed column for cache lookup
系统 SHALL 使用独立的 video_id 列和索引进行缓存查询。

#### Scenario: Cache hit
- **WHEN** 查询已存在的 video_id
- **THEN** 通过 SQL WHERE 子句直接定位，不扫描全表

#### Scenario: Cache miss
- **WHEN** 查询不存在的 video_id
- **THEN** SQL 查询返回空结果，不扫描全表

#### Scenario: Migration from metadata
- **WHEN** 升级后首次启动，数据库无 video_id 列
- **THEN** 自动添加列并从 metadata JSON 中提取填充

### Requirement: Batch database updates
系统 SHALL 支持在 pipeline 结束时批量提交多个字段更新。

#### Scenario: Single task pipeline
- **WHEN** pipeline 完成，需要更新 status, summary, transcript, progress 等字段
- **THEN** 所有更新在一次 commit 中完成

#### Scenario: Multiple field update
- **WHEN** 调用 `update_task(task_id, status="done", summary="...", transcript="...")`
- **THEN** 单次 SQL UPDATE 完成所有字段更新（已有的行为，确认正确）

#### Scenario: Pipeline progress updates
- **WHEN** pipeline 中间阶段更新 progress
- **THEN** 允许单独 commit progress 更新（不需要等待 pipeline 结束）
