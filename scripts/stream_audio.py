"""Stream audio to the running server exactly like the browser does, and print live results.

    python scripts/stream_audio.py recording.wav
    python scripts/stream_audio.py --say "आज की meeting cancel है, please sab ko inform kar do"

`--say` synthesises the sentence with the app's Piper voices first, so you can demo and test
the real-time pipeline without a microphone. Audio is sent in 100 ms chunks at real-time speed.
"""
import argparse
import asyncio
import io
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RATE = 16_000
CHUNK = RATE // 10  # 100 ms


def load_pcm16(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        if wav.getsampwidth() != 2:
            raise SystemExit("Only 16-bit WAV files are supported")
        frames = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32)
        if wav.getnchannels() > 1:
            frames = frames.reshape(-1, wav.getnchannels()).mean(axis=1)
        rate = wav.getframerate()
    if rate != RATE:
        n = int(len(frames) * RATE / rate)
        frames = np.interp(np.linspace(0, len(frames), n, endpoint=False), np.arange(len(frames)), frames)
    return frames.astype("<i2").tobytes()


async def stream(pcm: bytes, url: str, language: str, title: str, realtime: bool) -> int:
    pcm += b"\x00\x00" * RATE  # one second of trailing silence, like a speaker pausing
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start", "language": language, "title": title}))

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                t = msg["type"]
                if t == "ready":
                    print(f"[ready] engine={msg['provider']} model={msg['model']}")
                elif t == "interim":
                    print(f"  … {msg['text']}")
                elif t == "final":
                    print(f"  ✔ {msg['text']}")
                elif t == "saved":
                    s = msg["transcription"]
                    print(f"[saved] id={s['id']} language={s['language_label']} words={s['word_count']}\n{s['text']}")
                    return 0
                elif t == "empty":
                    print("[empty] nothing recognised")
                    return 1
                else:
                    print(f"[{t}] {msg.get('message')}")
                    if t == "error":
                        return 2
            return 3

        read_task = asyncio.create_task(reader())
        started = time.perf_counter()
        for i in range(0, len(pcm), CHUNK * 2):
            if read_task.done():
                break
            await ws.send(pcm[i:i + CHUNK * 2])
            if realtime:
                await asyncio.sleep(max(0.0, started + (i / 2 + CHUNK) / RATE - time.perf_counter()))
        if not read_task.done():
            await ws.send(json.dumps({"type": "stop"}))
        return await read_task


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("wav", nargs="?", type=Path, help="16-bit WAV file (any sample rate, mono or stereo)")
    p.add_argument("--say", help="synthesise this text with Piper and stream it")
    p.add_argument("--url", default="ws://127.0.0.1:8000/ws/transcribe")
    p.add_argument("--language", default="auto", choices=["auto", "hi-IN", "en-IN"])
    p.add_argument("--title", default="")
    p.add_argument("--fast", action="store_true", help="send as fast as possible instead of real time")
    args = p.parse_args()

    if args.say:
        from app.tts import get_tts

        wav_bytes = get_tts().synthesize_wav(args.say)
    elif args.wav:
        wav_bytes = args.wav.read_bytes()
    else:
        p.error("give a WAV file or --say TEXT")
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(asyncio.run(stream(load_pcm16(wav_bytes), args.url, args.language, args.title, not args.fast)))


if __name__ == "__main__":
    main()
