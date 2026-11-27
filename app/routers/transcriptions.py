"""CRUD endpoints for saved transcriptions."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app import crud
from app.db import get_db
from app.models import Transcription
from app.schemas import Language, Stats, TranscriptionCreate, TranscriptionOut, TranscriptionPage, TranscriptionUpdate

router = APIRouter(prefix="/api", tags=["transcriptions"])

DB = Annotated[Session, Depends(get_db)]


def _get_or_404(db: Session, transcription_id: int) -> Transcription:
    row = crud.get_transcription(db, transcription_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Transcription {transcription_id} not found")
    return row


@router.get("/transcriptions", response_model=TranscriptionPage)
def list_transcriptions(db: DB,
                        q: Annotated[str | None, Query(max_length=200, description="Search title and text")] = None,
                        language: Language | None = None,
                        limit: Annotated[int, Query(ge=1, le=100)] = 20,
                        offset: Annotated[int, Query(ge=0)] = 0):
    items, total = crud.list_transcriptions(db, q=q, language=language, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/transcriptions", response_model=TranscriptionOut, status_code=status.HTTP_201_CREATED)
def create_transcription(data: TranscriptionCreate, db: DB):
    return crud.create_transcription(db, data)


@router.get("/transcriptions/{transcription_id}", response_model=TranscriptionOut)
def get_transcription(transcription_id: int, db: DB):
    return _get_or_404(db, transcription_id)


@router.patch("/transcriptions/{transcription_id}", response_model=TranscriptionOut)
def update_transcription(transcription_id: int, data: TranscriptionUpdate, db: DB):
    return crud.update_transcription(db, _get_or_404(db, transcription_id), data)


@router.delete("/transcriptions/{transcription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transcription(transcription_id: int, db: DB):
    crud.delete_transcription(db, _get_or_404(db, transcription_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stats", response_model=Stats)
def stats(db: DB):
    return crud.get_stats(db)
