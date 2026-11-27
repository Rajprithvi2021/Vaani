"""Self-hosted, open-source streaming transcription with faster-whisper.

Whisper is not a streaming model, so we make it feel live:
  * every ~1 s of new speech, the current utterance is re-transcribed and sent as an interim result;
  * when the speaker pauses (~0.7 s of silence) or the utterance reaches 15 s, it is transcribed
    once more with a wider beam and committed as a final segment.
A single worker task runs the model so calls never overlap, and interims are skipped when it is busy.
"""
import asyncio
import logging
import threading

import numpy as np

from app.stt.base import SAMPLE_RATE, StreamingSession, TranscriptEvent

log = logging.getLogger(__name__)

SPEECH_RMS = 0.012          # energy gate for "someone is talking" (int16 scaled to [-1, 1])
END_OF_UTTERANCE_MS = 700   # pause that closes an utterance
MIN_SPEECH_MS = 250         # ignore clicks and breaths
INTERIM_EVERY_MS = 1000
MAX_UTTERANCE_S = 15
# Priming Whisper with code-mixed text makes it keep English words in Latin script
# and Hindi words in Devanagari instead of forcing everything into one script.
HINGLISH_PROMPT = "नमस्ते, आज की meeting में हम project timeline discuss करेंगे. Let's get started."

_model_lock = threading.Lock()
_models: dict[tuple[str, str, str], object] = {}


def load_model(name: str, device: str, compute_type: str):
    key = (name, device, compute_type)
    with _model_lock:
        if key not in _models:
            try:
                from faster_whisper import WhisperModel  # heavy import, only when this engine is used
            except ImportError:
                raise RuntimeError("faster-whisper is not installed (pip install -r requirements-local.txt), "
                                   "or set STT_PROVIDER=gemini") from None

            log.info("Loading faster-whisper model %s (%s/%s)", name, device, compute_type)
            _models[key] = WhisperModel(name, device=device, compute_type=compute_type)
        return _models[key]


class WhisperTranscriber:
    name = "whisper"

    def __init__(self, model: str, device: str = "cpu", compute_type: str = "int8"):
        self.model = model
        self._device = device
        self._compute_type = compute_type

    async def open_session(self, language: str) -> StreamingSession:
        whisper = await asyncio.to_thread(load_model, self.model, self._device, self._compute_type)
        session = WhisperSession(whisper, language)
        await session.start()
        return session


class WhisperSession(StreamingSession):
    def __init__(self, model, language: str):
        super().__init__()
        self._model = model
        # Whisper takes ISO-639-1 codes; None means auto-detect.
        self._language = {"hi-IN": "hi", "en-IN": "en"}.get(language)
        self._utterance = bytearray()
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._since_interim_ms = 0.0
        self._generation = 0  # bumps on every final; stale interims are dropped
        self._jobs: asyncio.Queue[tuple[str, int, bytes] | None] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._busy = False

    async def start(self) -> None:
        self._worker = asyncio.create_task(self._run_worker())

    async def send_audio(self, pcm16: bytes) -> None:
        samples = np.frombuffer(pcm16, dtype=np.int16)
        if samples.size == 0:
            return
        chunk_ms = samples.size * 1000 / SAMPLE_RATE
        rms = float(np.sqrt(np.mean((samples.astype(np.float32) / 32768.0) ** 2)))
        self._utterance.extend(pcm16)

        if rms >= SPEECH_RMS:
            self._speech_ms += chunk_ms
            self._silence_ms = 0.0
        else:
            self._silence_ms += chunk_ms
        self._since_interim_ms += chunk_ms

        if self._speech_ms < MIN_SPEECH_MS:
            # Only silence so far: keep a short lead-in, drop the rest.
            keep = int(0.3 * SAMPLE_RATE) * 2
            if self._silence_ms > 1000 and len(self._utterance) > keep:
                del self._utterance[:-keep]
                self._speech_ms = 0.0
            return

        utterance_s = len(self._utterance) / (SAMPLE_RATE * 2)
        if self._silence_ms >= END_OF_UTTERANCE_MS or utterance_s >= MAX_UTTERANCE_S:
            self._commit()
        elif self._since_interim_ms >= INTERIM_EVERY_MS and not self._busy and self._jobs.empty():
            self._since_interim_ms = 0.0
            self._jobs.put_nowait(("interim", self._generation, bytes(self._utterance)))

    def _commit(self) -> None:
        if self._speech_ms >= MIN_SPEECH_MS and self._utterance:
            self._jobs.put_nowait(("final", self._generation, bytes(self._utterance)))
        self._generation += 1
        self._utterance.clear()
        self._speech_ms = self._silence_ms = self._since_interim_ms = 0.0

    async def finish(self) -> None:
        self._commit()
        self._jobs.put_nowait(None)

    async def aclose(self) -> None:
        if self._worker and not self._worker.done():
            self._worker.cancel()
        self.close_events()

    async def _run_worker(self) -> None:
        try:
            while (job := await self._jobs.get()) is not None:
                kind, generation, audio = job
                self._busy = True
                try:
                    text = await asyncio.to_thread(self._transcribe, audio, kind == "final")
                except Exception as exc:  # keep the session alive; report and move on
                    log.exception("Whisper transcription failed")
                    self.emit(TranscriptEvent("error", f"Transcription failed: {exc}"))
                    continue
                finally:
                    self._busy = False
                if not text:
                    continue
                if kind == "final":
                    self.emit(TranscriptEvent("final", text))
                elif generation == self._generation:
                    self.emit(TranscriptEvent("interim", text))
        finally:
            self.close_events()

    def _transcribe(self, pcm16: bytes, final: bool) -> str:
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=5 if final else 1,
            initial_prompt=HINGLISH_PROMPT if self._language != "en" else None,
            condition_on_previous_text=False,
            vad_filter=False,
            # Timestamp tokens let Whisper segment code-switched speech; without them it tends to
            # stop after the first language switch and drop the rest of the utterance.
            without_timestamps=False,
        )
        parts = [s.text.strip() for s in segments if s.no_speech_prob < 0.6 and s.text.strip()]
        return " ".join(parts)
