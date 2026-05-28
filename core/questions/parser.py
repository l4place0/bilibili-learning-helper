"""Parse question JSON output from LLM into structured question lists."""

import json
import logging
import re
from uuid import uuid4

from core.questions.schema import ALL_TYPES, validate_question

logger = logging.getLogger(__name__)


def parse_questions_json(raw: str) -> list[dict]:
    """Parse a JSON string (possibly wrapped in markdown code blocks) into a list of question dicts.

    Handles common LLM output formats:
    - Pure JSON array
    - JSON wrapped in ```json ... ```
    - JSON with trailing commas or other minor issues
    """
    text = raw.strip()
    # Strip markdown code blocks
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to fix trailing commas
        text = re.sub(r",\s*([}\]])", r"\1", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse questions JSON: %s", e)
            return []

    if isinstance(data, dict) and "questions" in data:
        data = data["questions"]
    if not isinstance(data, list):
        logger.warning("Expected list of questions, got %s", type(data).__name__)
        return []

    return data


def parse_questions(raw: str) -> list[dict]:
    """Parse LLM output into validated question list with defaults filled in.

    Returns list of question dicts with guaranteed base fields.
    """
    raw_questions = parse_questions_json(raw)
    questions = []
    for i, q in enumerate(raw_questions):
        # Ensure base fields
        if "id" not in q:
            q["id"] = str(uuid4())[:8]
        if "type" not in q:
            q["type"] = "qa"
        if "difficulty" not in q:
            q["difficulty"] = 3
        if "bloom_level" not in q:
            q["bloom_level"] = "understand"
        if "source_refs" not in q:
            q["source_refs"] = []

        # Normalize type
        qtype = q["type"].lower().strip()
        type_aliases = {
            "truefalse": "true_false", "true/false": "true_false",
            "multiple_choice": "choice", "multiplechoice": "choice", "mcq": "choice",
            "fillintheblank": "fill_blank", "fill-in-blank": "fill_blank", "cloze": "fill_blank",
            "sequence": "sequencing", "order": "sequencing", "ordering": "sequencing",
            "pair": "matching", "pairing": "matching",
            "code_completion": "code", "codecompletion": "code",
            "open_ended": "explain", "explanation": "explain",
        }
        q["type"] = type_aliases.get(qtype, qtype)

        if q["type"] not in ALL_TYPES:
            logger.warning("Unknown question type '%s', defaulting to 'qa'", q["type"])
            q["type"] = "qa"

        questions.append(q)

    return questions
