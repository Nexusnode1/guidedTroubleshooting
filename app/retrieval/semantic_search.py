"""Rank supplied catalog entries against a troubleshooting query."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.retrieval.embeddings import EmbeddingModel, HashEmbeddingModel, cosine_similarity


@dataclass(frozen=True)
class SearchResult:
    """A catalog entry and its similarity score."""

    entry: Mapping[str, Any]
    score: float


def _searchable_text(entry: Mapping[str, Any], fields: Sequence[str] | None) -> str:
    """Extract catalog text without changing or synthesizing entry fields."""
    candidate_fields = fields or ("text", "title", "name", "description", "query", "intent", "label")
    values = [entry[field] for field in candidate_fields if isinstance(entry.get(field), str)]
    if not values:
        raise ValueError("catalog entry has no supported searchable text field")
    return " ".join(values)


class SemanticSearcher:
    """In-memory ranked search index over supplied catalog mappings."""

    def __init__(
        self,
        catalog: Iterable[Mapping[str, Any]],
        model: EmbeddingModel | None = None,
        text_fields: Sequence[str] | None = None,
    ) -> None:
        self.model = model or HashEmbeddingModel()
        self._entries: list[tuple[Mapping[str, Any], list[float]]] = []
        for entry in catalog:
            if not isinstance(entry, Mapping):
                raise TypeError("catalog entries must be mappings")
            text = _searchable_text(entry, text_fields)
            self._entries.append((entry, self.model.embed(text)))

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Return positive-similarity entries in descending score order."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        query_vector = self.model.embed(query)
        ranked = (
            SearchResult(entry, cosine_similarity(query_vector, vector))
            for entry, vector in self._entries
        )
        return sorted(
            (result for result in ranked if result.score > 0.0),
            key=lambda result: result.score,
            reverse=True,
        )[:top_k]


def search(
    query: str,
    catalog: Iterable[Mapping[str, Any]],
    limit: int = 5,
    model: EmbeddingModel | None = None,
) -> list[SearchResult]:
    """Convenience wrapper for one search over the supplied catalog."""
    return SemanticSearcher(catalog, model=model).search(query, top_k=limit)
