from app.services.variations import generate_variations, normalize_query


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


def test_normalize_query_is_lowercase_and_stable():
    assert normalize_query("Phone Swipe GESTURES wrong direction") == "phone swipe gestures wrong direction"
