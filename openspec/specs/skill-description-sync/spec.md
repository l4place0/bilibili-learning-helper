## ADDED Requirements

### Requirement: Skill description matches backend capabilities
SKILL.md SHALL 准确描述后端所有可用功能。

#### Scenario: Batch submit described
- **WHEN** 用户询问如何一次提交多个视频
- **THEN** Claude 能从 SKILL.md 中找到批量提交的使用说明

#### Scenario: Task retry described
- **WHEN** 用户询问失败任务如何重试
- **THEN** Claude 能从 SKILL.md 中找到重试说明

#### Scenario: Export described
- **WHEN** 用户询问如何导出总结到 Obsidian
- **THEN** Claude 能从 SKILL.md 中找到导出说明

### Requirement: Summarize script supports batch
`summarize.sh` SHALL 支持批量提交多个 URL。

#### Scenario: Batch via script
- **WHEN** 执行 `bash summarize.sh "url1" "url2" "url3"`
- **THEN** 调用 batch API 提交所有 URL
- **AND** 返回所有 task_id

#### Scenario: Single URL backward compatible
- **WHEN** 执行 `bash summarize.sh "url1"`
- **THEN** 行为与之前完全一致
