"""Replaceable embedding service used by dense retrieval."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.retrieval.embeddings import EmbeddingModel, HashEmbeddingModel


class EmbeddingService:
    """Small adapter that keeps the embedding model replaceable."""

    def __init__(self, model: EmbeddingModel | None = None) -> None:
        self.model = model or HashEmbeddingModel()

    def embed(self, text: str) -> list[float]:
        """Embed one text value."""
        return self.model.embed(text)

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        """Embed text values in input order."""
        return [self.embed(text) for text in texts]

    @property
    def dimension(self) -> int | None:
        """Expose a model dimension when the provider declares one."""
        value = getattr(self.model, "dimension", None)
        return value if isinstance(value, int) else None
