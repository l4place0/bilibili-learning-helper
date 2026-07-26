"""Platform adapters for video capture."""

from core.platforms.base import BasePlatform
from core.platforms.bilibili import BilibiliPlatform
from core.platforms.youtube import YouTubePlatform


PLATFORMS: list[BasePlatform] = [
    BilibiliPlatform(),
    YouTubePlatform(),
]


def get_platform(url: str) -> BasePlatform:
    """Resolve a supported video platform without importing task infrastructure."""
    for platform in PLATFORMS:
        if platform.match(url):
            return platform
    raise ValueError(f"Unsupported URL: no platform matched for {url}")
