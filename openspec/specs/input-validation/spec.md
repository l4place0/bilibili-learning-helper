## ADDED Requirements

### Requirement: Enum constraint on request fields
系统 SHALL 使用 enum 约束 language、mode、detail 字段。

#### Scenario: Invalid language
- **WHEN** 请求 language="fr"（不在 zh/en/ja 中）
- **THEN** 返回 422 Validation Error

#### Scenario: Invalid mode
- **WHEN** 请求 mode="video"（不在 audio/multimodal 中）
- **THEN** 返回 422 Validation Error

### Requirement: URL length limit
系统 SHALL 限制 URL 最大长度为 2000 字符。

#### Scenario: Normal URL
- **WHEN** 请求 url 长度 100 字符
- **THEN** 正常处理

#### Scenario: Excessive URL
- **WHEN** 请求 url 长度 5000 字符
- **THEN** 返回 422 Validation Error
