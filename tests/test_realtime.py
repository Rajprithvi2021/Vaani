"""WebSocket streaming tests with a scripted fake engine (no network, no model)."""
import pytest
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.stt import get_transcriber
from app.stt.base import StreamingSession, TranscriptBuffer, TranscriptEvent

CHUNK = b"\x00\x01" * 1600  # 100 ms of 16 kHz int16 audio


class FakeSession(StreamingSession):
    """Every 2 chunks of audio becomes one word: interim first, final on the next chunk."""

    WORDS = ["आज", "की", "meeting", "cancel", "है"]

    def __init__(self):
        super().__init__()
        self.chunks = 0
        self.word = 0

    async def send_audio(self, pcm16: bytes) -> None:
        self.chunks += 1
        if self.chunks % 2 == 1 and self.word < len(self.WORDS):
            self.emit(TranscriptEvent("interim", self.WORDS[self.word]))
        elif self.word < len(self.WORDS):
            self.emit(TranscriptEvent("final", self.WORDS[self.word]))
            self.word += 1

    async def finish(self) -> None:
        self.close_events()


class FakeTranscriber:
    name = "fake"
    model = "fake-1"

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sessions: list[FakeSession] = []

    async def open_session(self, language: str) -> StreamingSession:
        if self.fail:
            raise RuntimeError("GEMINI_API_KEY is not set")
        session = FakeSession()
        self.sessions.append(session)
        return session


@pytest.fixture
def fake(client):
    transcriber = FakeTranscriber()
    app.dependency_overrides[get_transcriber] = lambda: transcriber
    return transcriber


def test_stream_transcribe_and_save(client, fake):
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.send_json({"type": "start", "language": "auto", "title": "Live test"})
        assert ws.receive_json()["type"] == "ready"
        for _ in range(10):
            ws.send_bytes(CHUNK)
        ws.send_json({"type": "stop"})

        messages = []
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] in ("saved", "empty", "error"):
                break

    kinds = [m["type"] for m in messages]
    assert kinds.count("interim") == 5 and kinds.count("final") == 5
    finals = [m for m in messages if m["type"] == "final"]
    assert finals[-1]["transcript"] == "आज की meeting cancel है"

    saved = messages[-1]["transcription"]
    assert saved["title"] == "Live test"
    assert saved["language"] == "hi-en"
    assert saved["source"] == "fake" and saved["model"] == "fake-1"
    assert saved["duration_seconds"] == pytest.approx(1.0)

    stored = client.get(f"/api/transcriptions/{saved['id']}").json()
    assert stored["text"] == "आज की meeting cancel है"


def test_title_defaults_to_first_words(client, fake):
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(4):
            ws.send_bytes(CHUNK)
        ws.send_json({"type": "stop"})
        while (msg := ws.receive_json())["type"] != "saved":
            pass
    assert msg["transcription"]["title"] == "आज की"


def test_silence_saves_nothing(client, fake):
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        ws.send_json({"type": "stop"})
        assert ws.receive_json()["type"] == "empty"
    assert client.get("/api/transcriptions").json()["total"] == 0


def test_disconnect_mid_stream_still_saves(client, fake):
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(4):
            ws.send_bytes(CHUNK)
        ws.receive_json()  # make sure the server has consumed the audio
    # The socket closed without "stop": what was recognised is kept.
    for _ in range(50):
        if client.get("/api/transcriptions").json()["total"]:
            break
        import time
        time.sleep(0.05)
    items = client.get("/api/transcriptions").json()["items"]
    assert len(items) == 1 and items[0]["text"].startswith("आज")


def test_engine_failure_is_reported(client):
    app.dependency_overrides[get_transcriber] = lambda: FakeTranscriber(fail=True)
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.send_json({"type": "start"})
        msg = ws.receive_json()
        assert msg["type"] == "error" and "GEMINI_API_KEY" in msg["message"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_first_message_must_be_start(client, fake):
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.send_json({"type": "hello"})
        assert ws.receive_json()["type"] == "error"


def test_transcript_buffer_spacing():
    b = TranscriptBuffer()
    b.add("Hello")
    b.add(" there,")
    b.add("how are you")
    assert b.text == "Hello there, how are you"
    assert b.add("Cleaned up text.", replace=True) == "Cleaned up text."
