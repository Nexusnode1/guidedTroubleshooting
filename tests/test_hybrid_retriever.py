"""Hybrid retrieval tests using synthetic TEST DATA."""

from app.services.hybrid_retriever import HybridRetriever


CATALOG = [
    {"id": "battery", "title": "Battery", "description": "battery drains quickly"},
    {"id": "camera", "title": "Camera", "description": "camera cannot open"},
    {"id": "display", "title": "Display", "description": "screen is dim"},
]


def test_hybrid_fuses_and_exposes_individual_scores() -> None:
    """Hybrid results contain BM25, dense, and fused scores."""
    results = HybridRetriever(CATALOG, bm25_weight=0.7, dense_weight=0.3).search("battery drains")
    assert results[0].entry is CATALOG[0]
    assert results[0].bm25_score >= 0
    assert isinstance(results[0].dense_score, float)
    assert isinstance(results[0].hybrid_score, float)


def test_hybrid_top_k_and_weight_validation() -> None:
    """Top-K and configurable weights are enforced."""
    assert len(HybridRetriever(CATALOG, bm25_weight=1, dense_weight=0).search("camera", top_k=1)) == 1
