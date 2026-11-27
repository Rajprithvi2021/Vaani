"""Application settings, read from environment variables and an optional `.env` file."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database -----------------------------------------------------------------------------
    database_url: str = "postgresql+psycopg://vaani:vaani@localhost:5432/vaani"

    # --- Speech-to-text -----------------------------------------------------------------------
    # "gemini"  -> Gemini Live API (cloud, real-time streaming, free tier)
    # "whisper" -> faster-whisper running locally (self-hosted, open source)
    stt_provider: Literal["gemini", "whisper"] = "gemini"

    gemini_api_key: str = ""
    gemini_live_model: str = "gemini-3.5-transcribe-live"
    # VERBATIM: each final message is a new segment (append). SMART: cumulative, cleaned-up text.
    gemini_transcription_mode: Literal["VERBATIM", "SMART"] = "VERBATIM"

    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Hard cap per recording; the browser stops itself here too.
    max_session_seconds: int = 600

    # --- Text-to-speech (Piper, open source) ---------------------------------------------------
    piper_voices_dir: Path = ROOT_DIR / "models" / "piper"
    piper_voice_en: str = "en_US-lessac-medium"
    piper_voice_hi: str = "hi_IN-priyamvada-medium"


@lru_cache
def get_settings() -> Settings:
    return Settings()
