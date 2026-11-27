"""Real-time transcription with the Gemini Live API (bidirectional WebSocket).

The default model, `gemini-3.5-transcribe-live`, is Google's dedicated live-transcription model:
it answers with text only, detects the language automatically and handles code-switching
(Hindi <-> English mid-sentence). Conversational Live models (e.g. `gemini-3.8-live`) also work;
they only reply in audio, which we ignore — we read the *input* transcription.

Reliability:
  * audio goes through a queue, so a dropped or rotated connection (Gemini sends `go_away`
    before closing a ~10 min connection) is re-opened without losing what the user says next;
  * on stop we send `audio_stream_end` and wait briefly for the last words to be finalised.
"""
import asyncio
import logging
from contextlib import suppress

from google import genai
from google.genai import types

from app.stt.base import LANGUAGE_HINTS, SAMPLE_RATE, StreamingSession, TranscriptEvent

log = logging.getLogger(__name__)

MIME_TYPE = f"audio/pcm;rate={SAMPLE_RATE}"
CONNECT_TIMEOUT_S = 20
MAX_RECONNECTS = 3


class GeminiLiveTranscriber:
    name = "gemini"

    def __init__(self, api_key: str, model: str, mode: str = "VERBATIM"):
        self.model = model
        self._api_key = api_key
        self._mode = mode
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY is not set. Add it to .env "
                               "(free key: https://aistudio.google.com/apikey) or set STT_PROVIDER=whisper.")
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key, http_options={"api_version": "v1beta"})
        return self._client

    def build_config(self, language: str) -> types.LiveConnectConfig:
        # The transcription model streams text; conversational native-audio models only allow AUDIO.
        modality = types.Modality.TEXT if "transcribe" in self.model else types.Modality.AUDIO
        return types.LiveConnectConfig(
            response_modalities=[modality],
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=LANGUAGE_HINTS.get(language) or None,  # None = auto-detect + code-switching
                mode=self._mode,
            ),
        )

    async def open_session(self, language: str) -> StreamingSession:
        session = GeminiLiveSession(self._get_client(), self.model, self.build_config(language),
                                    smart=self._mode == "SMART")
        await session.start()
        return session


class GeminiLiveSession(StreamingSession):
    def __init__(self, client: genai.Client, model: str, config: types.LiveConnectConfig, smart: bool):
        super().__init__()
        self._client = client
        self._model = model
        self._config = config
        self._smart = smart  # SMART mode sends the cumulative, cleaned-up transcript each time
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._carry: bytes | None = None   # chunk to resend after a reconnect
        self._task: asyncio.Task | None = None
        self._ready: asyncio.Future | None = None
        self._interim = ""                 # latest hypothesis not yet finalised
        self._smart_base = ""              # SMART text from previous connections
        self._smart_current = ""
        self._last_event = 0.0
        self._go_away = False

    # ---- StreamingSession API ---------------------------------------------------------------
    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._task = asyncio.create_task(self._run())
        try:
            await asyncio.wait_for(asyncio.shield(self._ready), timeout=CONNECT_TIMEOUT_S)
        except TimeoutError:
            await self.aclose()
            raise RuntimeError("Timed out connecting to the Gemini Live API") from None
        except Exception:
            await self.aclose()
            raise

    async def send_audio(self, pcm16: bytes) -> None:
        self._audio.put_nowait(pcm16)

    async def finish(self) -> None:
        self._audio.put_nowait(None)

    async def aclose(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._task
        self.close_events()

    # ---- connection loop --------------------------------------------------------------------
    async def _run(self) -> None:
        failures = 0
        try:
            while True:
                try:
                    async with self._client.aio.live.connect(model=self._model, config=self._config) as live:
                        if not self._ready.done():
                            self._ready.set_result(None)
                        log.info("Gemini Live connected (%s)", self._model)
                        if await self._stream(live):
                            return
                    log.info("Gemini Live connection rotated; reconnecting")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if not self._ready.done():
                        self._ready.set_exception(exc)
                        return
                    failures += 1
                    log.warning("Gemini Live connection error (%d/%d): %s", failures, MAX_RECONNECTS, exc)
                    if failures > MAX_RECONNECTS:
                        self.emit(TranscriptEvent("error", f"Lost connection to Gemini Live: {exc}"))
                        return
                    await asyncio.sleep(0.25 * 2 ** failures)
                self._end_connection()
        finally:
            self._end_connection()
            self.close_events()

    async def _stream(self, live) -> bool:
        """Pump audio into one connection. True = user finished, False = reconnect needed."""
        self._go_away = False
        receiver = asyncio.create_task(self._receive(live))
        try:
            while True:
                if receiver.done():
                    receiver.result()  # re-raise connection errors
                    return False
                if self._carry is not None:
                    chunk, self._carry = self._carry, None
                else:
                    try:
                        chunk = await asyncio.wait_for(self._audio.get(), timeout=0.2)
                    except TimeoutError:
                        if self._go_away:
                            await self._rotate(live, receiver)
                            return False
                        continue
                if chunk is None:
                    try:
                        await live.send_realtime_input(audio_stream_end=True)
                    except Exception:
                        self._audio.put_nowait(None)  # retry the stop on the next connection
                        raise
                    await self._drain(receiver)
                    return True
                if self._go_away:
                    # Server will close this connection soon: new audio goes to the next one.
                    self._carry = chunk
                    await self._rotate(live, receiver)
                    return False
                try:
                    await live.send_realtime_input(audio=types.Blob(data=chunk, mime_type=MIME_TYPE))
                except Exception:
                    self._carry = chunk
                    raise
        finally:
            receiver.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await receiver

    async def _rotate(self, live, receiver: asyncio.Task) -> None:
        """Finalise what was said on a connection that is going away."""
        with suppress(Exception):
            await live.send_realtime_input(audio_stream_end=True)
            await self._drain(receiver)

    async def _receive(self, live) -> None:
        while True:
            # receive() ends after each turn, so keep re-entering it for the whole session.
            async for message in live.receive():
                self._handle(message)

    def _handle(self, message: types.LiveServerMessage) -> None:
        if message.go_away is not None:
            self._go_away = True
        content = message.server_content
        if content is None:
            return
        loop = asyncio.get_running_loop()
        interim = content.interim_input_transcription
        if interim is not None and interim.text:
            self._interim = interim.text
            self._last_event = loop.time()
            self.emit(TranscriptEvent("interim", interim.text))
        final = content.input_transcription
        if final is not None and final.text:
            self._interim = ""
            self._last_event = loop.time()
            if self._smart:
                self._smart_current = final.text.strip()
                full = f"{self._smart_base} {self._smart_current}".strip()
                self.emit(TranscriptEvent("final", full, replace=True))
            else:
                self.emit(TranscriptEvent("final", final.text))

    async def _drain(self, receiver: asyncio.Task) -> None:
        """After audio_stream_end, wait until the last words are finalised (or give up)."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        while not receiver.done():
            now = loop.time()
            idle = now - max(self._last_event, started)
            if (not self._interim and idle > 1.5) or idle > 3.0 or now - started > 10.0:
                break
            await asyncio.sleep(0.1)

    def _end_connection(self) -> None:
        """Keep text from a connection that is going away."""
        if self._interim:
            # Never finalised (stopped mid-word or connection dropped): keep the best guess.
            if self._smart:
                self._smart_current = f"{self._smart_current} {self._interim}".strip()
                self.emit(TranscriptEvent("final", f"{self._smart_base} {self._smart_current}".strip(), replace=True))
            else:
                self.emit(TranscriptEvent("final", self._interim))
            self._interim = ""
        if self._smart and self._smart_current:
            self._smart_base = f"{self._smart_base} {self._smart_current}".strip()
            self._smart_current = ""
