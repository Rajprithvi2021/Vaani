"""Pick the streaming speech-to-text engine from settings."""
from functools import lru_cache

from app.config import get_settings
from app.stt.base import StreamingTranscriber


@lru_cache
def get_transcriber() -> StreamingTranscriber:
    settings = get_settings()
    if settings.stt_provider == "whisper":
        from app.stt.whisper_local import WhisperTranscriber

        return WhisperTranscriber(settings.whisper_model, settings.whisper_device, settings.whisper_compute_type)

    from app.stt.gemini_live import GeminiLiveTranscriber

    return GeminiLiveTranscriber(settings.gemini_api_key, settings.gemini_live_model,
                                 settings.gemini_transcription_mode)
