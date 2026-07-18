import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from core.llm.prompts import (
    CONTENT_TYPES,
    get_classify_prompt,
    get_summary_prompt,
    get_three_stage_prompt,
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

    def generate_three_stage(self, transcript: str, lang: str = "zh", detail: str = "normal", has_segments: bool = False) -> dict:
        """Generate three-stage learning materials (preview + index + summary) in one call.

        Returns dict with keys: preview, index, summary.
        Falls back to regex extraction if JSON parsing fails.
        """
        from core.llm.prompts import DETAIL_MAX_TOKENS
        prompt = get_three_stage_prompt(lang, detail, has_segments).format(transcript=transcript)
        max_tokens = DETAIL_MAX_TOKENS.get(detail, 8192)
        # Three-stage output is longer than plain summary
        max_tokens = max(max_tokens, 8192)

        for attempt in range(3):
            try:
                raw = self._chat(prompt, max_tokens=max_tokens)
                if not raw or not raw.strip():
                    logger.warning("Three-stage attempt %d: empty response, retrying", attempt + 1)
                    continue
                result = self._parse_three_stage_json(raw)
                if self._validate_three_stage(result):
                    return result
                logger.warning("Three-stage attempt %d: validation failed, fields missing", attempt + 1)
                # Return partial result if at least one section exists
                if any(result.get(k) for k in ("preview", "index", "summary")):
                    return self._fill_three_stage_defaults(result)
            except json.JSONDecodeError as e:
                logger.warning("Three-stage attempt %d: JSON parse error (%s)", attempt + 1, e)
            except Exception as e:
                logger.warning("Three-stage attempt %d: error (%s)", attempt + 1, e)

        # All attempts failed — return empty structure
        logger.warning("Three-stage generation failed after 3 attempts, returning empty structure")
        return self._empty_three_stage()

    @staticmethod
    def _parse_three_stage_json(raw: str) -> dict:
        """Parse JSON from LLM response, handling markdown code blocks."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        # Try to find JSON object in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
        return json.loads(text)

    @staticmethod
    def _validate_three_stage(result: dict) -> bool:
        """Check that all three sections exist and are non-empty."""
        has_preview = bool(result.get("preview", {}).get("overview"))
        has_index = bool(result.get("index")) and isinstance(result.get("index"), list)
        has_summary = bool(result.get("summary", {}).get("text"))
        return has_preview and has_index and has_summary

    @staticmethod
    def _fill_three_stage_defaults(result: dict) -> dict:
        """Fill missing fields with defaults."""
        defaults = BaseLLM._empty_three_stage()
        for key in ("preview", "index", "summary"):
            if not result.get(key):
                result[key] = defaults[key]
            elif key == "preview":
                result[key].setdefault("overview", "")
                result[key].setdefault("questions", [])
                result[key].setdefault("pre_quiz", [])
            elif key == "summary":
                result[key].setdefault("text", "")
                result[key].setdefault("cards", [])
                result[key].setdefault("post_quiz", [])
                result[key].setdefault("weak_points", [])
        return result

    @staticmethod
    def _empty_three_stage() -> dict:
        """Return an empty three-stage structure."""
        return {
            "preview": {"overview": "", "questions": [], "pre_quiz": []},
            "index": [],
            "summary": {"text": "", "cards": [], "post_quiz": [], "weak_points": []},
        }
