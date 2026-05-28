## ADDED Requirements

### Requirement: CI test pipeline
项目 SHALL 配置 GitHub Actions CI 流水线，在每次 push 和 PR 到 master 时自动运行测试。

#### Scenario: Push to master triggers tests
- **WHEN** 代码推送到 master 分支
- **THEN** GitHub Actions 自动触发测试工作流
- **AND** 在 Python 3.11 和 3.12 两个版本上并行执行
- **AND** 安装 ffmpeg 系统依赖
- **AND** 使用 `uv` 安装 Python 依赖
- **AND** 执行 `uv run pytest` 并输出覆盖率报告

#### Scenario: PR triggers tests
- **WHEN** 创建或更新 PR 目标为 master
- **THEN** GitHub Actions 自动触发测试工作流
- **AND** 测试结果显示在 PR 状态检查中

#### Scenario: Lint check
- **WHEN** CI 工作流执行
- **THEN** 运行 `uv run ruff check` 进行代码风格检查
- **AND** lint 失败时工作流状态为失败
