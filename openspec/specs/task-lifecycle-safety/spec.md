## ADDED Requirements

### Requirement: Prevent deleting active tasks
系统 SHALL 拒绝删除正在处理中的任务。

#### Scenario: Delete running task
- **WHEN** 用户请求删除 status 为 "downloading" 的任务
- **THEN** 返回 409 Conflict，任务不被删除

#### Scenario: Delete completed task
- **WHEN** 用户请求删除 status 为 "done" 或 "failed" 的任务
- **THEN** 任务和关联文件被正常删除

### Requirement: Protect active task files during cleanup
系统 SHALL 在清理缓存时排除活跃和收藏任务的文件。

#### Scenario: Clean cache with active tasks
- **WHEN** 调用 clean_cache 且存在正在处理的任务
- **THEN** 活跃任务的音频、转录、帧文件不被删除

#### Scenario: Clean cache with favorites
- **WHEN** 调用 clean_cache 且存在收藏任务
- **THEN** 收藏任务的文件不被删除
