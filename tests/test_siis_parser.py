"""SIIS text becomes sections and imperative steps, and nothing else."""

import re

import pytest

from app.services.siis_parser import clean_siis_text, embedded_title, extract_steps, is_imperative, parse_sections


def test_clean_removes_category_prefix_urls_and_markdown_links():
    raw = "Smartphone,Tablet Title ( Smartphone,Tablet): ## Head\nTap https://x.example/a now [link](http://b.example) done www.c.example"
    cleaned = clean_siis_text(raw)
    assert cleaned.startswith("## Head")
    assert "http" not in cleaned and "www." not in cleaned
    assert "link" in cleaned


def test_navigation_chain_becomes_separate_steps():
    body = "Navigate to and open Settings. Tap Apps, select your email app."
    assert extract_steps(body) == ["Navigate to Settings.", "Tap Apps.", "Select your email app."]


def test_leading_condition_is_dropped_and_then_splits():
    body = "On devices with a Power button: Press and hold the Power button, then tap Restart."
    assert extract_steps(body) == ["Press and hold the Power button.", "Tap Restart."]


def test_you_can_is_turned_into_an_instruction():
    assert extract_steps("You can schedule a walk-in or mail-in repair to fix your cracked screen.") == [
        "Schedule a walk-in or mail-in repair to fix your cracked screen."
    ]


@pytest.mark.parametrize("sentence", [
    "The LDI should normally appear solid white.",
    "If the device has been exposed to moisture, the LDI will appear solid pink.",
    "If your screen protector is peeling, please remove it.",
    "Let's go through some steps to help resolve this.",
])
def test_non_instructions_are_not_steps(sentence):
    assert extract_steps(sentence) == []


def test_parse_sections_strips_numbering_and_uses_title_for_intro():
    content = "Cat Title ( Cat): Tap Settings now.\n## Step 2: Verify Your Phone's Internet Connection\nTap Wi-Fi.\n## 3. Charger Issues\nTry a different charger."
    sections = parse_sections(content, title="Title")
    assert [s.heading for s in sections] == ["Title", "Verify Your Phone's Internet Connection", "Charger Issues"]
    assert sections[1].steps == ("Tap Wi-Fi.",)


def test_parse_sections_stops_at_the_first_garbled_section():
    garbled = "enteryourcurrentpinpasswordorpatternandthentapsomething"
    content = f"Cat Title ( Cat): Tap Settings now.\n## Good\nTap Display.\n## Broken\n{garbled}\n## After\nTap Bluetooth."
    assert [s.heading for s in parse_sections(content, title="Title")] == ["Title", "Good"]


def test_is_imperative():
    assert is_imperative("Tap Display.") and is_imperative("go to Settings")
    assert not is_imperative("The screen is blank.")


def test_real_email_article_yields_clean_steps(siis_rows):
    row = next(r for r in siis_rows if r["id"] == "row_1")
    sections = parse_sections(row["siis_response"]["content"], row["siis_response"]["title"])
    clear = next(s for s in sections if "Cache and Data" in s.heading)
    assert "Tap Storage." in clear.steps
    for section in sections:
        for step in section.steps:
            assert step.endswith(".") and not re.search(r"https?://|www\.", step)


def test_real_garbled_article_keeps_only_the_clean_leading_part(siis_rows):
    row = next(r for r in siis_rows if r["id"] == "row_3")
    sections = parse_sections(row["siis_response"]["content"], row["siis_response"]["title"])
    assert len(sections) == 1
    assert "Fingerprint" not in sections[0].body


def test_embedded_title_recovers_the_articles_own_title_from_its_prefix():
    content = "Smartphone,Others Mobile Battery draining quickly on your Galaxy phone ( Smartphone,Others Mobile): body text here."
    assert embedded_title(content) == "Battery draining quickly on your Galaxy phone"


def test_embedded_title_handles_a_category_name_with_an_internal_space():
    content = "Smartphone,Others Mobile,Tablet Camera app closes or will not open ( Smartphone,Others Mobile,Tablet): body."
    assert embedded_title(content) == "Camera app closes or will not open"


def test_embedded_title_is_none_without_the_repeated_category_prefix():
    assert embedded_title("Just some plain text with no category prefix at all.") is None


def test_embedded_title_matches_every_official_row(siis_rows):
    for row in siis_rows:
        siis = row["siis_response"]
        assert embedded_title(siis["content"]) == siis["title"], row["id"]
