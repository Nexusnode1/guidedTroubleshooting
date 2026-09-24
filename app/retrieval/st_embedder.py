"""Sentence-transformers embedder: a Hugging Face model id or a local model directory.

A model you fine-tune yourself and save with ``model.save("models/my-embedder")``
loads through exactly this class, so swapping it in is only a config change:
``EMBEDDING_MODEL=models/my-embedder``.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.retrieval.embeddings import EmbeddingModel, HashEmbeddingModel

HASH_MODEL_ID = "hash"


class SentenceTransformerEmbedding:
    """Unit-length sentence embeddings from a sentence-transformers model."""

    def __init__(self, model_name_or_path: str, device: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer  # heavy import, kept lazy

        self.name = model_name_or_path
        self._model = SentenceTransformer(model_name_or_path, device=device)

    def embed(self, text: str) -> list[float]:
        """Embed one text."""
        return self.embed_many([text])[0]

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed several texts in one batch, preserving order."""
        vectors = self._model.encode(
            list(texts), normalize_embeddings=True, batch_size=64, show_progress_bar=False
        )
        return [vector.tolist() for vector in vectors]


def load_embedder(spec: str) -> EmbeddingModel:
    """Return the embedder named by ``spec``: ``"hash"``, a model id, or a local directory."""
    if spec.strip().lower() == HASH_MODEL_ID:
        model = HashEmbeddingModel()
        model.name = HASH_MODEL_ID  # type: ignore[attr-defined]
        return model
    return SentenceTransformerEmbedding(spec)
