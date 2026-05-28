"""Generate self-contained interactive review HTML documents."""

import base64
import json
import re
from pathlib import Path

from core.config import settings


def parse_review_cards(summary: str) -> list[dict]:
    """Extract Q&A cards from the '## 复习卡片' / '## Review Cards' section of a summary.

    Returns a list of {"question": str, "answer": str} dicts (legacy format).
    Returns empty list if the section is missing or no cards are found.
    """
    # Find the review cards section
    pattern = r"##\s*(?:复习卡片|Review Cards)\s*\n(.*?)(?=\n##\s|\Z)"
    match = re.search(pattern, summary, re.DOTALL | re.IGNORECASE)
    if not match:
        return []

    section = match.group(1)
    # Extract Q/A pairs
    q_pattern = r"\*\*Q(\d+):\*\*\s*(.*?)(?=\n\*\*[AQ]\d+:\*\*|\Z)"
    a_pattern = r"\*\*A(\d+):\*\*\s*(.*?)(?=\n\*\*[AQ]\d+:\*\*|\Z)"

    questions = {int(m.group(1)): m.group(2).strip() for m in re.finditer(q_pattern, section, re.DOTALL)}
    answers = {int(m.group(1)): m.group(2).strip() for m in re.finditer(a_pattern, section, re.DOTALL)}

    # Match by index, truncate to shortest
    common_ids = sorted(set(questions.keys()) & set(answers.keys()))
    return [{"type": "qa", "question": questions[i], "answer": answers[i],
             "difficulty": 3, "bloom_level": "understand", "source_refs": [], "id": f"qa_{i}"}
            for i in common_ids]


def encode_frames(task_id: str, duration: float | None = None) -> list[dict]:
    """Read frame images for a task and return base64-encoded data.

    Returns a list of {"index": int, "data_uri": str, "timestamp": str}.
    """
    frames_dir = settings.cache_dir / "frames" / task_id
    if not frames_dir.exists():
        frames_dir = settings.audio_dir / task_id

    if not frames_dir.exists():
        return []

    frame_files = sorted(frames_dir.glob("frame_*.jpg"))
    if not frame_files:
        frame_files = sorted(frames_dir.glob("frame_*.webp"))
    if not frame_files:
        frame_files = sorted(frames_dir.glob("frame_*.*"))
    if not frame_files:
        frame_files = sorted(
            list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")) + list(frames_dir.glob("*.webp"))
        )

    total = len(frame_files)
    if total == 0:
        return []

    frames = []
    for i, f in enumerate(frame_files):
        b64 = base64.b64encode(f.read_bytes()).decode()
        ext = f.suffix.lstrip(".")
        mime = "jpeg" if ext == "jpg" else ext
        # Estimate timestamp
        if duration and total > 1:
            ts_sec = duration * i / (total - 1)
            minutes = int(ts_sec // 60)
            seconds = int(ts_sec % 60)
            timestamp = f"{minutes:02d}:{seconds:02d}"
        else:
            timestamp = ""
        frames.append({
            "index": i,
            "data_uri": f"data:image/{mime};base64,{b64}",
            "timestamp": timestamp,
        })

    return frames


def generate_review_doc(task: dict, cards: list[dict], frames: list[dict]) -> str:
    """Render a self-contained interactive review HTML document.

    Uses Jinja2 to render the template with all data embedded.
    """
    from jinja2 import Environment, FileSystemLoader

    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("review_doc.html")

    # Use structured segments from metadata if available, otherwise parse from text
    metadata = task.get("metadata") or {}
    raw_segments = metadata.get("transcript_segments", [])
    if raw_segments:
        transcript_segments = [
            {"index": i, "timestamp": _format_seg_timestamp(seg["start"]), "text": seg["text"]}
            for i, seg in enumerate(raw_segments)
        ]
    else:
        transcript = task.get("transcript", "") or ""
        transcript_segments = _parse_transcript_segments(transcript)

    # Merge legacy Q&A cards with structured questions from metadata
    all_questions = list(cards)  # Legacy Q&A cards (already parsed)
    meta_questions = metadata.get("questions", [])
    if meta_questions:
        all_questions.extend(meta_questions)

    # Build data for JS injection
    review_data = {
        "taskId": task.get("task_id", ""),
        "title": metadata.get("title", "Untitled"),
        "url": task.get("url", ""),
        "platform": task.get("platform", ""),
        "summary": task.get("summary", ""),
        "transcriptSegments": transcript_segments,
        "cards": all_questions,
        "frames": frames,
        "metadata": metadata,
    }

    return template.render(
        review_data_json=json.dumps(review_data, ensure_ascii=False),
        review_data=review_data,
    )


def _format_seg_timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _parse_transcript_segments(transcript: str) -> list[dict]:
    """Split transcript into segments by timestamp markers.

    Returns list of {"index": int, "timestamp": str, "text": str}.
    """
    if not transcript:
        return []

    # Split by lines, each line may have [MM:SS] prefix
    segments = []
    ts_pattern = re.compile(r"^\[(\d{2}:\d{2})\]\s*(.*)")
    current_ts = ""
    current_text = ""

    for line in transcript.split("\n"):
        line = line.strip()
        if not line:
            if current_text:
                segments.append({"index": len(segments), "timestamp": current_ts, "text": current_text})
                current_text = ""
            continue
        m = ts_pattern.match(line)
        if m:
            if current_text:
                segments.append({"index": len(segments), "timestamp": current_ts, "text": current_text})
            current_ts = m.group(1)
            current_text = m.group(2)
        else:
            current_text += (" " + line) if current_text else line

    if current_text:
        segments.append({"index": len(segments), "timestamp": current_ts, "text": current_text})

    return segments
