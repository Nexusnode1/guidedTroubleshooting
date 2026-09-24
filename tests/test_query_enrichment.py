"""Tests for deterministic query enrichment (no official dataset was supplied)."""

import pytest

from app.services.query_enrichment import (
    QueryEnricher,
    enrich_query,
    extract_core_intent,
    normalize_query,
)


def test_normalize_formal_and_casual_query() -> None:
    """Courtesy and question phrasing do not change the underlying intent."""
    assert normalize_query("  Hello, CAN you help me with Wi-Fi!!! ") == "wi-fi"
    assert normalize_query("What do I do if my WiFi won't connect?") == "my wifi will not connect"


def test_normalize_typo_and_keyword_query() -> None:
    """Common typos are corrected while keyword-only input remains usable."""
    assert normalize_query("wify conectivty") == "wifi connectivity"
    assert extract_core_intent("my wifi will not connect") == "wifi will not connect"


def test_enrichment_preserves_original_and_generates_variations() -> None:
    """The exact input is retained and generic variations are deduplicated."""
    raw = "Ugh!!! my TV wont conect :("
    result = enrich_query(raw)
    assert result.original_query == raw
    assert result.normalized_query == "ugh my tv will not connect"
    assert result.core_intent == "tv will not connect"
    assert result.variations[0] == result.normalized_query
    assert len(result.variations) == len(set(result.variations))
    assert all("deeplink" not in variation for variation in result.variations)


def test_empty_query_is_rejected() -> None:
    """Empty input cannot produce an intent."""
    with pytest.raises(ValueError):
        QueryEnricher().enrich("   ")
