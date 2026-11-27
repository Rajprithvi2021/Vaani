import { api } from "./api.js";
import { LiveRecorder } from "./recorder.js";
import { speak, stopSpeaking } from "./speech.js";

// ------------------------------------------------------------------ helpers
const $ = (sel) => document.querySelector(sel);

const ICONS = {
  play: '<path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  eraser: '<path d="M4 20h16"/><path d="m14 4 6 6-9 9H7l-3-3z"/>',
};
const icon = (name) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v; // only ever used with our own constant SVGs
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child != null) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function toast(message, kind = "info") {
  const t = el("div", { class: `toast ${kind}` }, message);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "error" ? 6000 : 3200);
}

const LANG_LABELS = { "hi-en": "Hindi + English", hi: "Hindi", en: "English" };
const SOURCE_LABELS = { gemini: "Gemini Live", whisper: "Whisper (local)", manual: "Manual" };
const fmtDuration = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const fmtDate = (iso) =>
  new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const langBadge = (lang) => el("span", { class: `badge lang-${lang}` }, LANG_LABELS[lang] || lang);

// Detect the language of live text the same way the server does (script-based).
function detectLang(text) {
  const deva = (text.match(/[ऀ-ॿ]/g) || []).length;
  const latin = (text.match(/[A-Za-z]/g) || []).length;
  if (deva && latin && Math.min(deva, latin) / (deva + latin) >= 0.08) return "hi-en";
  return deva > latin ? "hi" : "en";
}

// ------------------------------------------------------------------ routing
function showView(name) {
  const view = name === "history" ? "history" : "live";
  for (const v of ["live", "history"]) $(`#view-${v}`).hidden = v !== view;
  document.querySelectorAll(".tab").forEach((t) => {
    if (t.dataset.view === view) t.setAttribute("aria-current", "page");
    else t.removeAttribute("aria-current");
  });
  if (view === "history") loadHistory();
}
window.addEventListener("hashchange", () => showView(location.hash.slice(1)));

// ------------------------------------------------------------------ engine status
async function loadHealth() {
  const box = $("#engine-status");
  try {
    const h = await api.health();
    const name = SOURCE_LABELS[h.stt.provider] || h.stt.provider;
    box.classList.add(h.stt.configured ? "ok" : "warn");
    box.querySelector(".engine-label").textContent = h.stt.configured
      ? `${name} · ${h.stt.model}`
      : `${name} · API key missing`;
    box.title = `Speech-to-text: ${h.stt.model}\nText-to-speech: ${h.tts.available ? "Piper (open source)" : "browser voices"}\nDatabase: ${h.database}`;
  } catch {
    box.classList.add("warn");
    box.querySelector(".engine-label").textContent = "Server unreachable";
  }
}

// ------------------------------------------------------------------ live view
const recorder = new LiveRecorder();
const live = { committed: "", interim: "", startedAt: 0, maxSeconds: 600, timer: null, savedId: null };

const recordBtn = $("#record-btn");
const recState = $("#rec-state");

function renderTranscript() {
  const box = $("#transcript");
  const text = live.committed;
  const recording = recorder.state === "recording" || recorder.state === "finishing";
  box.replaceChildren();
  if (!text && !live.interim && !recording) {
    box.append(el("p", { class: "placeholder", html: "Press <strong>Start speaking</strong> and talk. Words appear here as you say them — in Hindi, English or both." }));
  } else {
    const p = el("p", { style: "margin:0" }, el("span", { class: "committed" }, text));
    if (live.interim) p.append(el("span", { class: "interim" }, (text ? " " : "") + live.interim));
    if (recording) p.append(el("span", { class: "caret", "aria-hidden": "true" }));
    box.append(p);
    box.scrollTop = box.scrollHeight;
  }
  const full = `${text} ${live.interim}`.trim();
  const badge = $("#live-lang");
  badge.hidden = !full;
  if (full) {
    const lang = detectLang(full);
    badge.className = `badge lang-${lang}`;
    badge.textContent = LANG_LABELS[lang];
  }
  const hasText = Boolean(text);
  $("#live-copy").disabled = !hasText;
  $("#live-speak").disabled = !hasText || recording;
  $("#live-clear").disabled = !hasText || recording;
}

function setRecState(text, cls = "") {
  recState.textContent = text;
  recState.className = `rec-state ${cls}`;
}

recorder.addEventListener("state", ({ detail: { state } }) => {
  recordBtn.classList.toggle("recording", state === "recording");
  recordBtn.setAttribute("aria-pressed", String(state === "recording"));
  recordBtn.disabled = state === "connecting" || state === "finishing";
  recordBtn.querySelector(".record-label").textContent =
    { idle: "Start speaking", connecting: "Connecting…", recording: "Stop", finishing: "Saving…" }[state];
  $("#language").disabled = $("#title").disabled = state !== "idle";
  if (state === "connecting") setRecState("Connecting to speech engine…");
  if (state === "recording") setRecState("Listening", "live");
  if (state === "finishing") setRecState("Finalising last words…");
  if (state === "idle") {
    clearInterval(live.timer);
    live.interim = "";
    if (!recState.classList.contains("error")) setRecState(live.savedId ? "Saved" : "Ready");
  }
  renderTranscript();
});

recorder.addEventListener("ready", ({ detail }) => {
  live.maxSeconds = detail.maxSeconds || 600;
  live.startedAt = performance.now();
  clearInterval(live.timer);
  live.timer = setInterval(() => {
    const elapsed = (performance.now() - live.startedAt) / 1000;
    $("#rec-timer").textContent = fmtDuration(elapsed);
    if (elapsed >= live.maxSeconds) recorder.stop();
  }, 250);
});
recorder.addEventListener("interim", ({ detail }) => {
  live.interim = detail.text;
  renderTranscript();
});
recorder.addEventListener("final", ({ detail }) => {
  live.committed = detail.transcript;
  live.interim = "";
  renderTranscript();
});
recorder.addEventListener("saved", ({ detail: { transcription } }) => {
  live.savedId = transcription.id;
  live.committed = transcription.text;
  const banner = $("#saved-banner");
  banner.replaceChildren(
    el("span", {}, `Saved “${transcription.title}” · ${transcription.word_count} words · ${transcription.language_label}`),
    el("a", { href: "#history" }, "View history →"),
  );
  banner.hidden = false;
  toast("Transcription saved");
});
recorder.addEventListener("empty", () => toast("Nothing was recognised, so nothing was saved."));
recorder.addEventListener("info", ({ detail }) => toast(detail.message));
recorder.addEventListener("error", ({ detail }) => {
  setRecState(detail.message, "error");
  toast(detail.message, "error");
});

recordBtn.addEventListener("click", async () => {
  if (recorder.state === "recording") return recorder.stop();
  if (recorder.state !== "idle") return;
  stopSpeaking();
  live.committed = "";
  live.interim = "";
  live.savedId = null;
  $("#saved-banner").hidden = true;
  $("#rec-timer").textContent = "0:00";
  setRecState("Starting…");
  try {
    await recorder.start({ language: $("#language").value, title: $("#title").value.trim() });
    drawMeter();
  } catch (err) {
    setRecState(err.message, "error");
    toast(err.message, "error");
  }
});

$("#live-copy").innerHTML = icon("copy");
$("#live-clear").innerHTML = icon("eraser");
$("#live-copy").addEventListener("click", async () => {
  await navigator.clipboard.writeText(live.committed);
  toast("Copied to clipboard");
});
$("#live-clear").addEventListener("click", () => {
  live.committed = "";
  live.savedId = null;
  $("#saved-banner").hidden = true;
  $("#title").value = "";
  setRecState("Ready");
  renderTranscript();
});
setupSpeakButton($("#live-speak"), () => ({ id: live.savedId, text: live.committed }));

// Live level meter: mirrored frequency bars while recording, a calm baseline otherwise.
const meter = $("#meter");
function drawMeter() {
  const ctx = meter.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = (meter.width = meter.clientWidth * dpr);
  const h = (meter.height = meter.clientHeight * dpr);
  const styles = getComputedStyle(document.documentElement);
  const accent = styles.getPropertyValue("--accent").trim();
  const rec = styles.getPropertyValue("--rec").trim();
  const bars = 48;
  const data = new Uint8Array(256);
  const gap = 3 * dpr;
  const bw = (w - gap * (bars - 1)) / bars;

  function frame() {
    ctx.clearRect(0, 0, w, h);
    const analyser = recorder.analyser;
    if (analyser) analyser.getByteFrequencyData(data);
    ctx.fillStyle = recorder.state === "recording" ? rec : accent;
    ctx.globalAlpha = 0.35;
    for (let i = 0; i < bars; i++) {
      const mirror = Math.abs(i - bars / 2) / (bars / 2); // 0 at centre, 1 at the edges
      const bin = Math.floor(mirror * 90) + 2;             // speech energy lives in the low bins
      const v = analyser ? data[bin] / 255 : 0;
      const bh = Math.max(3 * dpr, v * h * 0.9 * (1 - mirror * 0.5));
      const x = i * (bw + gap);
      ctx.beginPath();
      ctx.roundRect(x, h - bh, bw, bh, Math.min(bw / 2, 4 * dpr));
      ctx.fill();
    }
    if (recorder.state !== "idle") requestAnimationFrame(frame);
    else ctx.clearRect(0, 0, w, h);
  }
  requestAnimationFrame(frame);
}

// ------------------------------------------------------------------ text-to-speech buttons
function setupSpeakButton(button, getTarget) {
  button.innerHTML = icon("play");
  button.addEventListener("click", async () => {
    if (button.classList.contains("active")) return stopSpeaking();
    const target = getTarget();
    if (!target.text && !target.id) return;
    button.classList.add("active");
    button.innerHTML = icon("stop");
    button.title = "Stop";
    const reset = () => {
      button.classList.remove("active");
      button.innerHTML = icon("play");
      button.title = "Read aloud";
    };
    try {
      const engine = await speak(target, reset);
      if (engine === "browser") toast("Using the browser's voice (Piper voices not installed).");
    } catch (err) {
      reset();
      toast(err.message, "error");
    }
  });
}

// ------------------------------------------------------------------ history view
const history = { q: "", language: "", offset: 0, limit: 10, total: 0, items: [] };

async function loadHistory() {
  await Promise.all([loadStats(), loadList()]);
}

async function loadStats() {
  try {
    const s = await api.stats();
    $('[data-stat="total"]').textContent = s.total.toLocaleString();
    $('[data-stat="minutes"]').textContent = (s.total_duration_seconds / 60).toFixed(1);
    $('[data-stat="words"]').textContent = s.total_words.toLocaleString();
    const box = $('[data-stat="langs"]');
    const max = Math.max(1, ...Object.values(s.by_language));
    box.replaceChildren(
      ...["hi-en", "hi", "en"].map((lang) => {
        const n = s.by_language[lang] || 0;
        return el("div", { class: "lang-row" },
          el("span", {}, LANG_LABELS[lang]),
          el("div", { class: "lang-track" }, el("div", { class: "lang-fill", style: `width:${(n / max) * 100}%` })),
          el("span", {}, n));
      }),
    );
  } catch (err) {
    toast(`Could not load stats: ${err.message}`, "error");
  }
}

async function loadList() {
  const list = $("#list");
  try {
    const page = await api.list(history);
    history.total = page.total;
    history.items = page.items;
    if (page.items.length === 0 && history.offset > 0) {
      history.offset = Math.max(0, history.offset - history.limit);
      return loadList();
    }
    renderList();
  } catch (err) {
    list.replaceChildren(el("div", { class: "empty" }, el("strong", {}, "Could not load transcriptions"), err.message));
  }
}

function highlight(text, q) {
  if (!q) return [text];
  const out = [];
  const lower = text.toLowerCase();
  const needle = q.toLowerCase();
  let i = 0;
  for (let j = lower.indexOf(needle); j !== -1; j = lower.indexOf(needle, i)) {
    out.push(text.slice(i, j), el("mark", {}, text.slice(j, j + needle.length)));
    i = j + needle.length;
  }
  out.push(text.slice(i));
  return out;
}

function renderList() {
  const list = $("#list");
  const { items, total, offset, limit, q, language } = history;
  if (items.length === 0) {
    list.replaceChildren(
      el("div", { class: "empty" },
        el("strong", {}, q || language ? "No matching transcriptions" : "No transcriptions yet"),
        q || language ? "Try a different search or filter." : "Record something on the Live tab and it will appear here."),
    );
  } else {
    list.replaceChildren(...items.map(renderItem));
  }
  $("#page-info").textContent = total ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}` : "";
  $("#prev-page").disabled = offset === 0;
  $("#next-page").disabled = offset + limit >= total;
}

function renderItem(t) {
  const play = el("button", { class: "icon-btn", type: "button", title: "Read aloud", "aria-label": `Read “${t.title}” aloud` });
  setupSpeakButton(play, () => ({ id: t.id, text: t.text }));
  return el("article", { class: "item" },
    el("div", { class: "item-main", onclick: () => openEditor(t), title: "Open" },
      el("div", { class: "item-title" }, el("span", {}, ...highlight(t.title, history.q)), langBadge(t.language)),
      el("p", { class: "item-text" }, ...highlight(t.text || "(empty)", history.q)),
      el("div", { class: "item-meta" },
        el("span", {}, fmtDate(t.created_at)),
        t.duration_seconds ? el("span", {}, `⏱ ${fmtDuration(t.duration_seconds)}`) : null,
        el("span", {}, `${t.word_count} words`),
        el("span", {}, SOURCE_LABELS[t.source] || t.source)),
    ),
    el("div", { class: "item-actions" },
      play,
      el("button", { class: "icon-btn", type: "button", title: "Edit", "aria-label": `Edit “${t.title}”`, html: icon("edit"), onclick: () => openEditor(t) }),
      el("button", { class: "icon-btn", type: "button", title: "Delete", "aria-label": `Delete “${t.title}”`, html: icon("trash"), onclick: () => confirmDelete(t) }),
    ),
  );
}

let searchTimer;
$("#search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    history.q = e.target.value.trim();
    history.offset = 0;
    loadList();
  }, 250);
});
$("#filter-language").addEventListener("change", (e) => {
  history.language = e.target.value;
  history.offset = 0;
  loadList();
});
$("#prev-page").addEventListener("click", () => {
  history.offset = Math.max(0, history.offset - history.limit);
  loadList();
});
$("#next-page").addEventListener("click", () => {
  history.offset += history.limit;
  loadList();
});

// ------------------------------------------------------------------ create / edit / delete
const editor = $("#editor");
const form = $("#editor-form");
let editing = null; // null = creating

function openEditor(t = null) {
  editing = t;
  $("#editor-title").textContent = t ? "Edit transcription" : "New transcription";
  form.elements.title.value = t ? t.title : "";
  form.elements.text.value = t ? t.text : "";
  form.elements.language.value = t ? t.language : "";
  $("#editor-delete").hidden = !t;
  $("#editor-meta").textContent = t
    ? `Created ${fmtDate(t.created_at)} · updated ${fmtDate(t.updated_at)} · ${SOURCE_LABELS[t.source] || t.source}${t.model ? ` (${t.model})` : ""}`
    : "Type or paste text. The language is detected automatically unless you choose one.";
  editor.showModal();
  form.elements[t ? "text" : "title"].focus();
}

editor.querySelector('[data-icon="x"]').innerHTML = icon("x");

form.addEventListener("submit", async (e) => {
  if (e.submitter && e.submitter.value !== "save") return; // Cancel / close
  e.preventDefault();
  const data = {
    title: form.elements.title.value.trim(),
    text: form.elements.text.value,
    language: form.elements.language.value || null,
  };
  if (!data.title) return form.elements.title.focus();
  try {
    if (editing) {
      // Send the language only if the user changed it; otherwise the server re-detects it from the text.
      if (!data.language || data.language === editing.language) delete data.language;
      await api.update(editing.id, data);
      toast("Changes saved");
    } else {
      await api.create(data);
      toast("Transcription created");
    }
    editor.close();
    loadHistory();
  } catch (err) {
    toast(err.message, "error");
  }
});

$("#editor-delete").addEventListener("click", () => {
  const t = editing;
  editor.close();
  if (t) confirmDelete(t);
});

const confirmDialog = $("#confirm");
function confirmDelete(t) {
  $("#confirm-text").textContent = `“${t.title}” will be permanently removed from the database.`;
  confirmDialog.returnValue = "";
  confirmDialog.showModal();
  confirmDialog.addEventListener("close", async function onClose() {
    confirmDialog.removeEventListener("close", onClose);
    if (confirmDialog.returnValue !== "confirm") return;
    try {
      await api.remove(t.id);
      toast("Transcription deleted");
      if (live.savedId === t.id) live.savedId = null;
      loadHistory();
    } catch (err) {
      toast(err.message, "error");
    }
  });
}

$("#new-btn").addEventListener("click", () => openEditor(null));

// ------------------------------------------------------------------ boot
loadHealth();
renderTranscript();
showView(location.hash.slice(1) || "live");
