"""ASR provider factory."""

from core.asr.base import BaseASR


def get_asr(provider: str = "", **kwargs) -> BaseASR:
    """Get an ASR provider instance.

    Args:
        provider: "inprocess" | "local" | "openai". Defaults to settings.asr_provider.
        **kwargs: Provider-specific args (endpoint, api_key, model, base_url).
    """
    from core.config import settings

    provider = provider or settings.asr_provider

    if provider == "local":
        from core.asr.local import LocalASR
        endpoint = kwargs.get("endpoint") or settings.asr_endpoint
        if not endpoint:
            raise ValueError("ASR_ENDPOINT required for local provider")
        return LocalASR(endpoint)

    if provider == "openai":
        from core.asr.cloud import OpenAIWhisperAPI
        api_key = kwargs.get("api_key") or settings.asr_api_key
        if not api_key:
            raise ValueError("ASR_API_KEY required for openai provider")
        return OpenAIWhisperAPI(
            api_key=api_key,
            model=kwargs.get("model") or settings.asr_model,
            base_url=kwargs.get("base_url", ""),
        )

    # Default: in-process whisper
    from core.asr.whisper import InProcessASR
    return InProcessASR()


def format_segments_for_llm(segments: list[dict]) -> str:
    """Format transcript segments for LLM consumption.

    Converts segments list to: [S0 @00:00] text [S1 @00:15] text ...
    Each segment gets a sequential ID and timestamp.
    """
    if not segments:
        return ""
    lines = []
    for i, seg in enumerate(segments):
        start = seg.get("start", 0)
        m, s = divmod(int(start), 60)
        ts = f"{m:02d}:{s:02d}"
        text = seg.get("text", "").strip()
        lines.append(f"[S{i} @{ts}] {text}")
    return "\n".join(lines)
