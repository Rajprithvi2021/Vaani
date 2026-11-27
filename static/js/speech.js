// Text-to-speech: server-side Piper (open source) first, the browser's own voices as a fallback.
const DEVANAGARI = /[ऀ-ॿ]/;
const LATIN = /[A-Za-z]/;

let audio = null;
let audioUrl = null;
let onDone = null;

export function stopSpeaking() {
  if (audio) {
    audio.pause();
    audio = null;
  }
  if (audioUrl) {
    URL.revokeObjectURL(audioUrl);
    audioUrl = null;
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  const done = onDone;
  onDone = null;
  if (done) done();
}

/** Speak a saved transcription (id) or arbitrary text. Resolves with the engine used. */
export async function speak({ id, text }, onEnd) {
  stopSpeaking();
  onDone = onEnd || null;
  const res = await fetch(id ? `/api/transcriptions/${id}/speech` : "/api/tts", id ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (res.ok) {
    audioUrl = URL.createObjectURL(await res.blob());
    audio = new Audio(audioUrl);
    audio.onended = () => stopSpeaking();
    await audio.play();
    return "piper";
  }
  if (res.status !== 503) {
    onDone = null;
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Text-to-speech failed (${res.status})`);
  }
  browserSpeak(text);
  return "browser";
}

function splitByScript(text) {
  const runs = [];
  let lang = null;
  let buf = "";
  for (const ch of text) {
    const next = DEVANAGARI.test(ch) ? "hi" : LATIN.test(ch) ? "en" : null;
    if (next && lang && next !== lang) {
      runs.push([lang, buf]);
      buf = "";
    }
    if (next) lang = next;
    buf += ch;
  }
  if (buf.trim()) runs.push([lang || "en", buf]);
  return runs.filter(([, t]) => t.trim());
}

function browserSpeak(text) {
  if (!("speechSynthesis" in window)) throw new Error("This browser cannot speak text.");
  const voices = window.speechSynthesis.getVoices();
  const pick = (code) => voices.find((v) => v.lang === code) || voices.find((v) => v.lang.startsWith(code.slice(0, 2)));
  const runs = splitByScript(text);
  runs.forEach(([lang, chunk], i) => {
    const u = new SpeechSynthesisUtterance(chunk);
    u.lang = lang === "hi" ? "hi-IN" : "en-IN";
    const voice = pick(u.lang);
    if (voice) u.voice = voice;
    if (i === runs.length - 1) u.onend = () => stopSpeaking();
    window.speechSynthesis.speak(u);
  });
}
