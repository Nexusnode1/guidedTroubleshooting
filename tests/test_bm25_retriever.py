"""BM25 tests using clearly labelled synthetic TEST DATA."""

from app.services.bm25_retriever import BM25Retriever


CATALOG = [
    {"id": "battery", "title": "Battery settings", "description": "battery drains quickly"},
    {"id": "camera", "title": "Camera settings", "description": "camera cannot open"},
    {"id": "display", "title": "Display settings", "description": "screen is dim"},
]


def test_bm25_searches_metadata_and_ranks_match() -> None:
    """Metadata terms rank without considering the URI field."""
    catalog = [*CATALOG]
    catalog[0]["deeplink"] = "masked-battery-uri"
    results = BM25Retriever(catalog).search("battery drains")
    assert results[0].entry is catalog[0]
    assert results[0].score > 0


def test_bm25_does_not_search_uri() -> None:
    """A term found only in a URI cannot create a keyword match."""
    catalog = [{"id": "one", "title": "Battery", "deeplink": "masked-unique-uri"}, {"id": "two", "title": "Camera", "deeplink": "other-uri"}]
    results = BM25Retriever(catalog).search("masked-unique-uri")
    assert all(result.score == 0 for result in results)


def test_bm25_supports_top_k_and_config() -> None:
    """Top-K and BM25 parameters are configurable."""
    results = BM25Retriever(CATALOG, k1=1.2, b=0.4).search("settings", top_k=2)
    assert len(results) == 2
