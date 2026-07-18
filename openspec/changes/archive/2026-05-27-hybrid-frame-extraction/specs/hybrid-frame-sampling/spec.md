## ADDED Requirements

### Requirement: Hybrid frame sampling strategy
系统 SHALL 默认使用混合帧提取策略，将视频均分为 60 段，每段中点提取保底帧，每段内额外检测最多 2 个 scene 变化帧。

#### Scenario: Short video (10 minutes)
- **WHEN** 对 10 分钟视频进行帧提取
- **THEN** 保底帧数 = 60（每段 10s）
- **AND** scene 补充帧最多 120 个
- **AND** 去重后总帧数约 60-120 帧

#### Scenario: Long video (2 hours)
- **WHEN** 对 2 小时视频进行帧提取
- **THEN** 保底帧数 = 60（每段 120s）
- **AND** scene 补充帧最多 120 个
- **AND** 去重后总帧数约 150-170 帧

#### Scenario: Scene detection returns zero frames
- **WHEN** scene 检测未发现任何变化点
- **THEN** 系统 SHALL 降级为纯均匀采样，仅使用 60 个保底帧

### Requirement: Global scene detection with segment assignment
系统 SHALL 使用一次全局 ffmpeg pass 完成所有 scene 变化点检测，然后在 Python 侧按时间戳归段。

#### Scenario: Scene detection execution
- **WHEN** 执行混合帧提取
- **THEN** 系统调用一次 ffmpeg 的 `select='gt(scene,threshold)'` 滤镜
- **AND** 输出所有 scene 变化点的时间戳和 scene 分数
- **AND** Python 代码按时间戳将每个 scene 帧分配到对应的段

### Requirement: Frame deduplication with minimum gap
系统 SHALL 对保底帧和 scene 帧进行去重，相邻帧间距不得小于 5 秒。

#### Scenario: Scene frame too close to baseline
- **WHEN** 某段的 scene 帧与保底帧时间差 < 5 秒
- **THEN** 丢弃该 scene 帧

#### Scenario: Two scene frames too close
- **WHEN** 同一段内两个 scene 帧时间差 < 5 秒
- **THEN** 保留 scene 分数更高的帧，丢弃另一个

### Requirement: Unified image processing
系统 SHALL 将所有提取的帧统一缩放到 1280px 宽（保持宽高比），并转换为 WebP 格式（quality=85）。

#### Scenario: 1080p video frame extraction
- **WHEN** 从 1080p 视频提取帧
- **THEN** 输出图片分辨率为 1280×720 WebP

#### Scenario: 4K video frame extraction
- **WHEN** 从 4K 视频提取帧
- **THEN** 输出图片分辨率为 1280×720 WebP
- **AND** 不保留原始 3840×2160 分辨率

#### Scenario: Vertical video frame extraction
- **WHEN** 从竖屏视频（1080×1920）提取帧
- **THEN** 输出图片分辨率为 1280×2276 WebP（宽度固定，高度按比例）

### Requirement: Backward compatibility with explicit max_frames
当用户显式设置 `max_frames` 参数时，系统 SHALL 回退到原有的 timestamp 模式，不启用混合策略。

#### Scenario: User overrides max_frames
- **WHEN** 调用 `extract_frames(video_path, max_frames=10)`
- **THEN** 使用原有的 timestamp 模式
- **AND** 不执行 scene 检测
- **AND** 不进行 WebP 转换（保持原有行为）
