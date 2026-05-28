## ADDED Requirements

### Requirement: Persist classification results to database
Pipeline SHALL 将分类结果（content_type、language）写入任务的 metadata 字段。

#### Scenario: Classification completes successfully
- **WHEN** LLM 分类阶段返回 content_type 和 language
- **THEN** metadata dict 中新增 `content_type` 字段（值为 tutorial/tech_talk/demo/review/news/vlog/general 之一）
- **AND** metadata dict 中新增 `language` 字段（值为 zh/en 等）
- **AND** 数据库更新对应任务的 metadata

#### Scenario: Classification fails
- **WHEN** 分类失败使用默认值 "general"
- **THEN** content_type 存储为 "general"

### Requirement: Export reads classification from metadata
导出 Markdown 功能 SHALL 从 metadata 中读取 content_type 和 language 填充 frontmatter。

#### Scenario: Export with stored classification
- **WHEN** 用户导出已完成任务的 Markdown
- **THEN** frontmatter 中 `content_type` 字段值来自 metadata.content_type
- **AND** frontmatter 中 `language` 字段值来自 metadata.language

#### Scenario: Export legacy task without classification
- **WHEN** 导出旧任务（metadata 中无 content_type 字段）
- **THEN** content_type 和 language 默认为空字符串
