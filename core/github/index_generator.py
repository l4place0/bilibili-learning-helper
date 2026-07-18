"""Generate index.html for GitHub Pages with waterfall layout and tag filtering."""

import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


def generate_index(repo_dir: Path, reviews: list[dict]) -> None:
    """Generate index.html from review metadata list."""
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("github_index.html")

    # Collect all unique tags
    all_tags = sorted({tag for r in reviews for tag in r.get("tags", [])})

    # Sort by date descending
    reviews_sorted = sorted(reviews, key=lambda r: r.get("date", ""), reverse=True)

    reviews_json_str = json.dumps(reviews_sorted, ensure_ascii=False)
    # Escape HTML-significant chars to prevent stored XSS via | safe filter
    reviews_json_str = reviews_json_str.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    html = template.render(
        reviews_json=reviews_json_str,
        reviews=reviews_sorted,
        all_tags=all_tags,
        review_count=len(reviews_sorted),
    )

    index_path = repo_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    logger.info("Generated index.html with %d reviews", len(reviews_sorted))
