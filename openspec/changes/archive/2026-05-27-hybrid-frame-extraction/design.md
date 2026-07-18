## Context

当前 `core/vision/frames.py` 提供三种帧提取模式（timestamp、fps、scene），默认 `max_frames=10`，`frame_interval=30`。pipeline 中通过 `extract_frames()` 调用，支持 `prefetched_frames` 预提取。

长视频（30分钟+）每帧覆盖数分钟画面，多模态摘要缺乏足够的视觉信息。同时三种模式的图片处理不一致：timestamp/fps 保留原始分辨率，scene 模式缩放到 1280px，导致 token 消耗不可预测。

## Goals / Non-Goals

**Goals:**
- 默认启用混合采样策略：60 段均匀保底 + scene 补充帧
- 统一所有帧的图片处理：1280px 宽 + WebP 格式
- 通过全局单次 ffmpeg pass 完成 scene 检测，避免逐段调用
- 去重逻辑保证相邻帧间距 >= 5s

**Non-Goals:**
- 不改变 LLM provider 的图片发送逻辑（仅更新 media_type）
- 不引入自适应帧数（按视频内容复杂度动态调整帧数）
- 不支持用户自定义每段 scene 帧数（固定为 2）

## Decisions

### D1: 全局 scene 检测 vs 逐段检测

**选择**: 全局 scene 检测

一次 ffmpeg pass 输出所有 scene 变化点及时间戳，Python 侧按段分配。

**理由**: 逐段检测需要 60 次 ffmpeg 进程启动，开销大。全局检测只需一次 pass，效率高一个数量级。

**替代方案**: 逐段检测 — 更精确但慢 60 倍，且 ffmpeg 的 scene filter 本身是帧级别的，不存在跨段污染问题。

### D2: 保底帧位置 — 段中点

**选择**: 每段中点

**理由**: scene 帧天然偏向变化发生的位置（段的边界附近），保底帧放在段中点可以兜底覆盖静态段落，与 scene 帧形成互补。

**替代方案**: 段首 — 容易与 scene 帧重叠，去重后覆盖不均匀。

### D3: WebP 编码参数

**选择**: `libwebp -quality 85`

**理由**: quality 85 在画质和体积之间平衡良好，比 JPEG 小 25-35%，对 60-170 帧的 base64 传输有明显收益。LLM token 按图片尺寸计算，不受格式影响。

**替代方案**: quality 90 — 画质略好但体积优势减弱；quality 75 — 体积更小但画质损失可感知。

### D4: 统一缩放宽度 1280px

**选择**: `scale=1280:-2`

**理由**: 1280px 宽度对 LLM 视觉理解足够（720p 级别），同时避免 4K 视频的 token 爆炸（4K 帧约 4500 tokens vs 1280px 约 765 tokens）。`-2` 保证高度为偶数，避免某些编码器报错。

### D5: 向后兼容策略

**选择**: 新策略为默认行为，保留 `max_frames` 和 `frame_interval` 参数作为覆盖

当用户显式设置 `max_frames` 时，回退到原有的 timestamp 模式。`extract_frames()` 函数新增 `mode="hybrid"` 默认值。

## Risks / Trade-offs

- **[帧数膨胀]** scene 丰富的视频（vlog、快剪）每段可能都有 2 个 scene 帧 → 最多 180 帧 → LLM 处理时间增加。→ 通过 `max_frames` 硬上限兜底（默认 180），超出时按时间均匀裁剪。
- **[scene 检测失败]** 某些视频（纯色、极低对比度）scene 检测可能返回 0 帧。→ 混合策略自动降级为纯均匀采样，不受影响。
- **[WebP 兼容性]** 极少数旧版 ffmpeg 不支持 libwebp。→ 启动时检测 ffmpeg 编码器支持，不支持时回退 JPEG。
- **[处理时间增加]** 60+ 帧的提取和 base64 编码比 10 帧慢。→ 帧提取本身不是瓶颈（转录和 LLM 调用才是），可接受。
