import base64
import logging
from pathlib import Path

import anthropic

from core.config import settings
from core.llm.base import BaseLLM
from core.vision.frames import extract_frames
from core.llm.prompts import get_summary_prompt

logger = logging.getLogger(__name__)


class ClaudeLLM(BaseLLM):
    def __init__(self):
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        kwargs = {"api_key": settings.anthropic_api_key}
        if settings.anthropic_base_url:
            kwargs["base_url"] = settings.anthropic_base_url
        self.client = anthropic.Anthropic(**kwargs)

    def _chat(self, prompt: str, max_tokens: int = 4096) -> str:
        message = self.client.messages.create(
            model=settings.claude_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _chat_multimodal(self, content: list[dict], max_tokens: int = 4096) -> str:
        message = self.client.messages.create(
            model=settings.claude_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": content}],
        )
        return message.content[0].text

    def summarize(self, transcript: str, lang: str = "zh", detail: str = "normal", content_type: str | None = None, has_segments: bool = False) -> str:
        from core.llm.prompts import DETAIL_MAX_TOKENS
        prompt = get_summary_prompt(content_type or "general", lang, multimodal=False, has_segments=has_segments).format(transcript=transcript)
        max_tokens = DETAIL_MAX_TOKENS.get(detail, 4096)
        logger.info("Summarizing with Claude (%s, type=%s, detail=%s)", settings.claude_model, content_type, detail)
        summary = self._chat(prompt, max_tokens=max_tokens)
        logger.info("Summary done: %d chars", len(summary))
        return summary

    def summarize_multimodal(
        self, transcript: str, video_path: Path, lang: str = "zh", detail: str = "normal",
        content_type: str | None = None, prefetched_frames: list[Path] | None = None,
        has_segments: bool = False,
    ) -> str:
        prompt = get_summary_prompt(content_type or "general", lang, multimodal=True, has_segments=has_segments).format(transcript=transcript)

        frames = extract_frames(
            video_path,
            max_frames=0,
            mode="hybrid",
            interval=settings.frame_interval,
        )

        content: list[dict] = []
        for frame in frames:
            b64 = base64.b64encode(frame.read_bytes()).decode()
            media_type = "image/webp" if frame.suffix == ".webp" else "image/jpeg"
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            })
        content.append({"type": "text", "text": prompt})

        logger.info("Multimodal summarizing with Claude (%s, %d frames, type=%s)", settings.claude_model, len(frames), content_type)
        summary = self._chat_multimodal(content, max_tokens=4096)
        logger.info("Multimodal summary done: %d chars", len(summary))
        return summary
