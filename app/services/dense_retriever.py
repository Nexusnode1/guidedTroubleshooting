"""Dense embedding retrieval over catalog metadata."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.models.retrieval import DenseResult
from app.retrieval.embeddings import EmbeddingModel, cosine_similarity
from app.services.bm25_retriever import DEFAULT_METADATA_FIELDS, metadata_text
from app.services.embedding_service import EmbeddingService


class DenseRetriever:
    """In-memory dense index with an injectable embedding provider."""

    def __init__(
        self,
        catalog: Iterable[Mapping[str, Any]],
        model: EmbeddingModel | None = None,
        metadata_fields: Sequence[str] = DEFAULT_METADATA_FIELDS,
    ) -> None:
        self.embedding_service = EmbeddingService(model)
        self._entries = list(catalog)
        self._vectors = [
            self.embedding_service.embed(metadata_text(entry, metadata_fields))
            for entry in self._entries
        ]

    def search(self, query: str, top_k: int = 5) -> list[DenseResult]:
        """Return top catalog entries ranked by cosine similarity."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        vector = self.embedding_service.embed(query)
        ranked = [
            DenseResult(entry, float(cosine_similarity(vector, stored)))
            for entry, stored in zip(self._entries, self._vectors)
        ]
        return [
            result
            for _, result in sorted(
                enumerate(ranked), key=lambda pair: (-pair[1].score, pair[0])
            )[:top_k]
        ]
