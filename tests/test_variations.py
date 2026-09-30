import pytest

from app.services.variations import generate_variations, normalize_query, searchable_text, strip_urls


def test_variations_are_eight_to_ten_distinct_and_deterministic():
    query = "My Galaxy S22 screen turns completely blank or white"
    first = generate_variations(query, "Blank Display")
    assert 8 <= len(first) <= 10
    assert len(set(first)) == len(first)
    assert first == generate_variations(query, "Blank Display")
    assert first[0] == query


def test_variations_span_registers():
    joined = " | ".join(generate_variations("phone swipe gestures wrong direction after app install", "Swipe Navigation"))
    for marker in ("annoying", "How do I fix", "Why does", "Troubleshoot swipe navigation"):
        assert marker in joined


def test_variations_contain_no_urls():
    assert not any("http" in v or "www." in v for v in generate_variations("wifi keeps dropping", "Wi-Fi"))


@pytest.mark.parametrize(
    "query",
    [
        "my screen is black see http://example.com/pic for a photo",
        "HTTPS://EXAMPLE.COM/A my wifi keeps dropping",
        "wifi keeps dropping, see www.example.com/help",
        "wifi keeps dropping like in [this post](https://example.com/p)",
        "open voiceassist://masked/act/0000 when wifi keeps dropping",
    ],
)
def test_urls_in_the_query_never_reach_a_variation(query):
    variations = generate_variations(query, "Wi-Fi")
    assert 8 <= len(variations) <= 10 and len(set(variations)) == len(variations)
    for text in variations:
        lowered = text.lower()
        assert "://" not in lowered and "www." not in lowered and "](" not in lowered
        assert "http" not in lowered and "example" not in lowered and "voiceassist" not in lowered


def test_strip_urls_leaves_text_without_urls_untouched():
    for text in ("My Nexa X1 screen is black  (or blue), it won't start.", "wi-fi drops: every 5 min", "a [note] (aside)"):
        assert strip_urls(text) == text
    assert strip_urls("see https://example.com/a now") == "see now"
    assert strip_urls("like [this post](https://example.com/p) says") == "like this post says"


def test_official_queries_generate_the_same_variations_as_before_url_stripping(siis_rows):
    for row in siis_rows:
        query = row["original_query"]
        assert strip_urls(query) == query
        assert generate_variations(query, "Device Issue")[0] == query.strip()[:1].upper() + query.strip()[1:]


def test_searchable_text_is_empty_for_blank_punctuation_and_bare_urls():
    for text in ("   ", "???", "https://example.com/x", "www.example.com", "please"):
        assert searchable_text(text) == ""
    assert searchable_text("Screen is BLACK, see https://example.com") == "screen is black see"


def test_normalize_query_is_lowercase_and_stable():
    assert normalize_query("Phone Swipe GESTURES wrong direction") == "phone swipe gestures wrong direction"
