import logging
import os
import threading
from pathlib import Path

from core.config import settings

# Set HuggingFace mirror endpoint if configured
if settings.hf_endpoint:
    os.environ["HF_ENDPOINT"] = settings.hf_endpoint

logger = logging.getLogger(__name__)

_backend = None  # "faster" or "openai"
_model = None
_device = None
_lock = threading.Lock()


def _get_device() -> str:
    global _device
    if _device is not None:
        return _device

    try:
        import torch
        if torch.cuda.is_available():
            try:
                torch.zeros(1, device="cuda")
                _device = "cuda"
                logger.info("Whisper: using CUDA GPU")
            except Exception as e:
                _device = "cpu"
                logger.warning("Whisper: CUDA available but failed (%s), falling back to CPU", e)
        else:
            _device = "cpu"
            logger.info("Whisper: using CPU (CUDA not available)")
    except ImportError:
        _device = "cpu"
        logger.info("Whisper: using CPU (torch not available)")
    return _device


def _detect_backend() -> str:
    """Detect which Whisper backend to use. Prefer faster-whisper."""
    global _backend
    if _backend is not None:
        return _backend

    # Check config override first
    preferred = getattr(settings, "whisper_backend", "faster")

    if preferred == "faster":
        try:
            import faster_whisper  # noqa: F401
            _backend = "faster"
            logger.info("Using faster-whisper backend")
            return _backend
        except ImportError:
            logger.warning("faster-whisper not installed, falling back to openai-whisper")

    try:
        import whisper  # noqa: F401
        _backend = "openai"
        logger.info("Using openai-whisper backend")
    except ImportError:
        _backend = "faster"
        logger.info("Using faster-whisper backend (openai-whisper not available)")

    return _backend


def _get_model():
    global _model
    if _model is not None:
        return _model

    backend = _detect_backend()
    device = _get_device()

    if backend == "faster":
        from faster_whisper import WhisperModel
        compute_type = "float32" if device == "cuda" else "int8"
        logger.info("Loading faster-whisper model: %s on %s (compute=%s)", settings.whisper_model, device, compute_type)
        _model = WhisperModel(settings.whisper_model, device=device, compute_type=compute_type)
    else:
        import whisper
        logger.info("Loading openai-whisper model: %s on %s", settings.whisper_model, device)
        _model = whisper.load_model(settings.whisper_model, device=device)

    logger.info("Whisper model loaded")
    return _model


def _format_timestamp(seconds: float) -> str:
    """Format seconds as [MM:SS]."""
    m, s = divmod(int(seconds), 60)
    return f"[{m:02d}:{s:02d}]"


def _transcribe_once(model, backend: str, audio_path: Path, language: str, beam_size: int = 5) -> tuple[str, list[dict]]:
    """Single transcription attempt. Returns (text, segments) with segment timestamps."""
    seg_data: list[dict] = []
    if backend == "faster":
        segments, info = model.transcribe(str(audio_path), language=language, beam_size=beam_size, vad_filter=False)
        logger.info("Whisper returned generator, language=%.2f, beam_size=%d", info.language_probability, beam_size)
        lines = []
        seg_count = 0
        for seg in segments:
            seg_count += 1
            if seg_count <= 3:
                logger.info("Segment %d: [%.1f-%.1f] %s", seg_count, seg.start, seg.end, seg.text.strip()[:100])
            ts = _format_timestamp(seg.start)
            lines.append(f"{ts} {seg.text.strip()}")
            seg_data.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        text = "\n".join(lines).strip()
        if seg_count == 0:
            logger.warning("faster-whisper produced 0 segments! language=%.2f, audio=%s, duration=%.1fs",
                           info.language_probability, audio_path.name, info.duration)
        logger.info("Transcription done: %d chars, %d segments (language: %.2f confidence, beam_size=%d)",
                    len(text), len(lines), info.language_probability, beam_size)
    else:
        result = model.transcribe(str(audio_path), language=language, fp16=False)
        raw_segments = result.get("segments", [])
        if raw_segments:
            lines = []
            for seg in raw_segments:
                ts = _format_timestamp(seg.get("start", 0))
                lines.append(f"{ts} {seg.get('text', '').strip()}")
                seg_data.append({"start": seg.get("start", 0), "end": seg.get("end", 0), "text": seg.get("text", "").strip()})
            text = "\n".join(lines).strip()
        else:
            text = result.get("text", "").strip()
        logger.info("Transcription done: %d chars", len(text))
    return text, seg_data


def transcribe(audio_path: Path, language: str = "zh") -> str:
    """Transcribe audio file to text using Whisper. Falls back to CPU on CUDA OOM."""
    text, _ = transcribe_segments(audio_path, language)
    return text


def transcribe_segments(audio_path: Path, language: str = "zh") -> tuple[str, list[dict]]:
    """Transcribe audio file and return (text, segments). Falls back to CPU on CUDA OOM."""
    global _device, _model

    logger.info("Transcribing: %s (lang=%s)", audio_path.name, language)

    with _lock:
        model = _get_model()
        backend = _detect_backend()

    try:
        text, seg_data = _transcribe_once(model, backend, audio_path, language)
        if not text and backend == "faster":
            logger.warning("Got 0 segments from cached model, retrying with fresh instance...")
            from faster_whisper import WhisperModel as FWModel
            fresh_model = FWModel(settings.whisper_model, device=_get_device(), compute_type="int8")
            text, seg_data = _transcribe_once(fresh_model, "faster", audio_path, language)
            if text:
                with _lock:
                    _model = fresh_model
                logger.info("Fresh model worked! Replaced cached model.")
            else:
                logger.warning("Fresh faster-whisper also returned 0 segments, trying openai-whisper...")
                try:
                    import whisper
                    ow_model = whisper.load_model(settings.whisper_model, device="cpu")
                    result = ow_model.transcribe(str(audio_path), language=language, fp16=False)
                    raw_segments = result.get("segments", [])
                    if raw_segments:
                        lines = []
                        seg_data = []
                        for seg in raw_segments:
                            ts = _format_timestamp(seg.get("start", 0))
                            lines.append(f"{ts} {seg.get('text', '').strip()}")
                            seg_data.append({"start": seg.get("start", 0), "end": seg.get("end", 0), "text": seg.get("text", "").strip()})
                        text = "\n".join(lines).strip()
                    else:
                        text = result.get("text", "").strip()
                    logger.info("openai-whisper fallback: %d chars", len(text))
                except ImportError:
                    logger.error("openai-whisper not available for fallback")
        return text, seg_data
    except RuntimeError as e:
        err_msg = str(e).lower()
        if "out of memory" in err_msg and _device == "cuda":
            with _lock:
                logger.warning("CUDA OOM during transcription, falling back to CPU permanently")
                _device = "cpu"
                _model = None
                model = _get_model()
            return _transcribe_once(model, backend, audio_path, language)
        if "reshape" in err_msg or "key.size" in err_msg or "out of memory" in err_msg:
            logger.warning("Whisper error (%s), trying openai-whisper CPU fallback", e)
            try:
                import whisper
                cpu_model = whisper.load_model(settings.whisper_model, device="cpu")
                result = cpu_model.transcribe(str(audio_path), language=language, fp16=False)
                raw_segments = result.get("segments", [])
                fallback_segs = []
                if raw_segments:
                    lines = []
                    for seg in raw_segments:
                        ts = _format_timestamp(seg.get("start", 0))
                        lines.append(f"{ts} {seg.get('text', '').strip()}")
                        fallback_segs.append({"start": seg.get("start", 0), "end": seg.get("end", 0), "text": seg.get("text", "").strip()})
                    return "\n".join(lines).strip(), fallback_segs
                return result.get("text", "").strip(), []
            except Exception as fallback_e:
                logger.error("CPU fallback also failed: %s", fallback_e)
                raise e
        raise


class InProcessASR:
    """Wrapper around the in-process Whisper transcribe function (duck-typed BaseASR)."""

    def transcribe(self, audio_path: Path, language: str = "zh") -> str:
        return transcribe(audio_path, language)

    def transcribe_segments(self, audio_path: Path, language: str = "zh") -> tuple[str, list[dict]]:
        return transcribe_segments(audio_path, language)
