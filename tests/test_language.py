import pytest

from app.language import detect_language, split_by_script


@pytest.mark.parametrize("text, expected", [
    ("Please send the report by Friday.", "en"),
    ("मैं कल दिल्ली जा रहा हूँ।", "hi"),
    ("आज की meeting cancel हो गई है", "hi-en"),
    ("Kal ki meeting teen baje hai, please time pe aana", "hi-en"),
    ("Main yahan hoon aur tum kahan ho?", "hi-en"),
    ("I like the main course", "en"),
    ("", "en"),
    ("12345 !!!", "en"),
])
def test_detect_language(text, expected):
    assert detect_language(text) == expected


def test_single_foreign_glyph_does_not_flip_language():
    assert detect_language("This is a long English sentence about the project plan ॐ") == "en"


def test_split_by_script_keeps_punctuation_with_runs():
    runs = split_by_script("आज की meeting cancel है, okay?")
    assert runs == [("hi", "आज की"), ("en", "meeting cancel"), ("hi", "है,"), ("en", "okay?")]


def test_split_by_script_plain_text():
    assert split_by_script("Hello world.") == [("en", "Hello world.")]
    assert split_by_script("   ") == []
