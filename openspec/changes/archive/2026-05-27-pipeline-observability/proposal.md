## Why

Pipeline 各阶段的日志散落在 `logger.info/warning` 中，出问题时无法回溯根因。转录 0 字符、scene 检测 0 帧、LLM 拒绝请求 — 这些问题发生时缺乏结构化的证据记录和指标统计，调试靠猜。

## What Changes

- **StageContext 上下文管理器**：每个 pipeline 阶段用 `with StageContext(task_id, "stage_name") as stage:` 包裹，自动记录输入输出、决策原因、耗时、异常
- **结构化 JSONL 日志**：每个任务一份 `data/logs/{task_id}.jsonl`，每行一个 stage event
- **证据链 DB 表**：新增 `evidence` 表存储关键 stage event，支持查询和审计
- **内存指标聚合**：`/api/metrics` 端点暴露各阶段耗时、成功率、降级率、空转录率等 Prometheus 格式指标
- **Pipeline 重构**：`run_pipeline()` 中所有阶段替换为 `StageContext` 包裹

## Capabilities

### New Capabilities
- `pipeline-observability`: 结构化日志 + 证据链 + 指标聚合，三者共享统一的 StageEvent 数据模型

### Modified Capabilities

## Impact

- **core/observability/**：新增模块（stage.py, logger.py, evidence.py, metrics.py）
- **core/pipeline.py**：重构为使用 StageContext
- **core/api/routes.py**：新增 `/api/metrics` 端点
- **core/storage/db.py**：新增 `evidence` 表
- **core/config.py**：新增 `log_dir` 配置项
