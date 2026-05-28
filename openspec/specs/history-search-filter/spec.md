## ADDED Requirements

### Requirement: Search tasks by title
前端 SHALL 支持在 history 表格中按标题搜索。

#### Scenario: Search input filters results
- **WHEN** 用户在搜索框输入文本
- **THEN** history 表格仅显示标题包含搜索文本的任务（不区分大小写）

#### Scenario: Clear search
- **WHEN** 用户清空搜索框
- **THEN** 显示所有任务

### Requirement: Filter tasks by platform
前端 SHALL 支持按平台筛选任务。

#### Scenario: Select platform filter
- **WHEN** 用户选择平台筛选（All/Bilibili/YouTube）
- **THEN** history 表格仅显示匹配平台的任务

### Requirement: Filter tasks by status
前端 SHALL 支持按状态筛选任务。

#### Scenario: Select status filter
- **WHEN** 用户选择状态筛选（All/Done/Failed/Processing）
- **THEN** history 表格仅显示匹配状态的任务

### Requirement: Filters combine with search
筛选条件 SHALL 与搜索文本联合生效。

#### Scenario: Combined filter and search
- **WHEN** 用户设置平台筛选为 "Bilibili" 且搜索文本为 "教程"
- **THEN** 仅显示平台为 Bilibili 且标题包含 "教程" 的任务
