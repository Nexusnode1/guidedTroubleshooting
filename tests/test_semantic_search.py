"""Tests using clearly labelled in-memory TEST DATA, not official catalog data."""

import pytest

from app.retrieval.embeddings import HashEmbeddingModel, build_embeddings, cosine_similarity
from app.retrieval.semantic_search import SemanticSearcher, search


TEST_CATALOG = [
    {"id": "battery-test", "text": "phone battery drains quickly"},
    {"id": "camera-test", "text": "camera cannot open"},
    {"id": "network-test", "text": "wifi connection problem"},
]


def test_embeddings_are_deterministic_and_normalized() -> None:
    """The fallback produces repeatable vectors without external services."""
    model = HashEmbeddingModel()
    first = model.embed("phone battery")
    assert first == model.embed("phone battery")
    assert cosine_similarity(first, first) == pytest.approx(1.0)
    assert len(build_embeddings(["phone", "camera"], model=model)) == 2


def test_search_ranks_matching_catalog_entry() -> None:
    """A query ranks the supplied matching TEST DATA entry first."""
    results = search("battery dying fast", TEST_CATALOG)
    assert results
    assert results[0].entry["id"] == "battery-test"
    assert results[0].score > 0


def test_search_preserves_entries_and_returns_scores() -> None:
    """Search returns original mappings and numeric similarity scores."""
    results = SemanticSearcher(TEST_CATALOG).search("camera issue")
    assert results[0].entry is TEST_CATALOG[1]
    assert isinstance(results[0].score, float)


def test_search_validates_inputs() -> None:
    """Empty queries and invalid limits fail clearly."""
    index = SemanticSearcher(TEST_CATALOG)
    with pytest.raises(ValueError):
        index.search(" ")
    with pytest.raises(ValueError):
        index.search("camera", top_k=0)


def test_entry_without_searchable_text_is_rejected() -> None:
    """The index does not invent text for an unknown catalog shape."""
    with pytest.raises(ValueError, match="searchable text"):
        SemanticSearcher([{"id": "no-text"}])
