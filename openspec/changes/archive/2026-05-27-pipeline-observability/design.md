## Context

当前 `core/pipeline.py` 使用 `MetricsTracker` 记录各阶段耗时，最终存入 task metadata。日志通过 `logging` 模块输出到 stdout，格式为非结构化的 INFO/WARNING 字符串。没有证据链记录，没有暴露可查询的指标。

`MetricsTracker` 的局限：只记录 duration 和少量 extra 字段，不记录输入参数、决策原因、异常上下文。

## Goals / Non-Goals

**Goals:**
- 统一的 StageEvent 数据模型，同时服务于日志、证据链、指标
- StageContext 上下文管理器，零侵入地包裹 pipeline 各阶段
- JSONL 日志文件，每任务独立，可离线分析
- `/api/metrics` 端点，暴露 Prometheus 格式指标
- 证据链 DB 表，支持按 task_id/stage 查询

**Non-Goals:**
- 不引入外部依赖（如 OpenTelemetry、Prometheus client）— 自实现轻量版
- 不做分布式追踪（单机部署，不需要跨服务关联）
- 不做日志采集/转发（文件即可，用户可自行接 ELK）
- 不替换现有 `logging` 模块 — 与其共存

## Decisions

### D1: StageContext 作为核心抽象

**选择**: 上下文管理器 `with StageContext(task_id, "stage_name") as stage:`

**理由**: 上下文管理器自动处理计时、异常捕获、资源清理。pipeline 代码只需在关键点调用 `stage.input()`, `stage.output()`, `stage.warning()`, `stage.decision()` 即可，不需要手动管理日志写入。

**替代方案**: 装饰器 — 不适合 pipeline 中的复杂控制流（并行、条件分支）。

### D2: 三写统一

**选择**: `StageContext.__exit__` 中同时写三个目标：JSONL 文件、DB evidence、内存 metrics。

**理由**: 统一写入点避免遗漏，保证三者数据一致。写入失败互相隔离（一个失败不影响其他）。

### D3: JSONL 而非结构化日志库

**选择**: 直接 `json.dumps` + `open().write()`，无外部依赖。

**理由**: JSONL 格式简单、可 grep、可 jq 分析、可直接导入 pandas。每任务独立文件，避免单文件过大。不需要 loguru/structlog 等额外依赖。

### D4: Metrics 自实现而非 Prometheus client

**选择**: 内存中的 `dict` 聚合，`/api/metrics` 端点输出 Prometheus text format。

**理由**: 指标数量少（<20 个），不值得引入 prometheus_client 依赖。自实现 Counter/Gauge/Histogram 足够。

### D5: Evidence 表设计

```sql
CREATE TABLE evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,        -- success/error/fallback
    input_summary TEXT,          -- JSON: 关键输入参数
    output_summary TEXT,         -- JSON: 关键输出结果
    decisions TEXT,              -- JSON: 决策列表
    warnings TEXT,               -- JSON: 警告列表
    duration_ms INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);
```

只存摘要，不存完整输入输出（如音频内容、完整 transcript）。保持表轻量。

## Risks / Trade-offs

- **[磁盘占用]** 每任务一个 JSONL 文件，长期运行会积累。→ 复用现有 auto_cleanup 机制，清理过期任务时一并删除日志文件。
- **[性能]** 每次 stage 结束写一次文件。→ 单次写入量小（<1KB），pipeline 瓶颈在 LLM/ASR，可忽略。
- **[DB 写入竞争]** 多任务并发时 evidence 表写入。→ 使用现有 `Storage._write_lock`，单写多读。
