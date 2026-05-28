## ADDED Requirements

### Requirement: Single-interval batch polling
系统 SHALL 使用单个 setInterval 轮询所有批量任务。

#### Scenario: Batch of 20 URLs
- **WHEN** 用户提交 20 个 URL 的批量任务
- **THEN** 仅创建 1 个 setInterval（而非 20 个），每次遍历所有未完成 task

#### Scenario: All tasks complete
- **WHEN** 所有批量任务完成或失败
- **THEN** 自动停止 setInterval
