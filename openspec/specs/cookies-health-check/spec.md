## ADDED Requirements

### Requirement: Cookies validity check
系统 SHALL 检测 Bilibili cookies 是否有效。

#### Scenario: Cookies are valid
- **WHEN** 系统检查 cookies 状态
- **AND** cookies 文件存在且有效
- **THEN** 返回 status="valid"

#### Scenario: Cookies are expired
- **WHEN** 系统检查 cookies 状态
- **AND** cookies 请求返回 403
- **THEN** 返回 status="expired"

#### Scenario: No cookies file
- **WHEN** 系统检查 cookies 状态
- **AND** cookies 文件不存在
- **THEN** 返回 status="not_configured"

### Requirement: Cookies status in status command
系统 SHALL 在 status 命令中显示 cookies 状态。

#### Scenario: Status shows cookies info
- **WHEN** 用户运行 `bash skill/scripts/status.sh`
- **THEN** 显示 Bilibili cookies 状态（有效/过期/未配置）
