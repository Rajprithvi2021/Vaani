"""FastAPI application: REST API, WebSocket streaming and the static web UI."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import ROOT_DIR, get_settings
from app.db import init_db
from app.routers import realtime, transcriptions, tts
from app.stt import get_transcriber
from app.tts import get_tts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Vaani — Real-time Speech to Text", version="1.0.0", lifespan=lifespan)
app.include_router(transcriptions.router)
app.include_router(tts.router)
app.include_router(realtime.router)


@app.get("/api/health", tags=["meta"])
def health():
    settings = get_settings()
    transcriber = get_transcriber()
    return {
        "status": "ok",
        "stt": {"provider": transcriber.name, "model": transcriber.model,
                "configured": settings.stt_provider != "gemini" or bool(settings.gemini_api_key)},
        "tts": get_tts().status(),
        "database": settings.database_url.split("://", 1)[0],
    }


app.mount("/", StaticFiles(directory=ROOT_DIR / "static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
