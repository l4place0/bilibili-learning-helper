## ADDED Requirements

### Requirement: Pipeline reports sub-stage progress
Pipeline SHALL 在每个阶段内报告 0-100 的进度百分比。

#### Scenario: Download progress
- **WHEN** pipeline 处于 downloading 阶段
- **THEN** progress 字段值在 10-25 范围内
- **AND** 如 yt-dlp 提供 progress hook，进度与下载百分比成比例

#### Scenario: Transcription progress
- **WHEN** pipeline 处于 transcribing 阶段
- **THEN** progress 字段值在 25-50 范围内

#### Scenario: Frame extraction progress
- **WHEN** pipeline 处于 extracting_frames 阶段
- **THEN** progress 字段值在 50-70 范围内
- **AND** 进度与已提取帧数/总帧数成比例

#### Scenario: Classification progress
- **WHEN** pipeline 处于 classifying 阶段
- **THEN** progress 字段值为 75

#### Scenario: Summarization progress
- **WHEN** pipeline 处于 summarizing 阶段
- **THEN** progress 字段值为 90

#### Scenario: Completion
- **WHEN** pipeline 完成
- **THEN** progress 字段值为 100

### Requirement: Frontend displays sub-stage progress
前端 SHALL 在状态标签旁显示阶段内进度百分比。

#### Scenario: Progress percentage visible
- **WHEN** 任务正在处理中（非 done/failed/pending）
- **THEN** status-text 旁显示百分比数字（如 "Transcribing 38%"）

#### Scenario: Done state
- **WHEN** 任务完成
- **THEN** 不显示百分比，仅显示 "Done"
