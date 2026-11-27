import io
import wave

import pytest

from app.config import get_settings
from app.main import app
from app.tts import PiperTTS, get_tts


def test_tts_returns_503_without_voices(client, tmp_path):
    app.dependency_overrides[get_tts] = lambda: PiperTTS(tmp_path, "en_US-lessac-medium", "hi_IN-priyamvada-medium")
    r = client.post("/api/tts", json={"text": "hello"})
    assert r.status_code == 503
    assert "download" in r.json()["detail"].lower()


def test_speech_for_unknown_transcription_is_404(client):
    assert client.get("/api/transcriptions/12345/speech").status_code == 404


voices_installed = PiperTTS(get_settings().piper_voices_dir, get_settings().piper_voice_en,
                            get_settings().piper_voice_hi).status()["available"]


@pytest.mark.skipif(not voices_installed, reason="Piper voices not downloaded (python scripts/download_models.py)")
def test_mixed_language_speech_is_valid_wav(client):
    created = client.post("/api/transcriptions", json={"title": "t", "text": "आज की meeting cancel है"}).json()
    r = client.get(f"/api/transcriptions/{created['id']}/speech")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(r.content)) as wav:
        assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
        assert wav.getnframes() / wav.getframerate() > 1.0  # more than a second of speech
