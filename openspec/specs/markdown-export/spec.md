## ADDED Requirements

### Requirement: Export button in result area
WebUI 结果区域 SHALL 显示"导出 Markdown"按钮，仅在任务状态为 done 且有总结内容时可见。

#### Scenario: Button visible after successful summary
- **WHEN** 用户查看一个 status=done 的任务结果
- **THEN** 结果区域显示"导出 Markdown"按钮

#### Scenario: Button hidden during processing
- **WHEN** 用户查看一个 status=processing 的任务
- **THEN** 不显示"导出 Markdown"按钮

### Requirement: Generate Obsidian-compatible Markdown
系统 SHALL 生成带 YAML frontmatter 的 Markdown 文本，包含视频元信息和总结内容。

#### Scenario: Full metadata export
- **WHEN** 用户点击"导出 Markdown"按钮
- **THEN** 生成的 Markdown 包含以下 YAML frontmatter 字段：
  - `title`: 视频标题（字符串，引号包裹）
  - `author`: UP主/频道名（字符串，引号包裹）
  - `url`: 视频原始链接
  - `platform`: 平台标识（bilibili/youtube）
  - `tags`: 标签数组
  - `date`: 导出日期（ISO 格式 YYYY-MM-DD）
  - `duration`: 视频时长（人类可读格式 HH:MM:SS 或 MM:SS）
  - `upload_date`: 视频上传日期
  - `content_type`: 分类结果（tutorial/tech_talk/demo/review/news/vlog/general）
  - `language`: 语言（zh/en）
  - `description`: 视频简介（YAML 多行语法 `|`）

#### Scenario: Markdown body structure
- **WHEN** 生成 Markdown
- **THEN** 正文部分包含：
  - `# {title}` 作为标题
  - `## 总结` 后跟 LLM 总结内容

### Requirement: Copy to clipboard
系统 SHALL 将生成的 Markdown 文本复制到用户剪贴板。

#### Scenario: Successful copy
- **WHEN** 用户点击"导出 Markdown"按钮且剪贴板 API 可用
- **THEN** Markdown 文本被复制到剪贴板
- **AND** 显示成功 toast 提示（2 秒自动消失）

#### Scenario: Clipboard API fallback
- **WHEN** `navigator.clipboard.writeText()` 失败
- **THEN** 使用 `document.execCommand('copy')` 作为 fallback
- **AND** 如果 fallback 也失败，显示错误 toast

### Requirement: Handle missing metadata gracefully
系统 SHALL 在元数据字段缺失时使用合理默认值。

#### Scenario: Missing optional fields
- **WHEN** 某些 metadata 字段为空（如 tags、description）
- **THEN** tags 默认为空数组 `[]`
- **AND** description 默认为空字符串
- **AND** 其他缺失字段使用空字符串
