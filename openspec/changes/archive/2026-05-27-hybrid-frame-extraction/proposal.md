## Why

当前帧提取默认 `max_frames=10`，对长视频（30分钟+）每帧覆盖数分钟画面，信息密度不足。多模态摘要质量直接受帧覆盖度影响，需要更智能的采样策略来提升长视频的视觉信息捕获能力。

## What Changes

- **混合采样策略**：将视频均分为 60 段，每段中点提取保底帧（60 帧），每段内额外检测最多 2 个 scene 变化帧，去重间距 5s
- **统一图片处理**：所有帧统一缩放到 1280px 宽（保持宽高比），统一转换为 WebP 格式（quality=85）
- **全局 scene 检测**：一次 ffmpeg pass 完成所有 scene 变化点检测，Python 侧按时间戳归段
- **向后兼容**：保留 `max_frames` 和 `frame_interval` 参数作为覆盖选项，新策略为默认行为

## Capabilities

### New Capabilities
- `hybrid-frame-sampling`: 60 段均匀保底 + scene 补充帧的混合采样策略，含去重逻辑和统一图片格式处理
- `ci-test-pipeline`: GitHub Actions CI 流水线，自动运行 pytest + ruff lint

### Modified Capabilities
- `claude-frame-extraction`: 帧提取从固定 timestamp 模式改为混合策略，需更新 spec 中的行为描述

## Impact

- **core/vision/frames.py**：重写 `extract_frames` 函数，新增 `_extract_frames_hybrid` 实现
- **core/config.py**：新增配置项 `frame_format`, `frame_quality`, `frame_width`, `scene_threshold`, `min_gap`, `max_scene_per_seg`
- **core/llm/openai_proto.py, core/llm/claude.py**：图片 media_type 从 `image/jpeg` 改为 `image/webp`
- **tests/test_vision.py**：更新帧提取测试用例
- **.github/workflows/test.yml**：新增 CI 测试流水线（pytest + ffmpeg 系统依赖 + ruff lint）
