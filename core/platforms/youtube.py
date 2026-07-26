import re
import logging

from core.platforms.base import YtdlpPlatform

logger = logging.getLogger(__name__)

_YOUTUBE_PATTERNS = [
    re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([\w-]{11})"),
]


class YouTubePlatform(YtdlpPlatform):
    def match(self, url: str) -> bool:
        return any(p.search(url) for p in _YOUTUBE_PATTERNS)

    def parse_url(self, url: str) -> str:
        for p in _YOUTUBE_PATTERNS:
            m = p.search(url)
            if m:
                return m.group(1)
        raise ValueError(f"Invalid YouTube URL: {url}")
