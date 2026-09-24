"""Dense retrieval tests using synthetic TEST DATA."""

from app.services.dense_retriever import DenseRetriever


CATALOG = [
    {"id": "battery", "description": "battery drains quickly"},
    {"id": "camera", "description": "camera cannot open"},
]


def test_dense_returns_similarity_scores_and_original_entries() -> None:
    """Dense results retain identity and expose numeric scores."""
    results = DenseRetriever(CATALOG).search("battery draining", top_k=2)
    assert results[0].entry is CATALOG[0]
    assert isinstance(results[0].score, float)


def test_dense_accepts_replaceable_model() -> None:
    """A tiny deterministic provider can replace the fallback model."""
    class Model:
        def embed(self, text: str) -> list[float]:
            return [1.0, 0.0] if "battery" in text else [0.0, 1.0]

    results = DenseRetriever(CATALOG, model=Model()).search("battery", top_k=1)
    assert results[0].entry["id"] == "battery"
