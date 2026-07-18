"""GitHub Pages publisher — manages local repo clone, HTML generation, and git operations."""

import logging
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.config import settings
from core.github.index_generator import generate_index
from core.storage.db import get_storage

logger = logging.getLogger(__name__)

_publish_lock = threading.Lock()


class PublishError(Exception):
    """Raised when publish operation fails."""


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in the given directory."""
    cmd = ["git", "-C", str(cwd)] + list(args)
    logger.info("git: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=_git_auth_env())
    if check and result.returncode != 0:
        logger.error("git failed: %s\nstderr: %s", result.stdout, result.stderr)
        raise PublishError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _validate_config() -> None:
    """Raise PublishError if GitHub config is incomplete."""
    missing = []
    if not settings.github_repo:
        missing.append("GITHUB_REPO")
    if not settings.github_token:
        missing.append("GITHUB_TOKEN")
    if not settings.github_pages_url:
        missing.append("GITHUB_PAGES_URL")
    if missing:
        raise PublishError(f"Missing GitHub config: {', '.join(missing)}. Set in .env")


def _clone_url() -> str:
    """Build standard clone URL (no token embedded)."""
    return f"https://github.com/{settings.github_repo}.git"


def _git_auth_env() -> dict[str, str]:
    """Return env dict with git http.extraHeader for token auth."""
    env = dict(os.environ)
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
    env["GIT_CONFIG_VALUE_0"] = f"Authorization: Bearer {settings.github_token}"
    return env


def ensure_clone() -> Path:
    """Ensure local clone exists on the correct branch. Returns repo path."""
    _validate_config()
    repo_dir = settings.github_repo_dir
    branch = settings.github_branch

    if (repo_dir / ".git").exists():
        # Check current branch, switch if needed
        result = _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD", check=False)
        current_branch = result.stdout.strip()
        if current_branch != branch:
            logger.info("Switching from %s to %s", current_branch, branch)
            _git(repo_dir, "fetch", "--depth", "1", "origin", branch)
            _git(repo_dir, "checkout", "-B", branch, f"origin/{branch}")
        return repo_dir

    logger.info("Cloning %s to %s", settings.github_repo, repo_dir)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", "-b", branch, _clone_url(), str(repo_dir)],
        capture_output=True, text=True, timeout=120, check=True, env=_git_auth_env(),
    )
    # Ensure reviews/ directory exists
    (repo_dir / "reviews").mkdir(exist_ok=True)
    return repo_dir


def pull(repo_dir: Path) -> None:
    """Pull latest changes."""
    _git(repo_dir, "pull", "--rebase", "origin", settings.github_branch)


def push(repo_dir: Path) -> None:
    """Push with one retry on failure."""
    result = _git(repo_dir, "push", "origin", settings.github_branch, check=False)
    if result.returncode != 0:
        logger.warning("Push failed, pulling and retrying...")
        pull(repo_dir)
        _git(repo_dir, "push", "origin", settings.github_branch)


def _generate_review_html(task: dict) -> str:
    """Generate self-contained review HTML for a task."""
    from core.review_doc import encode_frames, generate_review_doc, parse_review_cards

    cards = parse_review_cards(task.get("summary", ""))
    metadata = task.get("metadata") or {}
    duration = metadata.get("duration")
    frames = encode_frames(task["task_id"], duration=duration)
    return generate_review_doc(task, cards, frames)


def _build_review_metadata(task: dict) -> dict:
    """Extract metadata for index.html entry."""
    metadata = task.get("metadata") or {}
    title = metadata.get("title", "Untitled")
    platform = task.get("platform", "unknown")
    completed_at = task.get("completed_at", "")
    date = completed_at[:10] if completed_at else ""

    tags = []
    content_type = metadata.get("content_type")
    if content_type:
        tags.append(content_type)
    tags.extend(metadata.get("tags", []))

    summary = task.get("summary", "")
    # First 150 chars of summary as preview
    preview = summary[:150].replace("\n", " ").strip()
    if len(summary) > 150:
        preview += "..."

    def _escape_for_js(s: str) -> str:
        return s.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    return {
        "id": task["task_id"],
        "title": _escape_for_js(title),
        "platform": platform,
        "date": date,
        "tags": tags,
        "summary_preview": _escape_for_js(preview),
        "url": f"reviews/{task['task_id']}.html",
    }


def publish_reviews(task_ids: list[str]) -> dict:
    """Publish review docs for given tasks.

    Returns: { published: [{task_id, url}], failed: [{task_id, error}] }
    """
    with _publish_lock:
        return _publish_reviews_inner(task_ids)


def _publish_reviews_inner(task_ids: list[str]) -> dict:
    _validate_config()
    db = get_storage()

    repo_dir = ensure_clone()
    pull(repo_dir)

    published = []
    failed = []
    review_entries = []

    # Load existing index entries
    index_data_path = repo_dir / "reviews" / "_data.json"
    if index_data_path.exists():
        import json
        review_entries = json.loads(index_data_path.read_text(encoding="utf-8"))

    # Remove entries that will be re-published
    existing_ids = {e["id"] for e in review_entries}

    for task_id in task_ids:
        task = db.get_task(task_id)
        if not task:
            failed.append({"task_id": task_id, "error": "Task not found"})
            continue
        if task.get("status") != "done":
            failed.append({"task_id": task_id, "error": "Task is not completed"})
            continue

        try:
            html = _generate_review_html(task)
            html_path = repo_dir / "reviews" / f"{task_id}.html"
            html_path.write_text(html, encoding="utf-8")

            entry = _build_review_metadata(task)
            # Update or add entry
            if task_id in existing_ids:
                review_entries = [e for e in review_entries if e["id"] != task_id]
            review_entries.append(entry)

            # Update task metadata
            pages_url = f"{settings.github_pages_url.rstrip('/')}/reviews/{task_id}.html"
            metadata = task.get("metadata") or {}
            metadata["publish_url"] = pages_url
            metadata["published_at"] = datetime.now(timezone.utc).isoformat()
            db.update_task(task_id, metadata=metadata)

            published.append({"task_id": task_id, "url": pages_url})
            logger.info("Published %s -> %s", task_id[:8], pages_url)
        except Exception as e:
            failed.append({"task_id": task_id, "error": str(e)})
            logger.error("Failed to publish %s: %s", task_id[:8], e)

    if published:
        # Save index data and generate index.html
        import json
        index_data_path.write_text(json.dumps(review_entries, ensure_ascii=False, indent=2), encoding="utf-8")
        generate_index(repo_dir, review_entries)

        _git(repo_dir, "add", "-A")
        count = len(published)
        _git(repo_dir, "commit", "-m", f"publish: {count} review{'s' if count > 1 else ''}")
        push(repo_dir)

    return {"published": published, "failed": failed}


def unpublish_review(task_id: str) -> dict:
    """Remove a published review from GitHub Pages.

    Returns: { removed: bool, pages_url: str }
    """
    with _publish_lock:
        return _unpublish_review_inner(task_id)


def _unpublish_review_inner(task_id: str) -> dict:
    _validate_config()
    db = get_storage()

    task = db.get_task(task_id)
    if not task:
        raise PublishError("Task not found")

    metadata = task.get("metadata") or {}
    if not metadata.get("publish_url"):
        raise PublishError("Task was never published")

    repo_dir = ensure_clone()
    pull(repo_dir)

    # Remove HTML file
    html_path = repo_dir / "reviews" / f"{task_id}.html"
    if html_path.exists():
        html_path.unlink()

    # Update index data
    import json
    index_data_path = repo_dir / "reviews" / "_data.json"
    review_entries = []
    if index_data_path.exists():
        review_entries = json.loads(index_data_path.read_text(encoding="utf-8"))
    review_entries = [e for e in review_entries if e["id"] != task_id]
    index_data_path.write_text(json.dumps(review_entries, ensure_ascii=False, indent=2), encoding="utf-8")

    generate_index(repo_dir, review_entries)

    # Clear publish metadata
    del metadata["publish_url"]
    del metadata["published_at"]
    db.update_task(task_id, metadata=metadata)

    _git(repo_dir, "add", "-A")
    _git(repo_dir, "commit", "-m", f"unpublish: {task_id[:8]}")
    push(repo_dir)

    pages_url = f"{settings.github_pages_url.rstrip('/')}/"
    return {"removed": True, "pages_url": pages_url}


def get_publish_status() -> dict:
    """Return publish configuration status."""
    return {
        "repo_configured": bool(settings.github_repo and settings.github_token),
        "pages_url": settings.github_pages_url,
    }


def get_publish_preview(task_id: str) -> dict | None:
    """Return publish preview info for a task, or None if GitHub not configured.

    Used by Skill/CLI to show the user what will be published.
    """
    if not settings.github_repo or not settings.github_token:
        return None

    db = get_storage()
    task = db.get_task(task_id)
    if not task or task.get("status") != "done":
        return None

    metadata = task.get("metadata") or {}
    pages_url = f"{settings.github_pages_url.rstrip('/')}/reviews/{task_id}.html"

    return {
        "task_id": task_id,
        "title": metadata.get("title", "Untitled"),
        "platform": task.get("platform", "unknown"),
        "tags": metadata.get("tags", []),
        "content_type": metadata.get("content_type", ""),
        "summary_preview": (task.get("summary", "") or "")[:200],
        "pages_url": pages_url,
    }
