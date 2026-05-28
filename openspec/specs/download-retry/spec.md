## ADDED Requirements

### Requirement: Auto-retry on download failure
平台下载 SHALL 在 yt-dlp 失败时自动重试。

#### Scenario: Transient network failure
- **WHEN** yt-dlp 下载因网络错误失败
- **THEN** 系统等待 2 秒后重试
- **AND** 第二次失败等待 4 秒后重试
- **AND** 第三次失败等待 8 秒后重试
- **AND** 最多重试 3 次

#### Scenario: Persistent failure
- **WHEN** 3 次重试后仍然失败
- **THEN** 抛出原始异常，pipeline 标记为 failed

#### Scenario: Success on first attempt
- **WHEN** yt-dlp 下载成功
- **THEN** 不触发重试逻辑

#### Scenario: Retry applies to both audio and video
- **WHEN** 多模态模式下视频流下载失败
- **THEN** 视频流下载也使用相同的重试逻辑
