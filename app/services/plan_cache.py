"""Persistent semantic cache of validated plans, keyed by query paraphrases and plan content.

Only plans that pass ``validate_plan`` can enter the cache, and every entry is
re-validated when a saved cache is loaded. Lookup is cosine similarity between
the query embedding and every stored key (the original query, its paraphrases,
and one "action name + first step" key per action).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np

from app.config import SIMILARITY_THRESHOLD
from app.retrieval.embeddings import EmbeddingModel, HashEmbeddingModel
from app.services.plan_validator import validate_plan
from app.services.variations import normalize_query


@dataclass(frozen=True)
class CacheEntry:
    """One cached plan and the queries that key it."""

    entry_id: str
    query: str
    variations: tuple[str, ...]
    response: dict[str, Any]


@dataclass(frozen=True)
class CacheHit:
    """A lookup result with its similarity to the closest stored key."""

    entry: CacheEntry
    similarity: float
    exact: bool


@dataclass(frozen=True)
class _Key:
    entry_id: str
    normalized: str
    vector: list[float]


def _plan_keys(response: Mapping[str, Any]) -> list[str]:
    """One key per action: its name followed by its first step."""
    keys = []
    for action in response["contexts"][0]["actions"]:
        first = [step for group in action["stepGroups"] for step in group["steps"]][:1]
        keys.append(f'{action["actionName"]}. {" ".join(first)}')
    return keys


class PlanCache:
    """In-memory semantic index over validated plans with JSON persistence."""

    def __init__(
        self,
        catalog: Iterable[Mapping[str, Any]],
        model: EmbeddingModel | None = None,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> None:
        self._catalog = list(catalog)
        self._model = model or HashEmbeddingModel()
        self.threshold = threshold
        self._entries: dict[str, CacheEntry] = {}
        self._keys: list[_Key] = []
        self._exact: dict[str, str] = {}
        self._matrix: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def embedder_name(self) -> str:
        """Identifier of the embedding model in use, for reports."""
        return getattr(self._model, "name", type(self._model).__name__)

    def entries(self) -> list[CacheEntry]:
        """Return every cached entry in insertion order."""
        return list(self._entries.values())

    def _embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        batch = getattr(self._model, "embed_many", None)
        return batch(texts) if batch is not None else [self._model.embed(text) for text in texts]

    def add(self, entry_id: str, query: str, variations: Iterable[str], response: dict[str, Any]) -> None:
        """Validate and store a plan; raise ``ValueError`` if it breaks any rule."""
        variations = tuple(variations)
        result = validate_plan({**response, "query_variations": list(variations)}, self._catalog)
        if not result.valid:
            raise ValueError("; ".join(result.errors))
        self._entries[entry_id] = CacheEntry(entry_id, query, variations, response)
        self._keys = [key for key in self._keys if key.entry_id != entry_id]
        self._exact = {k: v for k, v in self._exact.items() if v != entry_id}
        texts = list(dict.fromkeys(t for t in (normalize_query(x) for x in (query, *variations, *_plan_keys(response))) if t))
        for text, vector in zip(texts, self._embed_many(texts)):
            self._exact.setdefault(text, entry_id)
            self._keys.append(_Key(entry_id, text, vector))
        self._matrix = None

    def add_lookup_keys(self, entry_id: str, texts: Iterable[str]) -> None:
        """Add extra lookup keys to an already-validated entry.

        Unlike ``add``, this does not re-run schema validation: ``texts`` are supplementary
        phrasings (for example hand-written evaluation paraphrases) rather than the official
        API's ``query_variations`` field, which has its own separate 8-10-item rule.
        """
        if entry_id not in self._entries:
            raise KeyError(f"no entry {entry_id!r}; call add() first")
        for text in dict.fromkeys(t for t in (normalize_query(x) for x in texts) if t):
            self._exact.setdefault(text, entry_id)
            self._keys.append(_Key(entry_id, text, self._model.embed(text)))
        self._matrix = None

    def _key_matrix(self) -> np.ndarray:
        if self._matrix is None:
            matrix = np.asarray([key.vector for key in self._keys], dtype=np.float32)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            self._matrix = matrix / np.where(norms == 0, 1.0, norms)
        return self._matrix

    def lookup(self, query: str) -> CacheHit | None:
        """Return the closest cached plan at or above the similarity threshold."""
        normalized = normalize_query(query)
        if not normalized or not self._keys:
            return None
        exact_id = self._exact.get(normalized)
        if exact_id is not None:
            return CacheHit(self._entries[exact_id], 1.0, True)
        vector = np.asarray(self._model.embed(normalized), dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            return None
        scores = self._key_matrix() @ (vector / norm)
        best = int(scores.argmax())
        if float(scores[best]) < self.threshold:
            return None
        return CacheHit(self._entries[self._keys[best].entry_id], round(float(scores[best]), 4), False)

    def top_matches(self, query: str, k: int = 5) -> list[CacheHit]:
        """Return up to ``k`` distinct cached plans ranked by similarity to ``query``.

        Unlike :meth:`lookup`, this ignores ``self.threshold`` and never uses the exact-match
        fast path: it always ranks every stored key by cosine similarity first, then keeps
        each entry's best-scoring key, so a query with several keys pointing at the same plan
        (canonical query, paraphrases, action names) counts as one candidate, not several. This
        is for reporting metrics such as Recall@k and MRR, where the point is to see how the
        candidate ranks, not just whether it is the single best match above a cutoff.
        """
        normalized = normalize_query(query)
        if not normalized or not self._keys:
            return []
        vector = np.asarray(self._model.embed(normalized), dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            return []
        scores = self._key_matrix() @ (vector / norm)
        best_per_entry: dict[str, float] = {}
        for key, score in zip(self._keys, scores):
            value = float(score)
            if value > best_per_entry.get(key.entry_id, -1.0):
                best_per_entry[key.entry_id] = value
        ranked = sorted(best_per_entry.items(), key=lambda pair: pair[1], reverse=True)[:k]
        return [CacheHit(self._entries[entry_id], round(score, 4), False) for entry_id, score in ranked]

    def save(self, path: Path) -> None:
        """Write all entries to ``path`` as JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "entries": [
                {"id": e.entry_id, "query": e.query, "variations": list(e.variations), "response": e.response}
                for e in self._entries.values()
            ]
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path, catalog: Iterable[Mapping[str, Any]], **kwargs: Any) -> "PlanCache":
        """Read a saved cache, re-validating every entry."""
        cache = cls(catalog, **kwargs)
        for item in json.loads(path.read_text(encoding="utf-8"))["entries"]:
            cache.add(item["id"], item["query"], item["variations"], item["response"])
        return cache
