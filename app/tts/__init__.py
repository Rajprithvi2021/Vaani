"""Open-source text-to-speech with Piper (offline, runs on CPU).

Code-mixed text is split into script runs, so "आज की meeting cancel है" is read with the
Hindi voice for the Devanagari words and the English voice for the Latin ones, then joined.
"""
import io
import logging
import threading
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.language import split_by_script

log = logging.getLogger(__name__)

GAP_SECONDS = 0.06  # short pause between language runs


class TTSUnavailable(RuntimeError):
    pass


class PiperTTS:
    def __init__(self, voices_dir: Path, voice_en: str, voice_hi: str):
        self._dir = Path(voices_dir)
        self._names = {"en": voice_en, "hi": voice_hi}
        self._voices: dict[str, object] = {}
        self._lock = threading.Lock()  # espeak phonemizer is not thread-safe

    def _path(self, lang: str) -> Path:
        return self._dir / f"{self._names[lang]}.onnx"

    def has_voice(self, lang: str) -> bool:
        return self._path(lang).exists() and self._path(lang).with_suffix(".onnx.json").exists()

    def status(self) -> dict:
        return {"engine": "piper", "available": self.has_voice("en") or self.has_voice("hi"),
                "voices": {lang: {"name": name, "installed": self.has_voice(lang)} for lang, name in self._names.items()}}

    def _voice(self, lang: str):
        if not self.has_voice(lang):
            other = "hi" if lang == "en" else "en"
            if not self.has_voice(other):
                raise TTSUnavailable("No Piper voices installed. Run: python scripts/download_voices.py")
            lang = other
        if lang not in self._voices:
            from piper import PiperVoice

            log.info("Loading Piper voice %s", self._names[lang])
            self._voices[lang] = PiperVoice.load(self._path(lang))
        return self._voices[lang]

    def synthesize_wav(self, text: str) -> bytes:
        runs = split_by_script(text) or [("en", text)]
        pieces: list[np.ndarray] = []
        out_rate: int | None = None
        with self._lock:
            for lang, chunk in runs:
                voice = self._voice(lang)
                for audio in voice.synthesize(chunk):
                    samples = audio.audio_float_array.astype(np.float32)
                    if out_rate is None:
                        out_rate = audio.sample_rate
                    elif audio.sample_rate != out_rate:
                        samples = _resample(samples, audio.sample_rate, out_rate)
                    pieces.append(samples)
                if out_rate:
                    pieces.append(np.zeros(int(out_rate * GAP_SECONDS), dtype=np.float32))
        if not pieces or out_rate is None:
            raise TTSUnavailable("Nothing to synthesise")
        pcm = (np.clip(np.concatenate(pieces), -1.0, 1.0) * 32767).astype("<i2")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(out_rate)
            wav.writeframes(pcm.tobytes())
        return buf.getvalue()


def _resample(samples: np.ndarray, src: int, dst: int) -> np.ndarray:
    n = int(round(len(samples) * dst / src))
    return np.interp(np.linspace(0, len(samples), n, endpoint=False), np.arange(len(samples)), samples).astype(np.float32)


@lru_cache
def get_tts() -> PiperTTS:
    s = get_settings()
    return PiperTTS(s.piper_voices_dir, s.piper_voice_en, s.piper_voice_hi)
