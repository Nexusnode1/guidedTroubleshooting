"""Small, deterministic embedding interfaces for catalog retrieval.

The official catalog and model requirements are not available in this
workspace. ``HashEmbeddingModel`` is therefore a dependency-free fallback;
it can be replaced by Sentence Transformers or another model without
changing the semantic-search interface.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Sequence
from typing import Protocol


_TOKEN = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")
_STOPWORDS = frozenset(
    "a an and are as at be can do for from has have i if in is it me my of on or "
    "that the this to was were what when where with you".split()
)


class EmbeddingModel(Protocol):
    """Protocol implemented by catalog and query embedding providers."""

    def embed(self, text: str) -> list[float]:
        """Return a numeric vector for ``text``."""


class HashEmbeddingModel:
    """Deterministic hashed bag-of-words embedding for local development."""

    def __init__(self, dimension: int = 2048) -> None:
        if dimension < 32:
            raise ValueError("dimension must be at least 32")
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        """Embed unigrams and adjacent bigrams with stable hashing."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        tokens = [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]
        terms = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
        vector = [0.0] * self.dimension
        for term in terms:
            digest = hashlib.sha256(term.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimension
            sign = 1.0 if digest[8] % 2 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector


def build_embedding(text: str, model: EmbeddingModel | None = None) -> list[float]:
    """Generate one embedding using the supplied or fallback model."""
    return (model or HashEmbeddingModel()).embed(text)


def build_embeddings(
    texts: Sequence[str] | Iterable[str], model: EmbeddingModel | None = None
) -> list[list[float]]:
    """Generate embeddings for searchable catalog text in input order."""
    provider = model or HashEmbeddingModel()
    return [provider.embed(text) for text in texts]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Return cosine similarity for two equal-length vectors."""
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimension")
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0
