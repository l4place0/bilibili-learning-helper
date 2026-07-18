# Bilibili Learning Helper

[English](README_EN.md) | 中文

基于 Whisper ASR + LLM 的 Bilibili/YouTube 视频摘要工具。

## 功能特性

- **视频摘要** — 自动下载、转录、分类、总结视频内容
- **批量处理** — 支持一次提交多个 URL，批量生成摘要
- **分享链接解析** — 直接粘贴 Bilibili 分享链接（含标题前缀）即用
- **多语言** — 支持中文、英文、日文视频
- **多 LLM** — 支持 OpenAI / Claude
- **多模态** — 可选帧分析模式，结合画面内容生成更丰富摘要
- **Markdown 导出** — 一键导出 Obsidian 兼容的 YAML frontmatter 格式
- **历史管理** — 搜索、筛选、收藏、重试、删除任务
- **Prompt 定制** — 自定义分类和摘要提示词
- **Web UI** — 现代化暗色主题界面

## 快速开始

### 环境要求

- Python 3.10+
- ffmpeg
- yt-dlp

### 安装

```bash
# 克隆仓库
git clone https://github.com/l4place/bilibili-learning-helper.git
cd bilibili-learning-helper

# 安装依赖
uv sync

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 API Key
```

### 启动

```bash
uv run uvicorn core.main:app --port 8000
```

打开浏览器访问 `http://localhost:8000`

### 使用 Skill

```bash
# 单个视频
bash skill/scripts/summarize.sh "https://bilibili.com/video/BVxxxxx"

# 批量提交
bash skill/scripts/summarize.sh "url1" "url2" "url3"

# 检查状态
bash skill/scripts/status.sh

# 检查更新
bash skill/scripts/check-update.sh
```

## Docker 部署

```bash
docker compose up -d
```

## 技术架构

```
用户输入 URL
    │
    ▼
┌─────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ Download │──▶│  Whisper  │──▶│ Classify │──▶│ Summarize│
│ (yt-dlp) │   │  (ASR)   │   │  (LLM)   │   │  (LLM)   │
└─────────┘   └──────────┘   └──────────┘   └──────────┘
                  │                              │
                  ▼                              ▼
            转录文本                        结构化摘要
```

### 内容类型路由

系统先将视频分为 7 种类型，然后使用对应的结构化提示词：

| 类型 | 说明 | 输出结构 |
|------|------|----------|
| tutorial | 教程 | 步骤、前置条件、常见问题 |
| tech_talk | 技术演讲 | 核心论点、证据、展望 |
| demo | 产品演示 | 工作流、输入输出、优缺点 |
| review | 评测对比 | 对象、标准、推荐 |
| news | 新闻 | 事实、背景、观点 |
| vlog | 日常 | 场景、亮点 |
| general | 通用 | 核心内容、要点、分析 |

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查（无需认证） |
| `/api/summarize` | POST | 提交视频摘要 |
| `/api/summarize/batch` | POST | 批量提交 |
| `/api/summarize/group` | POST | 分组提交（含组合分析） |
| `/api/groups/{group_id}` | GET | 分组状态与合成结果 |
| `/api/tasks` | GET | 任务列表 |
| `/api/tasks/{id}` | GET | 任务详情 |
| `/api/tasks/{id}/status` | GET | 轻量状态轮询 |
| `/api/tasks/{id}/stream` | GET | SSE 流式输出 |
| `/api/tasks/{id}/metadata` | GET | 视频元数据 |
| `/api/tasks/{id}/transcript` | GET | 转录文本 |
| `/api/tasks/{id}/summary` | GET | 摘要内容 |
| `/api/tasks/{id}/frames` | GET | 帧图片列表 |
| `/api/tasks/{id}/frames/{filename}` | GET | 帧图片文件 |
| `/api/tasks/{id}/review-doc` | GET | 下载交互式 Review HTML |
| `/api/tasks/{id}/retry` | POST | 重试失败任务 |
| `/api/tasks/{id}/favorite` | PUT | 收藏/取消收藏 |
| `/api/tasks/{id}/evidence` | GET | 证据链 |
| `/api/tasks/{id}` | DELETE | 删除任务及关联文件 |
| `/api/storage` | GET | 存储信息 |
| `/api/storage` | DELETE | 清理数据（支持 `?older_than=7d`） |
| `/api/prompts` | GET | 列出所有提示词 |
| `/api/prompts/classify` | GET/PUT/DELETE | 分类提示词管理 |
| `/api/prompts/summary/{type}` | GET/PUT/DELETE | 摘要提示词管理 |
| `/api/settings/cookies` | GET/PUT | Bilibili Cookies 管理 |
| `/api/metrics` | GET | Prometheus 指标 |
| `/api/publish/status` | GET | GitHub Pages 发布状态 |
| `/api/publish` | POST | 发布 Review 到 GitHub Pages |
| `/api/publish/{task_id}` | DELETE | 下线已发布的 Review |

## 配置

环境变量（`.env`）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| **Server** | | |
| `HOST` | `127.0.0.1` | 监听地址 |
| `PORT` | `8000` | 监听端口 |
| `API_SECRET` | | API 认证密钥（留空则不校验） |
| **LLM** | | |
| `LLM_PROVIDER` | `openai` | LLM 提供商：`openai` / `claude` |
| `OPENAI_API_KEY` | | OpenAI / 兼容 API Key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API 端点 |
| `OPENAI_MODEL` | `gpt-4o` | 文本模型 |
| `OPENAI_VISION_MODEL` | | 视觉模型（留空则用 OPENAI_MODEL） |
| `ANTHROPIC_API_KEY` | | Claude API Key |
| `ANTHROPIC_BASE_URL` | | 自定义 Claude 端点 |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude 模型 |
| **ASR / Whisper** | | |
| `WHISPER_MODEL` | `medium` | Whisper 模型大小 |
| `WHISPER_BACKEND` | `faster` | 后端：`faster` / `openai` |
| `HF_ENDPOINT` | | HuggingFace 镜像（如 `https://hf-mirror.com`） |
| `ASR_PROVIDER` | `inprocess` | ASR 方式：`inprocess` / `local` / `openai` |
| `ASR_ENDPOINT` | | 本地 ASR 服务地址 |
| `ASR_API_KEY` | | 云端 ASR API Key |
| `ASR_MODEL` | `whisper-1` | 云端 ASR 模型名 |
| **帧提取** | | |
| `FRAME_MODE` | `interval` | 帧提取模式：`interval` / `scene` |
| `MAX_FRAMES` | `10` | 最大帧数 |
| `FRAME_INTERVAL` | `30` | 间隔秒数（interval 模式） |
| `SCENE_THRESHOLD` | `0.3` | 场景变化阈值（scene 模式） |
| `FRAME_FORMAT` | `webp` | 输出格式：`webp` / `jpg` / `png` |
| `FRAME_QUALITY` | `85` | 输出质量 1-100 |
| `FRAME_WIDTH` | `1280` | 最大宽度像素 |
| `MIN_GAP` | `5.0` | 场景帧最小间隔秒数 |
| `MAX_SCENE_PER_SEG` | `2` | 每段最大场景帧数 |
| `SEGMENTS` | `60` | 场景分析分段数 |
| **GitHub Pages** | | |
| `GITHUB_REPO` | | 仓库（如 `user/video-reviews`） |
| `GITHUB_TOKEN` | | GitHub PAT |
| `GITHUB_BRANCH` | `gh-pages` | 发布分支 |
| `GITHUB_PAGES_URL` | | 站点 URL |
| **存储** | | |
| `DATA_DIR` | `data` | 数据目录 |
| `AUTO_CLEANUP_DAYS` | `7` | 自动清理天数 |

完整示例见 [`.env.example`](.env.example)。

## Testing

```bash
uv run pytest
```

## Contributing

1. Fork 本仓库并创建功能分支
2. 确保 `uv run pytest` 全部通过
3. 提交 Pull Request，说明改动内容和原因

## 技术栈

- Python 3.10+, FastAPI, uv
- Whisper (ASR), yt-dlp (下载), ffmpeg (音视频处理)
- Claude / OpenAI 兼容 LLM
- SQLite (WAL 模式)

## 许可证

MIT License
