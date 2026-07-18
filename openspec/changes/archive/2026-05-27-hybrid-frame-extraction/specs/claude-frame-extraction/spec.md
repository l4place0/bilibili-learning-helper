## MODIFIED Requirements

### Requirement: Claude uses timestamp-based frame extraction
Claude LLM 的帧提取 SHALL 使用混合采样策略（60 段均匀保底 + scene 补充帧），所有帧统一缩放到 1280px 宽并转换为 WebP 格式。

#### Scenario: Extract frames from long video
- **WHEN** Claude LLM 对长视频（>30min）进行多模态总结
- **THEN** 帧提取使用混合策略：60 段均匀保底 + 每段最多 2 个 scene 补充帧
- **AND** 所有帧缩放到 1280px 宽，格式为 WebP（quality=85）
- **AND** 每帧提取有 30 秒超时保护

#### Scenario: Duration detection fallback
- **WHEN** ffprobe 无法获取视频时长
- **THEN** 回退到 fps filter 方式提取帧
- **AND** 帧图片仍统一缩放到 1280px 宽并转换为 WebP

#### Scenario: Frame extraction timeout
- **WHEN** 单帧提取超过 30 秒
- **THEN** 跳过该帧，继续提取下一帧
