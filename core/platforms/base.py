import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yt_dlp

from core.runtime import ffmpeg_executable

logger = logging.getLogger(__name__)


class BasePlatform(ABC):
    @abstractmethod
    def match(self, url: str) -> bool:
        """Return True if this platform handles the given URL."""
        ...

    @abstractmethod
    def parse_url(self, url: str) -> str:
        """Extract and return the video ID from the URL."""
        ...

    @abstractmethod
    def download(self, url: str, output_dir: Path, keep_video: bool = False) -> tuple[Path, dict, Path | None]:
        """Download video, extract audio. Return (audio_path, metadata, video_path).

        metadata should include: title, duration, thumbnail, etc.
        video_path is returned when keep_video=True, else None.
        """
        ...

    @staticmethod
    def check_ffmpeg() -> None:
        if not ffmpeg_executable():
            raise RuntimeError(
                "ffmpeg not found. Install it with your OS package manager "
                "(for example: brew install ffmpeg or apt install ffmpeg)"
            )

    @staticmethod
    def extract_audio(video_path: Path, output_path: Path) -> Path:
        """Extract audio from video file using ffmpeg."""
        import subprocess

        BasePlatform.check_ffmpeg()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                ffmpeg_executable(), "-y", "-i", str(video_path),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )
        return output_path


class YtdlpPlatform(BasePlatform):
    """Shared base for platforms using yt-dlp (Bilibili, YouTube, etc.)."""

    def _get_ydl_opts(self, output_path: Path) -> dict:
        """Return yt-dlp options. Subclasses can override to add cookies, etc."""
        return {
            "outtmpl": str(output_path),
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }

    def _build_metadata(self, info: dict, video_id: str) -> dict:
        """Extract metadata from yt-dlp info dict."""
        return {
            "title": info.get("title", ""),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "uploader": info.get("uploader", ""),
            "video_id": video_id,
            "description": (info.get("description") or "")[:2000],
            "tags": info.get("tags") or [],
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "upload_date": info.get("upload_date", ""),
        }

    def _retry_download(self, url: str, ydl_opts: dict, max_retries: int = 3) -> dict:
        """Download with retry logic. Returns yt-dlp info dict."""
        last_error = None
        for attempt in range(max_retries):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=True)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning("Download attempt %d failed: %s, retrying in %ds", attempt + 1, e, wait)
                    time.sleep(wait)
        raise last_error

    def _download_video_stream(self, url: str, video_id: str, output_dir: Path) -> Path | None:
        """Download video-only stream for frame extraction. Returns path or None."""
        video_only_path = output_dir / f"{video_id}_video.mp4"
        vid_opts = {
            "outtmpl": str(video_only_path),
            "format": "bestvideo[height<=720][ext=mp4]/bestvideo[height<=720]/bestvideo",
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }
        # Allow subclass to add cookies to video opts too
        base_opts = self._get_ydl_opts(video_only_path)
        if "cookiefile" in base_opts:
            vid_opts["cookiefile"] = base_opts["cookiefile"]

        logger.info("Downloading video stream: %s", video_id)
        try:
            vid_info = self._retry_download(url, vid_opts)
            vid_file = Path(vid_info.get("_filename") or "")
            if not vid_file.name or not vid_file.exists():
                candidates = list(output_dir.glob(f"{video_id}_video.*"))
                vid_file = candidates[0] if candidates else None
            if vid_file and vid_file.exists():
                return vid_file
            logger.warning("Video stream download failed, falling back to audio-only")
        except Exception as e:
            logger.warning("Video stream download failed: %s, falling back to audio-only", e)
        return None

    def download(self, url: str, output_dir: Path, keep_video: bool = False) -> tuple[Path, dict, Path | None]:
        video_id = self.parse_url(url)
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / f"{video_id}.wav"
        video_path = output_dir / f"{video_id}.mp4"

        # Skip re-download if audio already exists (e.g. retry after transcription failure)
        if audio_path.exists() and audio_path.stat().st_size > 0:
            logger.info("Audio already exists, skipping download: %s", audio_path.name)
            # Still extract metadata from yt-dlp (without downloading)
            try:
                info_opts = self._get_ydl_opts(audio_path)
                info_opts["skip_download"] = True
                with yt_dlp.YoutubeDL(info_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                metadata = self._build_metadata(info, video_id)
            except Exception as e:
                logger.warning("Failed to extract metadata on retry: %s", e)
                metadata = {"video_id": video_id, "title": ""}
            ret_video = video_path if keep_video and video_path.exists() else None
            return audio_path, metadata, ret_video

        ydl_opts = self._get_ydl_opts(video_path)
        logger.info("Downloading audio: %s", video_id)
        info = self._retry_download(url, ydl_opts)

        downloaded = Path(info.get("_filename") or "")
        if not downloaded.name or not downloaded.exists():
            candidates = list(output_dir.glob(f"{video_id}.*"))
            if candidates:
                downloaded = candidates[0]
            else:
                raise FileNotFoundError(f"Downloaded file not found for {video_id}")

        metadata = self._build_metadata(info, video_id)

        if keep_video:
            # Parallel: extract audio + download video stream
            logger.info("Parallel: extracting audio + downloading video stream: %s", video_id)
            with ThreadPoolExecutor(max_workers=2) as pool:
                audio_future = pool.submit(self.extract_audio, downloaded, audio_path)
                video_future = pool.submit(self._download_video_stream, url, video_id, output_dir)
                audio_future.result()  # raise if failed
                ret_video = video_future.result()  # may be None
        else:
            logger.info("Extracting audio: %s", video_id)
            self.extract_audio(downloaded, audio_path)
            ret_video = None

        if downloaded != audio_path and downloaded.exists():
            downloaded.unlink()

        return audio_path, metadata, ret_video
