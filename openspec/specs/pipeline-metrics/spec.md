## ADDED Requirements

### Requirement: Track pipeline stage metrics
系统 SHALL 记录 pipeline 每个阶段的资源用量。

#### Scenario: Successful task metrics
- **WHEN** 任务成功完成
- **THEN** metadata.metrics 包含每个阶段的 duration_ms
- **AND** 包含 download.file_size_bytes、transcribe.text_length、extract_frames.frame_count
- **AND** 包含 total_duration_ms

#### Scenario: Failed task metrics
- **WHEN** 任务在某个阶段失败
- **THEN** metadata.metrics 包含已完成阶段的指标
- **AND** 失败阶段的指标记录到失败点为止

### Requirement: Display metrics in WebUI
系统 SHALL 在 WebUI 任务详情页展示 metrics。

#### Scenario: View completed task metrics
- **WHEN** 用户查看已完成任务的详情
- **THEN** 显示各阶段耗时条形图
- **AND** 显示总耗时、文件大小、文本长度等指标
- **AND** metrics 区域可折叠展开
