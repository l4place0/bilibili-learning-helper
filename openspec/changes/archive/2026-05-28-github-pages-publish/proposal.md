## Why

Video summaries are currently only viewable through the local web UI. Users need a way to publish review documents to the web for sharing and archiving. GitHub Pages provides a free, zero-infrastructure solution — publish self-contained HTML review docs to a GitHub repo and serve them via GitHub Pages.

## What Changes

- New `core/github/` module: publisher logic (local git clone, HTML generation, commit + push, index.html regeneration)
- New API endpoints: `POST /api/publish` (batch publish), `DELETE /api/publish/{task_id}` (unpublish), `GET /api/publish/status`
- Web UI: "Publish" button on task detail, publish status column in History table, batch publish controls, confirmation dialogs, progress feedback
- Skill/CLI: AI prompts user to publish after pipeline completes, with preview link
- Config: `github_repo`, `github_token`, `github_branch`, `github_pages_url` in `.env`
- Auto-generated `index.html`: waterfall layout, tag filtering, no preview images

## Capabilities

### New Capabilities
- `github-publish`: Core publish/unpublish logic — git clone management, HTML generation, index.html regeneration, batch operations, error handling
- `publish-ui`: Web UI integration — publish button, status indicators, batch selection, confirmation dialogs, progress feedback, re-publish prompts
- `publish-skill`: Skill/CLI integration — post-pipeline publish prompt with preview link

### Modified Capabilities

## Impact

- **New code**: `core/github/` module (publisher.py, index_generator.py), new API routes, JS frontend changes
- **Config**: 4 new settings in `config.py` / `.env`
- **Dependencies**: `gitpython` or shell git commands (for local repo operations), `jinja2` (already present)
- **Storage**: `data/github-repo/` local clone directory, `metadata.publish_url` / `metadata.published_at` in task records
- **External**: Requires user to create a GitHub repo and enable GitHub Pages, plus a PAT with repo scope
