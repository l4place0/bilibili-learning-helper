## ADDED Requirements

### Requirement: Update cookies via API
系统 SHALL 提供 API 端点更新 cookies。

#### Scenario: Update cookies via PUT
- **WHEN** PUT `/api/settings/cookies` 带 cookies 内容
- **THEN** cookies 文件被更新
- **AND** 返回更新后的状态

#### Scenario: Invalid cookies format
- **WHEN** PUT `/api/settings/cookies` 带无效格式
- **THEN** 返回 400 错误

### Requirement: Update cookies via WebUI
系统 SHALL 在 WebUI 提供 cookies 管理界面。

#### Scenario: View cookies status
- **WHEN** 用户打开 Settings 页面
- **THEN** 显示当前 cookies 状态

#### Scenario: Paste new cookies
- **WHEN** 用户在文本框粘贴 cookies 并点击保存
- **THEN** cookies 被更新并显示新状态

### Requirement: Update cookies via Skill
系统 SHALL 提供脚本更新 cookies。

#### Scenario: Update via stdin
- **WHEN** 用户运行 `bash skill/scripts/update-cookies.sh` 并输入 cookies
- **THEN** cookies 文件被更新
