import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from core.llm.prompts import (
    CONTENT_TYPES,
    get_classify_prompt,
    get_summary_prompt,
)

logger = logging.getLogger(__name__)


class BaseLLM(ABC):
    @abstractmethod
    def _chat(self, prompt: str, max_tokens: int = 4096) -> str:
        """Send a text-only prompt to the LLM and return the response text."""
        ...

    def _chat_stream(self, prompt: str, max_tokens: int = 4096):
        """Stream text response from LLM. Yields text chunks. Default: falls back to non-streaming."""
        yield self._chat(prompt, max_tokens)

    def _chat_multimodal(self, content: list[dict], max_tokens: int = 4096) -> str:
        """Send a multimodal content array to the LLM. Default: extract text parts only."""
        text_parts = [p["text"] for p in content if p.get("type") == "text"]
        return self._chat("\n".join(text_parts), max_tokens=max_tokens)

    def classify(self, transcript: str, lang: str = "zh", multimodal: bool = False) -> dict:
        """Stage 1: Quick classification. Returns {"summary": str, "type": str}."""
        prompt = get_classify_prompt(lang, multimodal).format(transcript=transcript[:3000])

        # Retry up to 3 times (MIMO API sometimes returns empty responses)
        for attempt in range(3):
            try:
                raw = self._chat(prompt, max_tokens=500)
                if not raw or not raw.strip():
                    logger.warning("Classify attempt %d: empty response, retrying", attempt + 1)
                    continue

                # Extract JSON from response (handle markdown code blocks)
                text = raw.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                result = json.loads(text)
                content_type = result.get("type", "general")
                if content_type not in CONTENT_TYPES:
                    content_type = "general"
                return {"summary": result.get("summary", ""), "type": content_type}
            except json.JSONDecodeError as e:
                logger.warning("Classify attempt %d: invalid JSON response (%s), raw=%s", attempt + 1, e, raw[:200] if raw else "<empty>")
            except Exception as e:
                logger.warning("Classify attempt %d: network/API error: %s", attempt + 1, e)

        logger.warning("Classification failed after 3 attempts, using general")
        return {"summary": "", "type": "general"}

    def summarize(self, transcript: str, lang: str = "zh", detail: str = "normal", content_type: str | None = None, has_segments: bool = False) -> str:
        """Stage 2: Summarize with structured prompt based on content type."""
        from core.llm.prompts import DETAIL_MAX_TOKENS
        ct = content_type or "general"
        prompt = get_summary_prompt(ct, lang, multimodal=False, detail=detail, has_segments=has_segments).format(transcript=transcript)
        max_tokens = DETAIL_MAX_TOKENS.get(detail, 4096)
        return self._chat(prompt, max_tokens=max_tokens)

    def summarize_stream(self, transcript: str, lang: str = "zh", detail: str = "normal", content_type: str | None = None, has_segments: bool = False):
        """Stage 2: Stream summarize. Yields text chunks."""
        from core.llm.prompts import DETAIL_MAX_TOKENS
        ct = content_type or "general"
        prompt = get_summary_prompt(ct, lang, multimodal=False, detail=detail, has_segments=has_segments).format(transcript=transcript)
        max_tokens = DETAIL_MAX_TOKENS.get(detail, 4096)
        yield from self._chat_stream(prompt, max_tokens=max_tokens)

    def summarize_multimodal(
        self, transcript: str, video_path: Path, lang: str = "zh", detail: str = "normal",
        content_type: str | None = None, prefetched_frames: list[Path] | None = None,
        has_segments: bool = False,
    ) -> str:
        """Stage 2: Summarize with video + structured prompt. Default: fall back to text-only."""
        return self.summarize(transcript, lang, detail, content_type=content_type, has_segments=has_segments)
