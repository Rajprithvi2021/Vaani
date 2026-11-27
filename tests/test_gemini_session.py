"""Gemini Live session logic against a fake Live connection (no network)."""
import asyncio
from contextlib import asynccontextmanager

import pytest
from google.genai import types

from app.stt.gemini_live import GeminiLiveSession, GeminiLiveTranscriber


def transcription(text: str, interim: bool = False) -> types.LiveServerMessage:
    field = "interim_input_transcription" if interim else "input_transcription"
    return types.LiveServerMessage(server_content=types.LiveServerContent(**{field: types.Transcription(text=text)}))


class FakeLive:
    """Turns every audio chunk into one interim+final word; can announce go_away after N chunks."""

    def __init__(self, words: list[str], go_away_after: int | None = None):
        self.words = words
        self.go_away_after = go_away_after
        self.audio: list[bytes] = []
        self.stream_ended = False
        self.queue: asyncio.Queue[types.LiveServerMessage] = asyncio.Queue()

    async def send_realtime_input(self, *, audio=None, audio_stream_end=None):
        if audio is not None:
            assert audio.mime_type == "audio/pcm;rate=16000"
            self.audio.append(audio.data)
            word = self.words[len(self.audio) - 1]
            await self.queue.put(transcription(word, interim=True))
            await self.queue.put(transcription(word))
            if self.go_away_after and len(self.audio) == self.go_away_after:
                await self.queue.put(types.LiveServerMessage(go_away=types.LiveServerGoAway(time_left="5s")))
        if audio_stream_end:
            self.stream_ended = True

    async def receive(self):
        while True:
            yield await self.queue.get()


class FakeClient:
    def __init__(self, connections: list[FakeLive]):
        self.connections = connections
        self.opened = 0
        self.aio = self
        self.live = self

    @asynccontextmanager
    async def connect(self, *, model, config):
        live = self.connections[self.opened]
        self.opened += 1
        yield live


async def collect(session: GeminiLiveSession) -> list:
    return [e async for e in session.events()]


def config():
    return GeminiLiveTranscriber("key", "gemini-3.5-transcribe-live").build_config("auto")


@pytest.mark.anyio
async def test_streams_audio_and_finishes():
    live = FakeLive(["नमस्ते", "everyone"])
    session = GeminiLiveSession(FakeClient([live]), "m", config(), smart=False)
    await session.start()
    events_task = asyncio.create_task(collect(session))
    await session.send_audio(b"a" * 3200)
    await session.send_audio(b"b" * 3200)
    await session.finish()
    events = await asyncio.wait_for(events_task, timeout=10)
    await session.aclose()

    assert live.stream_ended
    assert [e.text for e in events if e.kind == "final"] == ["नमस्ते", "everyone"]
    assert [e.text for e in events if e.kind == "interim"] == ["नमस्ते", "everyone"]


@pytest.mark.anyio
async def test_reconnects_after_go_away_without_losing_audio():
    first = FakeLive(["one", "two"], go_away_after=2)
    second = FakeLive(["three", "four"])
    client = FakeClient([first, second])
    session = GeminiLiveSession(client, "m", config(), smart=False)
    await session.start()
    events_task = asyncio.create_task(collect(session))
    for chunk in (b"1", b"2", b"3", b"4"):
        await session.send_audio(chunk * 3200)
        await asyncio.sleep(0.05)
    await session.finish()
    events = await asyncio.wait_for(events_task, timeout=15)
    await session.aclose()

    assert client.opened == 2
    assert first.stream_ended and second.stream_ended  # each connection was flushed
    assert len(first.audio) + len(second.audio) == 4
    assert [e.text for e in events if e.kind == "final"] == ["one", "two", "three", "four"]


@pytest.mark.anyio
async def test_unfinalised_interim_is_kept_on_stop():
    class InterimOnly(FakeLive):
        async def send_realtime_input(self, *, audio=None, audio_stream_end=None):
            if audio is not None:
                self.audio.append(audio.data)
                await self.queue.put(transcription("half a sente", interim=True))
            if audio_stream_end:
                self.stream_ended = True

    session = GeminiLiveSession(FakeClient([InterimOnly([])]), "m", config(), smart=False)
    await session.start()
    events_task = asyncio.create_task(collect(session))
    await session.send_audio(b"x" * 3200)
    await session.finish()
    events = await asyncio.wait_for(events_task, timeout=15)
    assert events[-1].kind == "final" and events[-1].text == "half a sente"


@pytest.mark.anyio
async def test_connection_error_is_raised_from_start():
    class Broken:
        def __init__(self):
            self.aio = self
            self.live = self

        @asynccontextmanager
        async def connect(self, *, model, config):
            raise RuntimeError("API key not valid")
            yield  # pragma: no cover

    session = GeminiLiveSession(Broken(), "m", config(), smart=False)
    with pytest.raises(RuntimeError, match="API key not valid"):
        await session.start()


def test_config_uses_text_for_transcribe_model_and_language_hints():
    t = GeminiLiveTranscriber("key", "gemini-3.5-transcribe-live")
    cfg = t.build_config("auto")
    assert cfg.response_modalities == [types.Modality.TEXT]
    assert not cfg.input_audio_transcription.language_codes  # auto-detect + code-switching
    assert t.build_config("hi-IN").input_audio_transcription.language_codes == ["hi-IN"]
    assert GeminiLiveTranscriber("key", "gemini-3.8-live").build_config("auto").response_modalities == [types.Modality.AUDIO]


def test_missing_key_message():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        asyncio.run(GeminiLiveTranscriber("", "m").open_session("auto"))


@pytest.fixture
def anyio_backend():
    return "asyncio"
