## ADDED Requirements

### Requirement: Parallel audio and video download
系统 SHALL 在 multimodal 模式下并行下载音频和视频流。

#### Scenario: Multimodal mode download
- **WHEN** 用户提交任务且 mode=multimodal
- **THEN** 音频下载和视频流下载同时启动
- **AND** 两者都完成后才进入下一阶段

#### Scenario: Video download fails
- **WHEN** 视频流下载失败但音频下载成功
- **THEN** 任务继续处理（降级为 audio-only 模式）

#### Scenario: Audio download fails
- **WHEN** 音频下载失败
- **THEN** 任务标记为 failed
