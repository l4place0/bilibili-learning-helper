## ADDED Requirements

### Requirement: Post-pipeline publish prompt
The Skill/CLI SHALL prompt the user to publish after a pipeline completes successfully.

#### Scenario: Pipeline completes successfully
- **WHEN** a pipeline run finishes with status "done" and GitHub is configured
- **THEN** the AI displays a summary of the result (title, platform, tags, summary preview) and asks: "要发布到 GitHub Pages 吗？" with [发布] / [跳过] options

#### Scenario: User chooses to publish
- **WHEN** user selects "发布"
- **THEN** the system calls the publish API and returns the published URL to the user

#### Scenario: User chooses to skip
- **WHEN** user selects "跳过"
- **THEN** no publish action is taken

#### Scenario: GitHub not configured
- **WHEN** a pipeline completes but `github_repo` or `github_token` is empty
- **THEN** the publish prompt is skipped silently (no error, no prompt)

### Requirement: Publish preview link
The Skill SHALL show the expected GitHub Pages URL before publishing.

#### Scenario: Preview URL display
- **WHEN** the publish prompt is shown
- **THEN** the expected URL is displayed: "发布后链接: {pages_url}/reviews/{task_id}.html"
