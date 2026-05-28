import base64
import logging
from pathlib import Path

from openai import OpenAI

from core.config import settings
from core.llm.base import BaseLLM
from core.llm.prompts import get_summary_prompt
from core.vision.frames import extract_frames

logger = logging.getLogger(__name__)


class OpenAILLM(BaseLLM):
    def __init__(self):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        self.client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)

    def _chat(self, prompt: str, max_tokens: int = 4096) -> str:
        response = self.client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        finish_reason = response.choices[0].finish_reason

        # MIMO API bug: sometimes returns empty content with finish_reason=length
        if not content and finish_reason == "length":
            logger.warning("MIMO API returned empty content with finish_reason=length, retrying")
            raise ValueError("Empty response from API")

        return content or ""

    def _chat_stream(self, prompt: str, max_tokens: int = 4096):
        """Stream text response from OpenAI API."""
        try:
            stream = self.client.chat.completions.create(
                model=settings.openai_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.warning("Streaming failed (%s), falling back to non-streaming", e)
            yield self._chat(prompt, max_tokens)

    def _chat_multimodal(self, content: list[dict], max_tokens: int = 4096) -> str:
        model = settings.openai_vision_model or settings.openai_model
        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    def summarize(self, transcript: str, lang: str = "zh", detail: str = "normal", content_type: str | None = None, has_segments: bool = False) -> str:
        from core.llm.prompts import DETAIL_MAX_TOKENS
        prompt = get_summary_prompt(content_type or "general", lang, multimodal=False, detail=detail, has_segments=has_segments).format(transcript=transcript)
        max_tokens = DETAIL_MAX_TOKENS.get(detail, 4096)
        logger.info("Summarizing with OpenAI (%s, type=%s, detail=%s)", settings.openai_model, content_type, detail)
        summary = self._chat(prompt, max_tokens=max_tokens)
        logger.info("Summary done: %d chars", len(summary))
        return summary

    def summarize_multimodal(
        self, transcript: str, video_path: Path, lang: str = "zh", detail: str = "normal",
        content_type: str | None = None, prefetched_frames: list[Path] | None = None,
        has_segments: bool = False,
    ) -> str:
        # Strategy 1: Extract frames and send as images (primary)
        try:
            return self._summarize_with_frames(transcript, video_path, lang, content_type, prefetched_frames, has_segments=has_segments)
        except Exception as e:
            logger.warning("Frame-based summarization failed: %s, trying native video", e)

        # Strategy 2: Native video via video_url (fallback)
        try:
            return self._summarize_native_video(transcript, video_path, lang, content_type, has_segments=has_segments)
        except Exception as e:
            logger.warning("Native video summarization failed: %s, falling back to text-only", e)

        # Strategy 3: Text-only (final fallback)
        return self.summarize(transcript, lang, content_type=content_type, has_segments=has_segments)

    def _summarize_native_video(self, transcript: str, video_path: Path, lang: str, content_type: str | None, has_segments: bool = False) -> str:
        prompt = get_summary_prompt(content_type or "general", lang, multimodal=True, has_segments=has_segments).format(transcript=transcript)

        video_data = video_path.read_bytes()
        b64 = base64.b64encode(video_data).decode()
        suffix = video_path.suffix.lower().lstrip(".")
        mime = {
            "mp4": "video/mp4", "mov": "video/quicktime",
            "avi": "video/x-msvideo", "wmv": "video/x-ms-wmv",
        }.get(suffix, "video/mp4")

        content = [
            {
                "type": "video_url",
                "video_url": {"url": f"data:{mime};base64,{b64}"},
                "fps": 2,
                "media_resolution": "default",
            },
            {"type": "text", "text": prompt},
        ]

        model = settings.openai_vision_model or settings.openai_model
        logger.info("Native video summarizing with OpenAI (%s, video=%s)", model, video_path.name)
        summary = self._chat_multimodal(content, max_tokens=4096)
        logger.info("Native video summary done: %d chars", len(summary))
        return summary

    def _summarize_with_frames(self, transcript: str, video_path: Path, lang: str, content_type: str | None,
                                prefetched_frames: list[Path] | None = None, has_segments: bool = False) -> str:
        prompt = get_summary_prompt(content_type or "general", lang, multimodal=True, has_segments=has_segments).format(transcript=transcript)

        if prefetched_frames:
            frames = prefetched_frames
            logger.info("Using %d prefetched frames", len(frames))
        else:
            frames = extract_frames(
                video_path,
                max_frames=0,
                mode="hybrid",
                interval=settings.frame_interval,
            )
        if not frames:
            raise RuntimeError("No frames extracted")

        content: list[dict] = []
        for frame in frames:
            b64 = base64.b64encode(frame.read_bytes()).decode()
            media_type = "image/webp" if frame.suffix == ".webp" else "image/jpeg"
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{b64}"},
            })
        content.append({"type": "text", "text": prompt})

        logger.info("Frame-based summarizing with OpenAI (%d frames, type=%s)", len(frames), content_type)
        summary = self._chat_multimodal(content, max_tokens=4096)
        logger.info("Frame-based summary done: %d chars", len(summary))
        return summary
