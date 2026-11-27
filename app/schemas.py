"""Request and response models for the REST API."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.language import LANGUAGE_LABELS

Language = Literal["en", "hi", "hi-en"]


class TranscriptionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(default="", max_length=100_000)
    language: Language | None = Field(default=None, description="Detected from the text when omitted.")


class TranscriptionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=100_000)
    language: Language | None = Field(default=None, description="Re-detected when the text changes and this is omitted.")


class TranscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    text: str
    language: str
    source: str
    model: str | None
    duration_seconds: float
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def language_label(self) -> str:
        return LANGUAGE_LABELS.get(self.language, self.language)

    @computed_field
    @property
    def word_count(self) -> int:
        return len(self.text.split())


class TranscriptionPage(BaseModel):
    items: list[TranscriptionOut]
    total: int
    limit: int
    offset: int


class Stats(BaseModel):
    total: int
    total_duration_seconds: float
    total_words: int
    by_language: dict[str, int]
    by_source: dict[str, int]


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5_000)
