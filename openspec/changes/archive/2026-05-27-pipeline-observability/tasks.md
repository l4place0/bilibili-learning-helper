## 1. Infrastructure

- [x] 1.1 新增 `core/observability/` 模块目录（`__init__.py`）
- [x] 1.2 实现 `core/observability/stage.py` — `StageContext` 上下文管理器，支持 `input()`, `output()`, `warning()`, `decision()` API
- [x] 1.3 实现 `core/observability/logger.py` — JSONL 日志写入器，`data/logs/{task_id}.jsonl`
- [x] 1.4 实现 `core/observability/evidence.py` — evidence 表写入（CREATE TABLE IF NOT EXISTS + INSERT）
- [x] 1.5 实现 `core/observability/metrics.py` — 内存 Counter/Gauge/Histogram 聚合 + Prometheus text format 输出

## 2. Config

- [x] 2.1 `core/config.py` 新增 `log_dir` 配置项（default `data/logs`），在 `ensure_dirs()` 中创建

## 3. Pipeline Refactor

- [x] 3.1 重构 `core/pipeline.py` — 用 `StageContext` 替换 `MetricsTracker`，包裹 download, transcribe, extract_frames, classify, summarize 各阶段
- [x] 3.2 记录关键决策：ASR backend 选择、LLM provider、帧提取模式、内容分类结果、multimodal 降级原因
- [x] 3.3 记录空转录警告（text_length == 0）
- [x] 3.4 保留 metrics 写入 task metadata 的现有行为（向后兼容）

## 4. API

- [x] 4.1 `core/api/routes.py` 新增 `GET /api/metrics` 端点，返回 Prometheus text format
- [x] 4.2 新增 `GET /api/tasks/{task_id}/evidence` 端点，返回该任务的证据链

## 5. Storage

- [x] 5.1 evidence 表由 `core/observability/evidence.py` 自动创建（CREATE TABLE IF NOT EXISTS），无需改 db.py

## 6. Tests

- [x] 6.1 测试 StageContext — 正常执行记录 input/output/duration
- [x] 6.2 测试 StageContext — 异常时记录 error status
- [x] 6.3 测试 JSONL 写入 — 文件创建、格式正确、多 stage 写入
- [x] 6.4 测试 evidence 表 — 写入和查询
- [x] 6.5 测试 metrics — Counter/Histogram 递增正确
- [x] 6.6 测试 metrics_text() Prometheus 格式输出
