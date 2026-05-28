## ADDED Requirements

### Requirement: Publish button on task detail
The system SHALL display a "Publish" button on the task detail view when the task status is "done".

#### Scenario: Button visibility
- **WHEN** a completed task is displayed in the result section
- **THEN** a "Publish" button appears alongside existing actions (Export Markdown, Review Doc, etc.)

#### Scenario: Already published task
- **WHEN** a completed task has `publish_url` in metadata
- **THEN** the button changes to show "已发布" with a link to the published page and a "取消发布" option

### Requirement: Publish confirmation dialog
The system SHALL show a confirmation dialog before publishing.

#### Scenario: Confirmation dialog content
- **WHEN** user clicks "Publish"
- **THEN** a dialog shows the task title, platform, tags, the predicted Pages URL, and [取消] / [确认发布] buttons

#### Scenario: Confirm publish
- **WHEN** user clicks "确认发布"
- **THEN** the system calls `POST /api/publish`, shows a loading state, and on success displays the published URL with [复制链接] and [打开] buttons

#### Scenario: Cancel publish
- **WHEN** user clicks "取消"
- **THEN** the dialog closes without action

### Requirement: Publish status in history table
The system SHALL display publish status in the task history table.

#### Scenario: Published task indicator
- **WHEN** the history table renders a task with `publish_url` in metadata
- **THEN** a "✓ 已发布" indicator appears in a "Published" column with the publish date

#### Scenario: Unpublished task indicator
- **WHEN** the history table renders a task without `publish_url`
- **THEN** a "-" appears in the "Published" column

### Requirement: Batch publish from history
The system SHALL support batch publish and unpublish from the history page.

#### Scenario: Select tasks for batch publish
- **WHEN** user selects multiple tasks via checkboxes in the history table
- **THEN** a "批量发布" action button appears in the section header

#### Scenario: Batch publish execution
- **WHEN** user clicks "批量发布"
- **THEN** the system calls `POST /api/publish` with all selected task_ids, shows a progress indicator with completed/total count, and displays results (published + failed) on completion

#### Scenario: Batch unpublish
- **WHEN** user selects published tasks and clicks "批量取消发布"
- **THEN** the system calls `DELETE /api/publish/{task_id}` for each, with the same progress feedback

### Requirement: Re-publish prompt on content change
The system SHALL prompt users to re-publish when a published task's content changes.

#### Scenario: Content changed after publish
- **WHEN** a task has `publish_url` in metadata AND `completed_at` is later than `published_at`
- **THEN** a banner appears: "内容已变更，上次发布: {date}" with [重新发布] and [忽略] buttons

### Requirement: First-time setup guidance
The system SHALL guide users when GitHub is not configured.

#### Scenario: Publish button clicked without config
- **WHEN** user clicks "Publish" but `github_repo` or `github_token` is empty
- **THEN** the dialog shows setup instructions: "请先在 .env 中配置 GITHUB_REPO, GITHUB_TOKEN, GITHUB_PAGES_URL"
