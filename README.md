# Vaani (वाणी) — Real-time Speech to Text

A web app where you speak, in Hindi, English or a mix of both, and the words appear on screen **as you speak**.
Every recording is saved to **PostgreSQL** and listed in a **history dashboard** with full CRUD, search,
statistics and **text-to-speech** playback.

| Assignment requirement | How it is met |
|---|---|
| Real-time transcription | The browser streams 16 kHz PCM over a WebSocket every 100 ms. The server relays it to a streaming STT engine, and interim (live) and final words stream back. |
| Multilingual (Hindi + English mixed) | Default engine: **Gemini Live** `gemini-3.5-transcribe-live` with automatic language detection, which handles code-switching mid-sentence. Language hints (Hindi / English-India) are optional. Transcripts are tagged `hi`, `en` or `hi-en`. |
| Self-deployable open-source option | `STT_PROVIDER=whisper` runs **faster-whisper** locally (no cloud, no key) with pseudo-streaming. |
| Relational database | **PostgreSQL 17** (Docker) through SQLAlchemy 2. |
| History dashboard with CRUD | History tab: list, search, language filter, paging, stats; create, view, edit, delete. A REST API backs every action. |
| Text-to-speech (open source preferred) | **Piper** (open source, offline). Mixed text is split by script and read with a Hindi voice and an English voice. The browser's own voices are the fallback. |

## Architecture

```
 Browser                                  FastAPI server                              Engines
 ───────                                  ──────────────                              ───────
 mic ─► AudioWorklet (48k→16k PCM) ─WS─►  /ws/transcribe ──► StreamingTranscriber ──► Gemini Live API  (cloud, default)
          100 ms int16 chunks             │  ▲                 (one interface)    └─► faster-whisper   (local, open source)
 live text ◄──── interim / final ─────────┘  │
                                             └─ on stop: flush last words ─► PostgreSQL (transcriptions)
 History tab ◄── REST /api/transcriptions (CRUD, search, stats)
 ▶ Play     ◄── /api/transcriptions/{id}/speech ──► Piper TTS (hi + en voices) ─► WAV
```

What makes it reliable:
- **No lost audio at the start.** The mic is captured before the socket opens, and early chunks are buffered and sent once it does.
- **No lost words at the end.** On *Stop*, the server sends `audio_stream_end` and waits for the engine to finalise the last words. A trailing interim guess is kept rather than dropped.
- **Long sessions survive.** Gemini rotates Live connections (it sends `go_away` before closing). The session flushes the old connection and continues on a new one, and audio is queued, so nothing is lost (covered by tests).
- **Abrupt disconnects still save.** If the tab closes mid-recording, whatever was recognised is still saved.

## Quick start

Requirements: Python 3.12, Docker (for PostgreSQL), and a Gemini API key (free: https://aistudio.google.com/apikey).

```powershell
docker compose up -d db                      # PostgreSQL 17 on localhost:5432 (user/pass/db: vaani)
python -m venv .venv
.venv\Scripts\activate                       # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                       # macOS/Linux: cp .env.example .env  → then set GEMINI_API_KEY
python scripts/download_models.py            # Piper voices for text-to-speech (~120 MB)
uvicorn app.main:app --port 8000
```

Open http://localhost:8000, press **Start speaking**, and allow the microphone. Browsers allow the mic only on
`localhost` or HTTPS.

### Fully self-hosted (no cloud, no key)

```powershell
# in .env
STT_PROVIDER=whisper
WHISPER_MODEL=small        # base for low-RAM machines, medium/large-v3 for best Hindi accuracy
python scripts/download_models.py --whisper
```

Whisper is not a streaming model. The app re-transcribes the current utterance every ~1 s (interim) and commits it
after a ~0.7 s pause (final), and it primes the decoder with code-mixed text so English words stay in Latin script.
Accuracy depends heavily on model size: `small` needs about 1 GB of free RAM, and `base` runs on less but makes
more Hindi spelling mistakes.

### Everything in Docker

```powershell
docker compose --profile app up --build      # app on http://localhost:8000, reads .env
```

### Demo without a microphone

```powershell
python scripts/stream_audio.py --say "आज की meeting cancel हो गई है. Please inform the whole team."
python scripts/stream_audio.py my-recording.wav
```

This streams audio over the same WebSocket the browser uses, at real-time speed. `--say` synthesises the sentence
with Piper first. The script prints interim and final words as they arrive, then the saved row.

## API

Interactive docs: http://localhost:8000/docs

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/transcriptions?q=&language=&limit=&offset=` | List (newest first), search title and text, filter by `en`/`hi`/`hi-en` |
| `POST` | `/api/transcriptions` | Create `{title, text, language?}`. Language is detected if omitted. |
| `GET` | `/api/transcriptions/{id}` | Read one |
| `PATCH` | `/api/transcriptions/{id}` | Update any of `{title, text, language}`. Language is re-detected when the text changes. |
| `DELETE` | `/api/transcriptions/{id}` | Delete |
| `GET` | `/api/stats` | Totals, minutes, words, by language, by source |
| `GET` | `/api/transcriptions/{id}/speech` | Text-to-speech WAV of a saved transcription |
| `POST` | `/api/tts` | Text-to-speech WAV of `{text}` |
| `GET` | `/api/health` | Active STT engine/model, TTS voices, database |
| `WS` | `/ws/transcribe` | Real-time streaming (protocol below) |

WebSocket protocol:

```
client → {"type":"start","language":"auto"|"hi-IN"|"en-IN","title":"optional"}
client → binary frames: 16-bit little-endian PCM, 16 kHz, mono (~100 ms each)
client → {"type":"stop"}
server → {"type":"ready","provider","model","max_seconds"}
server → {"type":"interim","text"}                  live hypothesis (replaced as you speak)
server → {"type":"final","text","transcript"}       committed segment + full transcript so far
server → {"type":"saved","transcription":{...}}     or {"type":"empty"} / {"type":"error","message"}
```

## Data model

`transcriptions(id, title, text, language, source, model, duration_seconds, created_at, updated_at)`.
`language` is one of `en`, `hi`, `hi-en`. `source` is `gemini`, `whisper` or `manual`. Tables are created on startup.

## Tests

```powershell
pytest
```

The 33 tests run offline on in-memory SQLite and cover:
- the CRUD API, search with escaped wildcards, filters, paging, validation and stats;
- the WebSocket protocol with a scripted engine: streaming, default titles, silence, abrupt disconnect, engine failure;
- the Gemini Live session against a fake Live connection: streaming, `go_away` reconnect with no audio lost, keeping a trailing interim, connection errors, and config;
- language tagging, plus Piper output for mixed-language text (a valid WAV).

## Project layout

```
app/
  main.py               FastAPI app, routers, static UI
  config.py             settings from env / .env
  db.py, models.py      SQLAlchemy engine + Transcription table
  schemas.py, crud.py   API models + database operations
  language.py           hi / en / hi-en tagging, script splitting
  routers/              transcriptions (CRUD), realtime (WebSocket), tts
  stt/                  base interface, gemini_live.py, whisper_local.py
  tts/                  Piper text-to-speech
static/                 index.html, css/app.css, js/{main,recorder,pcm-worklet,api,speech}.js
scripts/                download_models.py, stream_audio.py
tests/                  pytest suite
```

## Design notes and trade-offs

- **Why Gemini Live as the default.** It is a true streaming model with a free tier, native Hindi–English code-switching,
  and interim results. It is a cloud API, not self-hosted, so faster-whisper sits behind the same interface for a
  fully self-hosted deployment.
- **No front-end framework.** Plain ES modules and one AudioWorklet keep the real-time path small and easy to follow.
- **Language tag is a heuristic.** It counts Devanagari vs Latin characters and adds a small romanised-Hindi lexicon. Users can override it in the editor.
- **Not included yet:** authentication or per-user history, schema migrations (Alembic), speaker diarization (not
  supported by the Live transcription model), and audio file storage (only text is kept).
