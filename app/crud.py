"""Database operations for transcriptions."""
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.language import detect_language
from app.models import Transcription
from app.schemas import TranscriptionCreate, TranscriptionUpdate


def _like_pattern(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_transcriptions(db: Session, *, q: str | None = None, language: str | None = None,
                        limit: int = 20, offset: int = 0) -> tuple[list[Transcription], int]:
    stmt = select(Transcription)
    if q:
        pattern = _like_pattern(q.strip())
        stmt = stmt.where(or_(Transcription.title.ilike(pattern, escape="\\"),
                              Transcription.text.ilike(pattern, escape="\\")))
    if language:
        stmt = stmt.where(Transcription.language == language)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Transcription.created_at.desc(), Transcription.id.desc())
                      .limit(limit).offset(offset)).all()
    return list(rows), total


def get_transcription(db: Session, transcription_id: int) -> Transcription | None:
    return db.get(Transcription, transcription_id)


def create_transcription(db: Session, data: TranscriptionCreate, *, source: str = "manual",
                         model: str | None = None, duration_seconds: float = 0.0) -> Transcription:
    text = data.text.strip()
    row = Transcription(
        title=data.title.strip(),
        text=text,
        language=data.language or detect_language(text),
        source=source,
        model=model,
        duration_seconds=round(duration_seconds, 2),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_transcription(db: Session, row: Transcription, data: TranscriptionUpdate) -> Transcription:
    changes = data.model_dump(exclude_unset=True)
    if changes.get("title") is not None:
        row.title = changes["title"].strip()
    if changes.get("text") is not None:
        row.text = changes["text"].strip()
        if changes.get("language") is None:
            row.language = detect_language(row.text)
    if changes.get("language") is not None:
        row.language = changes["language"]
    db.commit()
    db.refresh(row)
    return row


def delete_transcription(db: Session, row: Transcription) -> None:
    db.delete(row)
    db.commit()


def get_stats(db: Session) -> dict:
    total, duration = db.execute(
        select(func.count(Transcription.id), func.coalesce(func.sum(Transcription.duration_seconds), 0.0))
    ).one()
    by_language = dict(db.execute(select(Transcription.language, func.count()).group_by(Transcription.language)).all())
    by_source = dict(db.execute(select(Transcription.source, func.count()).group_by(Transcription.source)).all())
    # Word counts are cheap to compute in Python and portable across databases.
    words = sum(len(t.split()) for t in db.scalars(select(Transcription.text)))
    return {"total": total, "total_duration_seconds": float(duration), "total_words": words,
            "by_language": by_language, "by_source": by_source}


def default_title(text: str, max_words: int = 7) -> str:
    words = text.split()
    if not words:
        return "Untitled recording"
    title = " ".join(words[:max_words])
    return (title + "…") if len(words) > max_words else title
