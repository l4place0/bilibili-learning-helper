## Context

Video summaries are generated and stored locally. Users want to share them publicly via GitHub Pages. The existing `review_doc.py` already generates self-contained HTML documents with embedded images, transcript, and review cards. This change adds a publish pipeline: generate HTML → commit to a GitHub repo → serve via GitHub Pages.

## Goals / Non-Goals

**Goals:**
- Publish review docs to GitHub Pages with a single click or CLI command
- Support batch publish and unpublish
- Auto-generate an index.html with waterfall layout and tag filtering
- Track publish status in task metadata
- Prompt users to re-publish when content changes after previous publish

**Non-Goals:**
- Custom domain support (v1)
- GitHub Actions-based build pipeline (direct git push is sufficient)
- Multi-user conflict handling (personal tool)
- Real-time Pages build status monitoring (poll with long interval)
- Image optimization or CDN (base64-embedded is fine for personal use)

## Decisions

### 1. Local git clone vs GitHub Contents API

**Decision:** Local git clone in `data/github-repo/`.

**Rationale:**
- Batch publish needs to write multiple files + regenerate index.html — single commit is cleaner
- Can generate and validate index.html locally before pushing
- Consistent with existing git-based tooling
- Contents API would require multiple HTTP calls per file, rate limit concerns

**Alternative considered:** GitHub Contents API — simpler (no local git dependency), but batch operations are awkward and index.html regeneration requires read-modify-write across API calls.

### 2. Authentication via Personal Access Token (PAT)

**Decision:** Store `GITHUB_TOKEN` in `.env` (same pattern as `OPENAI_API_KEY`).

**Rationale:**
- Personal tool, single user
- PAT with `repo` scope is sufficient
- `.env` already in `.gitignore`

### 3. Index.html data embedding strategy

**Decision:** Embed review metadata as a JSON array in a `<script>` tag in index.html. Client-side JS renders cards and filters by tags.

**Rationale:**
- Pure static site, no server needed
- Tag filtering is client-side, instant
- Regenerating index.html from the reviews/ directory is straightforward
- Tags sourced from `metadata.content_type` + `metadata.tags` (video platform tags)

### 4. Git operations via subprocess

**Decision:** Use `subprocess.run(["git", ...])` for git operations, not `gitpython` library.

**Rationale:**
- Avoids new dependency
- Git commands needed are simple: clone, pull, add, commit, push
- Easier to debug (visible in logs)

### 5. Publish status tracking

**Decision:** Store `publish_url` and `published_at` in task metadata dict.

**Rationale:**
- No schema migration needed (metadata is a JSON column)
- Naturally included in task API responses
- Can detect "content changed after publish" by comparing `completed_at` vs `published_at`

### 6. Error handling for batch publish

**Decision:** Skip failed tasks, continue with rest. Return both `published` and `failed` lists.

**Rationale:**
- One bad task shouldn't block the entire batch
- User can retry failed tasks individually

## Risks / Trade-offs

- **[GitHub Pages build delay]** → Publish returns immediately; UI shows "构建中..." with a poll link. Non-blocking.
- **[Local repo disk usage]** → Shallow clone (`--depth 1`) minimizes footprint. Reviews are small HTML files.
- **[Token security]** → Same risk as existing API keys in `.env`. Document that PAT should have minimal scopes (repo only).
- **[Large HTML files]** → 60 base64-embedded frames ≈ 3-6MB per file. GitHub supports up to 100MB per file, so fine for personal use.
- **[Git not installed]** → Publish endpoint returns clear error if git is not available.
