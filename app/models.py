"""Database tables."""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Transcription(Base):
    __tablename__ = "transcriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # "en", "hi" or "hi-en" (code-mixed). Detected from the text, editable by the user.
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en", index=True)
    # Where the text came from: "gemini", "whisper" or "manual".
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    model: Mapped[str | None] = mapped_column(String(100))
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
