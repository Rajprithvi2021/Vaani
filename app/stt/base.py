"""Common interface for streaming speech-to-text engines.

Audio in:  raw 16-bit little-endian PCM, 16 kHz, mono (what the browser worklet sends).
Events out: an async stream of `TranscriptEvent`s, ending when the session is finished.
"""
import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

SAMPLE_RATE = 16_000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # int16 mono

# What the UI offers. "auto" lets the engine detect and switch language mid-sentence.
LANGUAGE_HINTS: dict[str, list[str]] = {
    "auto": [],
    "hi-IN": ["hi-IN"],
    "en-IN": ["en-IN"],
}


@dataclass(frozen=True)
class TranscriptEvent:
    kind: Literal["interim", "final", "info", "error"]
    text: str
    # True when `text` is the whole transcript so far rather than a new segment.
    replace: bool = False


class StreamingSession:
    """Base class: engines push events with `emit` and call `close_events` when done."""

    def __init__(self) -> None:
        self._events: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()
        self._closed = False

    def emit(self, event: TranscriptEvent) -> None:
        if not self._closed:
            self._events.put_nowait(event)

    def close_events(self) -> None:
        if not self._closed:
            self._closed = True
            self._events.put_nowait(None)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while (event := await self._events.get()) is not None:
            yield event

    async def start(self) -> None:
        """Connect / load the model. Raise here so the client gets a clear error."""

    async def send_audio(self, pcm16: bytes) -> None:
        raise NotImplementedError

    async def finish(self) -> None:
        """No more audio is coming: flush the last words, then close the event stream."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release resources. Safe to call more than once."""
        self.close_events()


class StreamingTranscriber(Protocol):
    name: str   # stored as the transcription's `source`
    model: str

    async def open_session(self, language: str) -> StreamingSession: ...


class TranscriptBuffer:
    """Joins final segments into the running transcript."""

    def __init__(self) -> None:
        self.text = ""

    def add(self, segment: str, replace: bool = False) -> str:
        if replace:
            self.text = segment.strip()
        elif segment.strip():
            if self.text and not self.text[-1].isspace() and not segment[0].isspace():
                self.text += " "
            self.text += segment
        return self.text.strip()
