"""Text-to-speech endpoints (Piper). The UI falls back to the browser's voices on 503."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import crud
from app.db import get_db
from app.schemas import SpeechRequest
from app.tts import PiperTTS, TTSUnavailable, get_tts

router = APIRouter(prefix="/api", tags=["text-to-speech"])

MAX_CHARS = 5_000


async def _speak(tts: PiperTTS, text: str) -> Response:
    try:
        wav = await run_in_threadpool(tts.synthesize_wav, text[:MAX_CHARS])
    except TTSUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/tts", response_class=Response, responses={200: {"content": {"audio/wav": {}}}})
async def text_to_speech(req: SpeechRequest, tts: Annotated[PiperTTS, Depends(get_tts)]):
    return await _speak(tts, req.text)


@router.get("/transcriptions/{transcription_id}/speech", response_class=Response,
            responses={200: {"content": {"audio/wav": {}}}})
async def transcription_speech(transcription_id: int, db: Annotated[Session, Depends(get_db)],
                               tts: Annotated[PiperTTS, Depends(get_tts)]):
    row = crud.get_transcription(db, transcription_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Transcription {transcription_id} not found")
    if not row.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This transcription has no text")
    return await _speak(tts, row.text)
