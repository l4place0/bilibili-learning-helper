## 1. Config

- [x] 1.1 在 `core/config.py` 新增配置项：`frame_format` (default "webp"), `frame_quality` (default 85), `frame_width` (default 1280), `scene_threshold` (default 0.3), `min_gap` (default 5), `max_scene_per_seg` (default 2), `segments` (default 60)

## 2. Core Frame Extraction

- [x] 2.1 实现 `_detect_scene_changes()` — 全局 ffmpeg scene 检测，返回 `list[tuple[float, float]]`（时间戳, scene 分数）
- [x] 2.2 实现 `_assign_scenes_to_segments()` — 将 scene 候选按时间戳归段，每段取 top-N，执行去重逻辑
- [x] 2.3 实现 `_extract_frames_hybrid()` — 生成保底帧（段中点）+ 合并 scene 帧，统一调用 ffmpeg 提取并转 WebP
- [x] 2.4 实现 `_encode_frame_webp()` — ffmpeg 单帧提取 + scale=1280:-2 + libwebp -quality 85
- [x] 2.5 修改 `extract_frames()` 入口 — 新增 `mode="hybrid"` 默认值，混合模式下调用 `_extract_frames_hybrid()`

## 3. LLM Provider Update

- [x] 3.1 修改 `core/llm/openai_proto.py` — 图片 media_type 从 `image/jpeg` 改为 `image/webp`
- [x] 3.2 修改 `core/llm/claude.py` — 图片 media_type 从 `image/jpeg` 改为 `image/webp`

## 4. Tests

- [x] 4.1 新增 `tests/test_vision.py` 测试用例 — 混合模式帧提取（mock ffmpeg）
- [x] 4.2 新增测试 — scene 检测返回 0 帧时降级为纯均匀采样
- [x] 4.3 新增测试 — 去重逻辑（scene 帧与保底帧 < 5s 时丢弃）
- [x] 4.4 新增测试 — WebP 输出格式验证
- [x] 4.5 更新现有测试 — LLM provider 的 media_type 断言（现有测试使用 .jpg mock 文件，动态 media_type 逻辑兼容，无需改动）

## 5. CI Pipeline

- [x] 5.1 创建 `.github/workflows/test.yml` — GitHub Actions 工作流，触发条件为 push/PR 到 master
- [x] 5.2 配置 Python 矩阵 — Python 3.11 + 3.12，使用 `uv` 安装依赖
- [x] 5.3 配置系统依赖 — 安装 ffmpeg（帧提取测试需要）
- [x] 5.4 配置测试步骤 — `uv run pytest` 并行执行
- [x] 5.5 添加 lint 步骤 — `uv run ruff check`（已在 pyproject.toml 添加 ruff dev 依赖）
