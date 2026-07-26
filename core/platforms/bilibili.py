import re
import logging
from pathlib import Path

import httpx
import yt_dlp

from core.platforms.base import YtdlpPlatform

logger = logging.getLogger(__name__)

_BILIBILI_PATTERN = re.compile(r"bilibili\.com/video/(BV[\w]+)")
_TEST_VIDEO_ID = "BV1GJ411x7h7"  # Stable public test video


class BilibiliPlatform(YtdlpPlatform):
    _API_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
    }

    def match(self, url: str) -> bool:
        return bool(_BILIBILI_PATTERN.search(url))

    def parse_url(self, url: str) -> str:
        m = _BILIBILI_PATTERN.search(url)
        if not m:
            raise ValueError(f"Invalid Bilibili URL: {url}")
        return m.group(1)

    def _get_ydl_opts(self, output_path: Path) -> dict:
        opts = super()._get_ydl_opts(output_path)
        from core.config import settings
        if settings.cookies_path.is_file():
            opts["cookiefile"] = str(settings.cookies_path)
        return opts

    def download(self, url: str, output_dir: Path, keep_video: bool = False):
        """Download public Bilibili DASH streams via the stable public API.

        yt-dlp is retained as a fallback for cookie-protected or future API
        variants. The public API avoids the HTTP 412 response frequently
        returned to yt-dlp metadata requests from local/CI networks.
        """
        try:
            return self._download_public_api(url, output_dir, keep_video)
        except Exception as exc:
            logger.warning(
                "Bilibili public API download failed (%s); falling back to yt-dlp",
                exc,
            )
            return super().download(url, output_dir, keep_video)

    def _download_public_api(
        self, url: str, output_dir: Path, keep_video: bool
    ) -> tuple[Path, dict, Path | None]:
        video_id = self.parse_url(url)
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / f"{video_id}.wav"
        with httpx.Client(
            headers=self._API_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(60.0, read=180.0),
        ) as client:
            view = self._api_json(
                client,
                "https://api.bilibili.com/x/web-interface/view",
                {"bvid": video_id},
            )
            cid = view.get("cid")
            if not cid:
                raise RuntimeError("Bilibili metadata did not include a cid")

            play = self._api_json(
                client,
                "https://api.bilibili.com/x/player/playurl",
                {
                    "bvid": video_id,
                    "cid": cid,
                    "qn": 64,
                    "fnval": 16,
                    "fourk": 0,
                },
            )
            dash = play.get("dash") or {}
            audio_streams = dash.get("audio") or []
            video_streams = dash.get("video") or []
            if not audio_streams:
                raise RuntimeError("Bilibili play API returned no audio stream")

            audio_stream = max(
                audio_streams, key=lambda item: item.get("bandwidth") or 0
            )
            raw_audio = output_dir / f"{video_id}_audio.m4s"
            self._download_stream(client, audio_stream, raw_audio)
            try:
                self.extract_audio(raw_audio, audio_path)
            finally:
                raw_audio.unlink(missing_ok=True)

            video_path = None
            if keep_video:
                if not video_streams:
                    raise RuntimeError("Bilibili play API returned no video stream")
                h264_streams = [
                    item
                    for item in video_streams
                    if item.get("codecid") == 7 and (item.get("height") or 0) <= 720
                ]
                candidates = h264_streams or [
                    item
                    for item in video_streams
                    if (item.get("height") or 0) <= 720
                ] or video_streams
                video_stream = max(
                    candidates,
                    key=lambda item: (
                        item.get("height") or 0,
                        item.get("bandwidth") or 0,
                    ),
                )
                video_path = output_dir / f"{video_id}_video.m4s"
                self._download_stream(client, video_stream, video_path)

            tags = []
            try:
                tag_data = self._api_json(
                    client,
                    "https://api.bilibili.com/x/tag/archive/tags",
                    {"bvid": video_id},
                )
                if isinstance(tag_data, list):
                    tags = [item.get("tag_name", "") for item in tag_data]
            except Exception:
                logger.debug("Bilibili tags unavailable for %s", video_id)

        owner = view.get("owner") or {}
        stat = view.get("stat") or {}
        metadata = {
            "title": view.get("title", ""),
            "duration": view.get("duration", 0),
            "thumbnail": view.get("pic", ""),
            "uploader": owner.get("name", ""),
            "video_id": video_id,
            "description": (view.get("desc") or "")[:2000],
            "tags": [tag for tag in tags if tag],
            "view_count": stat.get("view"),
            "like_count": stat.get("like"),
            "upload_date": view.get("pubdate"),
        }
        return audio_path, metadata, video_path

    @staticmethod
    def _api_json(client: httpx.Client, endpoint: str, params: dict) -> dict:
        response = client.get(endpoint, params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(
                f"Bilibili API error {payload.get('code')}: "
                f"{payload.get('message', 'unknown error')}"
            )
        return payload.get("data") or {}

    @staticmethod
    def _download_stream(
        client: httpx.Client, stream: dict, destination: Path
    ) -> None:
        urls = [
            stream.get("baseUrl") or stream.get("base_url"),
            *(stream.get("backupUrl") or stream.get("backup_url") or []),
        ]
        last_error = None
        for stream_url in [value for value in urls if value]:
            try:
                with client.stream("GET", stream_url) as response:
                    response.raise_for_status()
                    with destination.open("wb") as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            output.write(chunk)
                if destination.stat().st_size > 0:
                    return
            except Exception as exc:
                last_error = exc
                destination.unlink(missing_ok=True)
        raise RuntimeError(f"Unable to download Bilibili media stream: {last_error}")

    @staticmethod
    def check_cookies(cookies_path: Path | None = None) -> str:
        """Check if Bilibili cookies are valid. Returns 'valid', 'expired', or 'not_configured'."""
        from core.config import settings
        path = cookies_path or settings.cookies_path
        if not path.is_file():
            return "not_configured"

        opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
            "cookiefile": str(path),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.bilibili.com/video/{_TEST_VIDEO_ID}", download=False)
                if info and info.get("title"):
                    return "valid"
                return "expired"
        except Exception as e:
            if "403" in str(e) or "Forbidden" in str(e):
                return "expired"
            logger.warning("Cookies check failed: %s", e)
            return "expired"
