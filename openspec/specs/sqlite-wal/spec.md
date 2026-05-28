## ADDED Requirements

### Requirement: Enable SQLite WAL mode
系统 SHALL 在数据库初始化时启用 WAL (Write-Ahead Logging) 模式。

#### Scenario: WAL mode on startup
- **WHEN** Storage 实例初始化
- **THEN** 执行 `PRAGMA journal_mode=WAL`
- **AND** 后续数据库操作使用 WAL 模式

#### Scenario: Concurrent read and write
- **WHEN** 一个线程正在写入（pipeline 更新任务状态）
- **AND** 另一个线程正在读取（前端轮询任务状态）
- **THEN** 读操作不被阻塞，不返回 "database is locked" 错误
