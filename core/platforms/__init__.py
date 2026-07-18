"""Platform adapters for video download and URL construction."""


def build_video_url(platform: str, video_id: str, time_seconds: int = 0) -> str | None:
    """Build an external video URL with optional timestamp.

    Args:
        platform: Platform name (youtube, bilibili, etc.)
        video_id: Video identifier
        time_seconds: Timestamp in seconds

    Returns:
        URL string, or None if platform is unknown.
    """
    if platform == "youtube":
        url = f"https://youtube.com/watch?v={video_id}"
        if time_seconds > 0:
            url += f"&t={time_seconds}"
        return url
    elif platform == "bilibili":
        url = f"https://bilibili.com/video/{video_id}"
        if time_seconds > 0:
            url += f"?t={time_seconds}"
        return url
    return None
