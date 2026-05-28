## ADDED Requirements

### Requirement: StageContext captures structured stage events
系统 SHALL 提供 `StageContext` 上下文管理器，自动记录每个 pipeline 阶段的输入输出、决策、警告、耗时和异常。

#### Scenario: Normal stage execution
- **WHEN** 一个 pipeline 阶段在 `StageContext` 内正常执行
- **THEN** 自动记录 `started_at`, `duration_ms`, `status=success`
- **AND** 记录通过 `stage.input()` 和 `stage.output()` 设置的摘要

#### Scenario: Stage raises exception
- **WHEN** 一个 pipeline 阶段在 `StageContext` 内抛出异常
- **THEN** 自动记录 `status=error` 和异常类型+消息
- **AND** 异常继续向上抛出，不被吞掉

#### Scenario: Stage records decision
- **WHEN** 代码调用 `stage.decision(key, value, reason)`
- **THEN** 决策记录包含在 stage event 的 `decisions` 列表中

### Requirement: JSONL per-task log files
系统 SHALL 为每个任务写入独立的 JSONL 日志文件 `data/logs/{task_id}.jsonl`。

#### Scenario: Log file created on first stage
- **WHEN** 任务的第一个 StageContext 开始执行
- **THEN** 创建 `data/logs/{task_id}.jsonl` 文件
- **AND** 每个 stage event 作为一行 JSON 写入

#### Scenario: Log file cleanup
- **WHEN** auto_cleanup 删除过期任务
- **THEN** 对应的 JSONL 日志文件一并删除

### Requirement: Evidence table for audit trail
系统 SHALL 在 SQLite 中新增 `evidence` 表，存储关键 stage event 的摘要。

#### Scenario: Evidence written on stage completion
- **WHEN** StageContext 正常结束（成功或失败）
- **THEN** 在 evidence 表插入一行，包含 task_id, stage, status, input_summary, output_summary, decisions, warnings, duration_ms

#### Scenario: Query evidence by task_id
- **WHEN** 查询某个任务的证据链
- **THEN** 返回该任务所有 stage event，按创建时间排序

### Requirement: Prometheus-compatible metrics endpoint
系统 SHALL 暴露 `/api/metrics` 端点，输出 Prometheus text format 的指标。

#### Scenario: Pipeline stage metrics
- **WHEN** pipeline 执行完成
- **THEN** 更新以下指标：
  - `pipeline_stage_duration_seconds` (histogram, label: stage)
  - `pipeline_stage_total` (counter, label: stage, status)
  - `pipeline_transcribe_empty_total` (counter)
  - `pipeline_llm_fallback_total` (counter)

#### Scenario: Scrape metrics endpoint
- **WHEN** GET /api/metrics
- **THEN** 返回 200，Content-Type 为 text/plain，body 为 Prometheus text format
