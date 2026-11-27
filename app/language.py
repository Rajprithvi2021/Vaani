"""Lightweight language tagging for Hindi, English and code-mixed (Hinglish) text.

Speech engines write Hindi in Devanagari, but code-mixed speech often comes back with
English words in Latin script and sometimes with Hindi words romanised ("kya", "nahi").
We tag a transcript by script, plus a small lexicon of very common romanised Hindi words.
"""
import re

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")
WORD = re.compile(r"[A-Za-z]+")

# Frequent romanised Hindi function words. Kept short on purpose: words that are also
# common English words ("main", "to", "the") are left out to avoid false positives.
ROMAN_HINDI = {
    "hai", "hain", "hoon", "hun", "tha", "thi", "kya", "kyun", "kyon", "nahi", "nahin", "mein",
    "mera", "meri", "mere", "tera", "teri", "tum", "tumhara", "aap", "aapka", "hum", "humko",
    "mujhe", "kaise", "kaisa", "kahan", "kab", "accha", "acha", "achha", "theek", "thik", "bahut",
    "abhi", "kal", "aaj", "aur", "lekin", "kyunki", "matlab", "yaar", "bhai", "chalo", "karna",
    "karo", "karte", "raha", "rahi", "rahe", "gaya", "gayi", "wala", "wali", "sab", "kuch",
    "haan", "bolo", "dekho", "samjha", "pata", "zaroor", "jaldi", "ghar",
}

LANGUAGE_LABELS = {"en": "English", "hi": "Hindi", "hi-en": "Hindi + English"}


def detect_language(text: str) -> str:
    """Return "hi", "en" or "hi-en" for a transcript."""
    deva = len(DEVANAGARI.findall(text))
    latin = len(LATIN.findall(text))
    if deva == 0 and latin == 0:
        return "en"
    if deva and latin:
        # Ignore a stray brand name or a single Devanagari glyph.
        minority = min(deva, latin) / (deva + latin)
        if minority >= 0.08:
            return "hi-en"
        return "hi" if deva > latin else _latin_language(text)
    if deva:
        return "hi"
    return _latin_language(text)


def _latin_language(text: str) -> str:
    words = [w.lower() for w in WORD.findall(text)]
    if not words:
        return "en"
    hindi_hits = sum(1 for w in words if w in ROMAN_HINDI)
    if hindi_hits >= 2 and hindi_hits / len(words) >= 0.15:
        return "hi-en"
    return "en"


def split_by_script(text: str) -> list[tuple[str, str]]:
    """Split text into runs of ("hi", devanagari_run) / ("en", latin_run) for text-to-speech.

    Punctuation, digits and spaces stay attached to the run they follow.
    """
    runs: list[tuple[str, str]] = []
    current_lang: str | None = None
    buf: list[str] = []
    for ch in text:
        if DEVANAGARI.match(ch):
            lang = "hi"
        elif LATIN.match(ch):
            lang = "en"
        else:
            buf.append(ch)
            continue
        if current_lang is None:
            current_lang = lang
        elif lang != current_lang:
            runs.append((current_lang, "".join(buf)))
            buf, current_lang = [], lang
        buf.append(ch)
    if buf:
        tail = "".join(buf)
        if current_lang is None:
            current_lang = "en"
        runs.append((current_lang, tail))
    return [(lang, chunk.strip()) for lang, chunk in runs if chunk.strip()]
