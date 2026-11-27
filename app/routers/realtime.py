"""WebSocket bridge: browser microphone -> streaming STT engine -> live text -> database.

Protocol
  client -> server  {"type": "start", "language": "auto" | "hi-IN" | "en-IN", "title": "..."}
  client -> server  binary frames: 16-bit PCM, 16 kHz, mono (~100 ms each)
  client -> server  {"type": "stop"}
  server -> client  {"type": "ready", "provider", "model", "max_seconds"}
                    {"type": "interim", "text"}                 # live guess, will change
                    {"type": "final", "text", "transcript"}     # committed segment + full text
                    {"type": "info" | "error", "message"}
                    {"type": "saved", "transcription": {...}}   # or {"type": "empty"}
"""
import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketState

from app import crud
from app.config import get_settings
from app.db import SessionLocal
from app.schemas import TranscriptionCreate, TranscriptionOut
from app.stt import get_transcriber
from app.stt.base import BYTES_PER_SECOND, LANGUAGE_HINTS, StreamingSession, StreamingTranscriber, TranscriptBuffer

log = logging.getLogger(__name__)
router = APIRouter()

FLUSH_TIMEOUT_S = 15


async def _send(ws: WebSocket, payload: dict) -> None:
    if ws.application_state == WebSocketState.CONNECTED and ws.client_state == WebSocketState.CONNECTED:
        try:
            await ws.send_json(payload)
        except (RuntimeError, WebSocketDisconnect):
            pass


def _save(text: str, title: str, source: str, model: str, duration: float) -> dict:
    with SessionLocal() as db:
        row = crud.create_transcription(
            db, TranscriptionCreate(title=title or crud.default_title(text), text=text),
            source=source, model=model, duration_seconds=duration)
        return TranscriptionOut.model_validate(row).model_dump(mode="json")


@router.websocket("/ws/transcribe")
async def transcribe(ws: WebSocket, transcriber: Annotated[StreamingTranscriber, Depends(get_transcriber)]):
    await ws.accept()
    settings = get_settings()

    try:
        start = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
    except (TimeoutError, json.JSONDecodeError, WebSocketDisconnect, KeyError):
        await _send(ws, {"type": "error", "message": 'Expected a {"type": "start"} message first.'})
        await ws.close(code=1008)
        return
    if start.get("type") != "start":
        await _send(ws, {"type": "error", "message": 'Expected a {"type": "start"} message first.'})
        await ws.close(code=1008)
        return

    language = start.get("language") if start.get("language") in LANGUAGE_HINTS else "auto"
    title = str(start.get("title") or "").strip()[:200]

    try:
        session: StreamingSession = await transcriber.open_session(language)
    except Exception as exc:
        log.warning("Could not start %s session: %s", transcriber.name, exc)
        await _send(ws, {"type": "error", "message": f"Could not start speech recognition: {exc}"})
        await ws.close(code=1011)
        return

    await _send(ws, {"type": "ready", "provider": transcriber.name, "model": transcriber.model,
                     "max_seconds": settings.max_session_seconds})

    buffer = TranscriptBuffer()

    async def forward_events() -> None:
        async for event in session.events():
            if event.kind == "final":
                full = buffer.add(event.text, replace=event.replace)
                await _send(ws, {"type": "final", "text": event.text.strip(), "transcript": full})
            elif event.kind == "interim":
                await _send(ws, {"type": "interim", "text": event.text.strip()})
            else:
                await _send(ws, {"type": event.kind, "message": event.text})

    forwarder = asyncio.create_task(forward_events())
    audio_bytes = 0
    max_bytes = settings.max_session_seconds * BYTES_PER_SECOND

    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                chunk = message["bytes"]
                if len(chunk) % 2:  # int16 frames only
                    chunk = chunk[:-1]
                audio_bytes += len(chunk)
                await session.send_audio(chunk)
                if audio_bytes >= max_bytes:
                    await _send(ws, {"type": "info", "message": "Maximum recording length reached."})
                    break
            elif message.get("text"):
                try:
                    if json.loads(message["text"]).get("type") == "stop":
                        break
                except json.JSONDecodeError:
                    continue
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # engine failure mid-stream: still save what we have
        log.exception("Streaming failed")
        await _send(ws, {"type": "error", "message": f"Streaming failed: {exc}"})

    # Flush the last words, then persist. We save even if the browser disconnected abruptly.
    try:
        await session.finish()
        await asyncio.wait_for(forwarder, timeout=FLUSH_TIMEOUT_S)
    except TimeoutError:
        log.warning("Timed out waiting for final transcript")
        forwarder.cancel()
    except Exception:
        log.exception("Error while finishing the session")
    finally:
        await session.aclose()

    text = buffer.text.strip()
    if text:
        try:
            saved = await run_in_threadpool(_save, text, title, transcriber.name, transcriber.model,
                                            audio_bytes / BYTES_PER_SECOND)
            await _send(ws, {"type": "saved", "transcription": saved})
        except Exception as exc:
            log.exception("Saving transcription failed")
            await _send(ws, {"type": "error", "message": f"Could not save the transcription: {exc}"})
    else:
        await _send(ws, {"type": "empty"})

    if ws.application_state == WebSocketState.CONNECTED:
        try:
            await ws.close()
        except RuntimeError:
            pass
