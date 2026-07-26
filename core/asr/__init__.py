"""ASR provider factory."""

from core.asr.base import BaseASR


def get_asr(provider: str = "", **kwargs) -> BaseASR:
    """Get an ASR provider instance.

    Args:
        provider: "whisper-cpp" | "local" | "openai".
            Defaults to settings.asr_provider.
        **kwargs: Provider-specific args (endpoint, api_key, model, base_url).
    """
    from core.config import settings

    provider = provider or settings.asr_provider

    if provider in ("whisper-cpp", "whisper_cpp"):
        from core.asr.whisper_cpp import WhisperCppASR
        return WhisperCppASR(
            executable=kwargs.get("executable", ""),
            model_path=kwargs.get("model_path"),
            progress_callback=kwargs.get("progress_callback"),
        )

    if provider == "local":
        from core.asr.local import LocalASR
        endpoint = kwargs.get("endpoint") or settings.asr_endpoint
        if not endpoint:
            raise ValueError("ASR_ENDPOINT required for local provider")
        return LocalASR(endpoint, timeout=settings.asr_timeout_seconds)

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

    raise ValueError(
        "Unknown ASR provider: "
        f"{provider}. Available: ['whisper-cpp', 'local', 'openai']"
    )
