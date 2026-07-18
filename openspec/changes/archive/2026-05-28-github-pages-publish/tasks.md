## 1. Config

- [x] 1.1 Add `github_repo`, `github_token`, `github_branch`, `github_pages_url` to `core/config.py`
- [x] 1.2 Add `github_repo` and `data/github-repo/` to `.env` example and `ensure_dirs()`

## 2. Core Publisher Module

- [x] 2.1 Create `core/github/__init__.py`
- [x] 2.2 Implement `core/github/publisher.py` — `ensure_clone()`, `pull()`, `push()` using subprocess git
- [x] 2.3 Implement `publish_reviews(task_ids: list[str])` — generate HTML via existing `review_doc.py`, write to `reviews/{task_id}.html`, regenerate index, commit + push
- [x] 2.4 Implement `unpublish_review(task_id: str)` — delete file, regenerate index, commit + push
- [x] 2.5 Implement error handling: missing config returns clear error, push failure retries once after pull, batch skips failed tasks and returns both `published` and `failed` lists

## 3. Index.html Generator

- [x] 3.1 Implement `core/github/index_generator.py` — scan `reviews/` directory, collect metadata from task DB, render index.html with embedded JSON data
- [x] 3.2 Create `core/templates/github_index.html` — waterfall card layout, tag filter sidebar, no preview images, responsive
- [x] 3.3 Client-side JS: render cards from JSON, filter by tag click, show title/platform/date/tags/summary_preview per card

## 4. API Endpoints

- [x] 4.1 Add `POST /api/publish` to `core/api/routes.py` — accepts `{ task_ids: [...] }`, returns `{ published: [...], failed: [...] }`
- [x] 4.2 Add `DELETE /api/publish/{task_id}` — returns `{ removed: true }` or 404
- [x] 4.3 Add `GET /api/publish/status` — returns `{ repo_configured, published_count, pages_url }`
- [x] 4.4 Update task metadata on publish: set `publish_url` and `published_at`; on unpublish: remove them
- [x] 4.5 Validate tasks are status "done" before publishing; return 400 for non-done tasks

## 5. Web UI

- [x] 5.1 Add "Publish" button to task detail actions row in `core/web/index.html`
- [x] 5.2 Implement publish confirmation dialog — shows title, platform, tags, predicted URL, [取消]/[确认发布]
- [x] 5.3 Implement publish success feedback — show URL with [复制链接] and [打开] buttons
- [x] 5.4 Update button state for already-published tasks — show "已发布" with link and "取消发布" option
- [x] 5.5 Add "Published" column to history table — show "✓ {date}" or "-"
- [x] 5.6 Add checkbox column to history table + "批量发布"/"批量取消发布" buttons in section header
- [x] 5.7 Implement batch publish progress indicator — show completed/total count
- [x] 5.8 Add re-publish banner when `completed_at > published_at` — "内容已变更" with [重新发布]/[忽略]
- [x] 5.9 Show setup instructions when publish is clicked but config is missing

## 6. Skill/CLI Integration

- [x] 6.1 Add post-pipeline publish prompt in Skill interaction — show summary + "要发布到 GitHub Pages 吗？"
- [x] 6.2 Show predicted Pages URL in the prompt
- [x] 6.3 Skip prompt silently when GitHub is not configured

## 7. Tests

- [x] 7.1 Test `ensure_clone()` — clone on first call, pull on subsequent
- [x] 7.2 Test `publish_reviews()` — single and batch, verify files written and git commands called
- [x] 7.3 Test `unpublish_review()` — file deleted, index regenerated
- [x] 7.4 Test error handling — missing config, non-done task, push failure retry
- [x] 7.5 Test `index_generator` — correct JSON data, tag extraction from metadata
- [x] 7.6 Test API endpoints — publish, unpublish, status (mock git operations)
- [x] 7.7 Test metadata updates — publish_url/published_at set on publish, cleared on unpublish
