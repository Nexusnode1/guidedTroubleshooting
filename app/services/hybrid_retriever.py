"""Deterministic fusion of BM25 and dense retrieval results."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.models.retrieval import HybridResult
from app.retrieval.embeddings import EmbeddingModel
from app.services.bm25_retriever import BM25Retriever, DEFAULT_METADATA_FIELDS
from app.services.dense_retriever import DenseRetriever


class HybridRetriever:
    """Combine BM25 and dense scores with configurable weighted fusion."""

    def __init__(
        self,
        catalog: Iterable[Mapping[str, Any]],
        *,
        bm25_weight: float = 0.5,
        dense_weight: float = 0.5,
        model: EmbeddingModel | None = None,
        metadata_fields: Sequence[str] = DEFAULT_METADATA_FIELDS,
    ) -> None:
        if bm25_weight < 0 or dense_weight < 0 or bm25_weight + dense_weight == 0:
            raise ValueError("retrieval weights must be non-negative and not both zero")
        entries = list(catalog)
        self.bm25_weight = bm25_weight / (bm25_weight + dense_weight)
        self.dense_weight = dense_weight / (bm25_weight + dense_weight)
        self.bm25 = BM25Retriever(entries, metadata_fields=metadata_fields)
        self.dense = DenseRetriever(entries, model=model, metadata_fields=metadata_fields)

    @staticmethod
    def _normalize(scores: dict[int, float]) -> dict[int, float]:
        """Min-max normalize one score family while preserving zero-only sets."""
        if not scores:
            return {}
        minimum, maximum = min(scores.values()), max(scores.values())
        if maximum == minimum:
            return {key: (1.0 if maximum > 0 else 0.0) for key in scores}
        return {key: (value - minimum) / (maximum - minimum) for key, value in scores.items()}

    def search(self, query: str, top_k: int = 5) -> list[HybridResult]:
        """Return fused results while retaining individual BM25/dense scores."""
        if top_k < 1:
            raise ValueError("top_k must be positive")
        bm25 = self.bm25.search(query, top_k=max(top_k, len(self.bm25._documents)))
        dense = self.dense.search(query, top_k=max(top_k, len(self.dense._entries)))
        entry_ids = {id(result.entry): result.entry for result in [*bm25, *dense]}
        bm25_scores = self._normalize({id(result.entry): result.score for result in bm25})
        dense_scores = self._normalize({id(result.entry): result.score for result in dense})
        fused = [
            HybridResult(
                entry,
                next((result.score for result in bm25 if id(result.entry) == key), 0.0),
                next((result.score for result in dense if id(result.entry) == key), 0.0),
                self.bm25_weight * bm25_scores.get(key, 0.0)
                + self.dense_weight * dense_scores.get(key, 0.0),
            )
            for key, entry in entry_ids.items()
        ]
        return sorted(fused, key=lambda result: result.hybrid_score, reverse=True)[:top_k]
