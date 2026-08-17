# Bili Tutor CLI

[English](README_EN.md) | 中文

面向本地视频学习工作流的确定性 CLI。它负责下载、转写、候选关键帧、缓存和
笔记原子写入；用户意图理解、术语增强、视觉筛选、总结与 Mermaid 图由独立的
[bili-tutor-skill](https://github.com/l4place0/bili-tutor-skill) 交给宿主 AI 完成。

## 核心链路

```text
视频链接
  → video-sum capture
  → 原始转写稿 + 候选关键帧 + 可选评论/弹幕材料
  → 宿主 AI 分析
  → video-sum resource compose
  → 单份 Markdown 笔记 + 同级 assets/
```

支持 Bilibili 与 YouTube、中文/英文/日文转写、用户级分层缓存，以及三种
ASR 方式：本机 `whisper.cpp`、OpenAI 转写 API、兼容 HTTP 转写服务。
Whisper 模型与 `whisper-cli` 不包含在发布产物中。

## 安装

面向用户的推荐入口是安装
[bili-tutor-skill](https://github.com/l4place0/bili-tutor-skill)，由其薄安装脚本
下载本仓库 GitHub Release 中对应平台的独立产物。产物包含 CLI、Python
运行时、Python 依赖、yt-dlp、OpenAI ASR 客户端和 FFmpeg：

```text
bili-tutor-cli-<version>-<platform>-<arch>.zip
├── video-sum[.exe]
└── manifest.json
```

源码开发安装：

```bash
git clone https://github.com/l4place0/bili-tutor-cli.git
cd bili-tutor-cli
uv sync --extra dev
uv run video-sum --help
```

## CLI 原语

```bash
video-sum doctor
video-sum capture "<URL>" --frame-mode hybrid --cache reuse --frames 10
video-sum resource compose "<resource_id>" ...
video-sum library list|show|search
video-sum cache dir|status|list|inspect|prune|clear
video-sum frames extract "<video-file>" --at 12:30 --around 2
video-sum asr profiles
video-sum comments fetch "<URL>" --mode hot --output comments.jsonl
video-sum comments select comments.jsonl --output comment-candidates.json
video-sum danmaku fetch "<URL>" --output danmaku.jsonl
video-sum danmaku analyze danmaku.jsonl --output danmaku-analysis.json
```

`capture` 只生成可复用的原始材料。宿主 AI 完成内容处理后，使用
`resource compose` 写入最终笔记。每条资源只产生一份 Markdown，一级标题为：

```markdown
# 总结稿
# 辅助理解
# Data
```

图片统一放在笔记同目录的 `assets/`，不创建视频专属目录。

评论原语默认获取热门高赞一级评论；`--mode all --limit 0` 可获取所有当前
可访问的一级评论，但不包含楼中楼，且可能耗时或触发平台限流。弹幕原语通过
匿名 `seg.so` 分段接口获取当前可访问弹幕，不获取历史弹幕；接口失败时降级
到 XML 样本并在 metadata 中标记 `sampled_degraded`。

`danmaku analyze` 只生成时间热点、规范化复读簇和透明的情感词典信号，
`comments select` 只按互动与信息量生成评论候选。二者都明确要求宿主 AI
完成语义判断；高赞不代表事实正确。

## 保存目录与配置

```dotenv
VIDEO_SUM_LIBRARY_DIR=/Users/you/Documents/video-notes
VIDEO_SUM_CACHE_DIR=/Users/you/Library/Caches/video-sum
VIDEO_SUM_MODEL_DIR=/Users/you/Library/Application Support/video-sum/models
VIDEO_SUM_DEFAULT_LANGUAGE=zh
VIDEO_SUM_DEFAULT_FRAMES=10
VIDEO_SUM_DEFAULT_FRAME_MODE=hybrid
VIDEO_SUM_DEFAULT_CACHE_POLICY=reuse
VIDEO_SUM_FACT_CHECK=auto
VIDEO_SUM_FACT_CHECK_SOURCE_POLICY=primary-first
```

优先级为：CLI 参数 > 环境变量 > 项目 `.env` > 用户 `config.env` > 系统或
内置默认值。缓存 manifest 只保存稳定 cache key，入选帧复制到 `assets/`，
因此笔记可以整体搬移。

## 开发与发布

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv sync --extra standalone
uv run python scripts/build_standalone.py \
  --target darwin-arm64 --version 0.3.1
```

推送匹配 `v*` 的 tag 会触发 GitHub Actions，构建五个平台的 ZIP 与
SHA-256 sidecar。架构边界见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## License

MIT
