## ADDED Requirements

### Requirement: Publish review to GitHub Pages
The system SHALL publish a task's review document as a self-contained HTML file to a configured GitHub repository, making it accessible via GitHub Pages.

#### Scenario: Single task publish
- **WHEN** `POST /api/publish` is called with a single task_id
- **THEN** the system generates the review HTML, writes it to `reviews/{task_id}.html` in the local repo clone, regenerates `index.html`, commits, and pushes to the configured branch

#### Scenario: Batch publish
- **WHEN** `POST /api/publish` is called with multiple task_ids
- **THEN** the system generates review HTML for each task, writes all files, regenerates `index.html`, makes a single commit, and pushes

#### Scenario: Publish with missing config
- **WHEN** `POST /api/publish` is called but `github_repo` or `github_token` is not configured
- **THEN** the system returns HTTP 400 with a clear error message indicating which settings are missing

### Requirement: Unpublish review
The system SHALL remove a published review from the GitHub repository.

#### Scenario: Unpublish a single task
- **WHEN** `DELETE /api/publish/{task_id}` is called
- **THEN** the system deletes `reviews/{task_id}.html` from the repo, regenerates `index.html`, commits, and pushes

#### Scenario: Unpublish a task that was never published
- **WHEN** `DELETE /api/publish/{task_id}` is called for a task with no `publish_url` in metadata
- **THEN** the system returns HTTP 404

### Requirement: Local repo management
The system SHALL manage a local shallow clone of the GitHub repository at `data/github-repo/`.

#### Scenario: First publish (no local clone)
- **WHEN** publish is triggered and `data/github-repo/` does not exist
- **THEN** the system performs `git clone --depth 1` of the configured repo

#### Scenario: Subsequent publish (clone exists)
- **WHEN** publish is triggered and `data/github-repo/` already exists
- **THEN** the system performs `git pull --rebase` before making changes

#### Scenario: Push failure retry
- **WHEN** `git push` fails due to remote being ahead
- **THEN** the system performs `git pull --rebase` and retries the push once

### Requirement: Index.html generation
The system SHALL auto-generate an `index.html` listing all published reviews.

#### Scenario: Index page content
- **WHEN** index.html is regenerated
- **THEN** it contains a JSON data block with all review metadata (id, title, platform, date, tags, summary_preview, url) and renders a waterfall card layout with client-side tag filtering

#### Scenario: Tag filtering
- **WHEN** a user clicks a tag filter on the index page
- **THEN** only reviews matching that tag are displayed

### Requirement: Publish status tracking
The system SHALL record publish status in task metadata.

#### Scenario: Successful publish updates metadata
- **WHEN** a task is successfully published
- **THEN** `metadata.publish_url` is set to the GitHub Pages URL and `metadata.published_at` is set to the current ISO timestamp

#### Scenario: Unpublish clears metadata
- **WHEN** a task is unpublished
- **THEN** `metadata.publish_url` and `metadata.published_at` are removed from task metadata

### Requirement: Publish status API
The system SHALL expose publish configuration status.

#### Scenario: Check publish status
- **WHEN** `GET /api/publish/status` is called
- **THEN** the system returns `{ repo_configured: bool, published_count: int, pages_url: string }`
