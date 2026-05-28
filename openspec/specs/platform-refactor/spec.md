## ADDED Requirements

### Requirement: Shared yt-dlp platform base class
系统 SHALL 提供 `YtdlpPlatform` 基类，封装 yt-dlp 下载、metadata 提取、视频流下载的共享逻辑。

#### Scenario: Bilibili uses shared download logic
- **WHEN** 用户提交 Bilibili 视频 URL
- **THEN** `BilibiliPlatform` 继承 `YtdlpPlatform` 的 `download()` 方法
- **AND** 仅通过 `_get_ydl_opts()` 注入 cookies 配置

#### Scenario: YouTube uses shared download logic
- **WHEN** 用户提交 YouTube 视频 URL
- **THEN** `YouTubePlatform` 继承 `YtdlpPlatform` 的 `download()` 方法
- **AND** 不注入额外 cookies

#### Scenario: Metadata extraction is consistent
- **WHEN** 任意平台下载完成
- **THEN** metadata dict 包含相同的字段集（title, duration, thumbnail, uploader, video_id, description, tags, view_count, like_count, upload_date）

### Requirement: Platform-specific overrides
子类 SHALL 仅覆盖平台差异部分：URL 匹配、URL 解析、yt-dlp 选项。

#### Scenario: Bilibili provides cookies
- **WHEN** cookies 文件存在
- **THEN** Bilibili 的 `_get_ydl_opts()` 返回包含 `cookiefile` 的选项

#### Scenario: YouTube has no cookies
- **WHEN** YouTube 平台下载
- **THEN** `_get_ydl_opts()` 不包含 `cookiefile`
