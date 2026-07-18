"""Tests for GitHub Pages publish functionality."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_settings():
    """Mock settings with GitHub config."""
    with patch("core.github.publisher.settings") as mock:
        mock.github_repo = "user/video-reviews"
        mock.github_token = "ghp_test123"
        mock.github_branch = "main"
        mock.github_pages_url = "https://user.github.io/video-reviews"
        mock.github_repo_dir = Path(tempfile.mkdtemp()) / "github-repo"
        yield mock


@pytest.fixture
def repo_dir(mock_settings):
    """Create a fake repo directory with git initialized."""
    repo = mock_settings.github_repo_dir
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "reviews").mkdir()
    return repo


class TestEnsureClone:
    def test_clone_on_first_call(self, mock_settings):
        """Clones repo when directory doesn't exist."""
        from core.github.publisher import ensure_clone

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            # Create the directory structure as clone would
            def side_effect(cmd, **kwargs):
                repo_dir = Path(cmd[-1])
                repo_dir.mkdir(parents=True, exist_ok=True)
                (repo_dir / ".git").mkdir(exist_ok=True)
                (repo_dir / "reviews").mkdir(exist_ok=True)
                return MagicMock(returncode=0)
            mock_run.side_effect = side_effect

            result = ensure_clone()
            assert result == mock_settings.github_repo_dir
            assert mock_run.called
            # Verify clone command
            call_args = mock_run.call_args[0][0]
            assert "clone" in call_args
            assert "--depth" in call_args

    def test_pull_on_subsequent_call(self, repo_dir, mock_settings):
        """Pulls when clone already exists."""
        from core.github.publisher import ensure_clone

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = ensure_clone()
            assert result == repo_dir


class TestPublishReviews:
    def test_publish_single_task(self, repo_dir, mock_settings):
        """Publishes a single task successfully."""
        from core.github.publisher import publish_reviews

        mock_task = {
            "task_id": "abc123",
            "status": "done",
            "platform": "bilibili",
            "summary": "## 核心内容\nTest summary",
            "transcript": "[00:00] Hello",
            "metadata": {"title": "Test Video", "tags": ["test"], "content_type": "general"},
            "completed_at": "2026-05-27T10:00:00Z",
        }

        with patch("core.github.publisher.get_storage") as mock_db, \
             patch("core.github.publisher._generate_review_html", return_value="<html>test</html>"), \
             patch("core.github.publisher.generate_index") as mock_gen_index, \
             patch("core.github.publisher._git") as mock_git:

            mock_storage = MagicMock()
            mock_storage.get_task.return_value = mock_task
            mock_db.return_value = mock_storage

            result = publish_reviews(["abc123"])

            assert len(result["published"]) == 1
            assert result["published"][0]["task_id"] == "abc123"
            assert len(result["failed"]) == 0

            # Verify HTML file written
            html_path = repo_dir / "reviews" / "abc123.html"
            assert html_path.exists()

            # Verify index data saved
            data_path = repo_dir / "reviews" / "_data.json"
            assert data_path.exists()

    def test_publish_batch(self, repo_dir, mock_settings):
        """Publishes multiple tasks in a single commit."""
        from core.github.publisher import publish_reviews

        tasks = {
            "a": {"task_id": "a", "status": "done", "platform": "yt", "summary": "s", "transcript": "", "metadata": {"title": "A"}, "completed_at": "2026-05-27"},
            "b": {"task_id": "b", "status": "done", "platform": "yt", "summary": "s", "transcript": "", "metadata": {"title": "B"}, "completed_at": "2026-05-27"},
        }

        with patch("core.github.publisher.get_storage") as mock_db, \
             patch("core.github.publisher._generate_review_html", return_value="<html>"), \
             patch("core.github.publisher.generate_index"), \
             patch("core.github.publisher._git"):

            mock_storage = MagicMock()
            mock_storage.get_task.side_effect = lambda tid: tasks.get(tid)
            mock_db.return_value = mock_storage

            result = publish_reviews(["a", "b"])

            assert len(result["published"]) == 2
            assert len(result["failed"]) == 0

    def test_publish_skips_non_done(self, repo_dir, mock_settings):
        """Skips tasks that are not done."""
        from core.github.publisher import publish_reviews

        mock_task = {"task_id": "abc", "status": "failed"}

        with patch("core.github.publisher.get_storage") as mock_db, \
             patch("core.github.publisher._git"):
            mock_storage = MagicMock()
            mock_storage.get_task.return_value = mock_task
            mock_db.return_value = mock_storage

            result = publish_reviews(["abc"])

            assert len(result["published"]) == 0
            assert len(result["failed"]) == 1
            assert "not completed" in result["failed"][0]["error"]


class TestUnpublishReview:
    def test_unpublish(self, repo_dir, mock_settings):
        """Removes a published review."""
        from core.github.publisher import unpublish_review

        # Create a fake review file
        html_path = repo_dir / "reviews" / "abc123.html"
        html_path.write_text("<html>test</html>")

        mock_task = {
            "task_id": "abc123",
            "metadata": {"publish_url": "https://example.com/reviews/abc123.html", "published_at": "2026-05-27"},
        }

        with patch("core.github.publisher.get_storage") as mock_db, \
             patch("core.github.publisher.generate_index"), \
             patch("core.github.publisher._git"):

            mock_storage = MagicMock()
            mock_storage.get_task.return_value = mock_task
            mock_db.return_value = mock_storage

            result = unpublish_review("abc123")

            assert result["removed"] is True
            assert not html_path.exists()

    def test_unpublish_not_published(self, mock_settings):
        """Raises error for task that was never published."""
        from core.github.publisher import PublishError, unpublish_review

        mock_task = {"task_id": "abc", "metadata": {}}

        with patch("core.github.publisher.get_storage") as mock_db:
            mock_storage = MagicMock()
            mock_storage.get_task.return_value = mock_task
            mock_db.return_value = mock_storage

            with pytest.raises(PublishError, match="never published"):
                unpublish_review("abc")


class TestErrorHandling:
    def test_missing_config(self, mock_settings):
        """Raises clear error when config is missing."""
        from core.github.publisher import PublishError, _validate_config

        mock_settings.github_repo = ""

        with pytest.raises(PublishError, match="Missing GitHub config"):
            _validate_config()


class TestIndexGenerator:
    def test_generates_index(self, repo_dir):
        """Generates index.html with correct data."""
        from core.github.index_generator import generate_index

        reviews = [
            {"id": "a", "title": "Video A", "platform": "bilibili", "date": "2026-05-27",
             "tags": ["general", "test"], "summary_preview": "Preview A", "url": "reviews/a.html"},
            {"id": "b", "title": "Video B", "platform": "youtube", "date": "2026-05-26",
             "tags": ["tutorial"], "summary_preview": "Preview B", "url": "reviews/b.html"},
        ]

        generate_index(repo_dir, reviews)

        index_path = repo_dir / "index.html"
        assert index_path.exists()
        content = index_path.read_text()
        assert "Video A" in content
        assert "Video B" in content
        assert "general" in content
        assert "tutorial" in content


class TestMetadataUpdates:
    def test_publish_sets_metadata(self, repo_dir, mock_settings):
        """Publish updates task metadata with publish_url and published_at."""
        from core.github.publisher import publish_reviews

        mock_task = {
            "task_id": "abc",
            "status": "done",
            "platform": "yt",
            "summary": "s",
            "transcript": "",
            "metadata": {"title": "T"},
            "completed_at": "2026-05-27",
        }

        with patch("core.github.publisher.get_storage") as mock_db, \
             patch("core.github.publisher._generate_review_html", return_value="<html>"), \
             patch("core.github.publisher.generate_index"), \
             patch("core.github.publisher._git"):

            mock_storage = MagicMock()
            mock_storage.get_task.return_value = mock_task
            mock_db.return_value = mock_storage

            publish_reviews(["abc"])

            # Verify update_task was called with publish metadata
            call_args = mock_storage.update_task.call_args
            meta = call_args[1]["metadata"] if "metadata" in call_args[1] else call_args[0][1]
            assert "publish_url" in meta
            assert "published_at" in meta

    def test_unpublish_clears_metadata(self, repo_dir, mock_settings):
        """Unpublish removes publish metadata from task."""
        from core.github.publisher import unpublish_review

        (repo_dir / "reviews" / "abc.html").write_text("<html>")

        mock_task = {
            "task_id": "abc",
            "metadata": {"publish_url": "https://...", "published_at": "2026-05-27", "title": "T"},
        }

        with patch("core.github.publisher.get_storage") as mock_db, \
             patch("core.github.publisher.generate_index"), \
             patch("core.github.publisher._git"):

            mock_storage = MagicMock()
            mock_storage.get_task.return_value = mock_task
            mock_db.return_value = mock_storage

            unpublish_review("abc")

            call_args = mock_storage.update_task.call_args
            meta = call_args[1]["metadata"] if "metadata" in call_args[1] else call_args[0][1]
            assert "publish_url" not in meta
            assert "published_at" not in meta
