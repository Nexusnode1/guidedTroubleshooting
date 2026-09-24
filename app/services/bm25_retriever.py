"""BM25 keyword retrieval over descriptive catalog metadata.

URI/deeplink fields are deliberately excluded from indexed text.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import math
import re
from typing import Any

from app.models.retrieval import BM25Result


_TOKEN = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")
_STOPWORDS = frozenset(
    "a an and are as at be can do for from has have i if in is it me my of on or "
    "that the this to was were what when where with you".split()
)
DEFAULT_METADATA_FIELDS = (
    "title", "description", "text", "target_screen", "screen", "screen_name",
    "intent", "category", "keywords", "query", "label", "name",
)


def _tokens(text: str) -> list[str]:
    """Tokenize descriptive text without URI-specific processing."""
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]


def metadata_text(entry: Mapping[str, Any], fields: Sequence[str] = DEFAULT_METADATA_FIELDS) -> str:
    """Extract only configured descriptive fields from a catalog entry."""
    values: list[str] = []
    for field in fields:
        value = entry.get(field)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple)):
            values.extend(item for item in value if isinstance(item, str))
    if not values:
        raise ValueError("catalog entry has no descriptive metadata fields")
    return " ".join(values)


@dataclass
class _Document:
    entry: Mapping[str, Any]
    terms: list[str]


class BM25Retriever:
    """In-memory BM25 index over the supplied catalog metadata."""

    def __init__(
        self,
        catalog: Iterable[Mapping[str, Any]],
        metadata_fields: Sequence[str] = DEFAULT_METADATA_FIELDS,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if k1 < 0 or not 0 <= b <= 1:
            raise ValueError("BM25 parameters must satisfy k1 >= 0 and 0 <= b <= 1")
        self.k1, self.b = k1, b
        self.metadata_fields = tuple(metadata_fields)
        self._documents = [
            _Document(entry, _tokens(metadata_text(entry, self.metadata_fields)))
            for entry in catalog
        ]
        self._average_length = (
            sum(len(document.terms) for document in self._documents) / len(self._documents)
            if self._documents else 0.0
        )
        document_frequency: Counter[str] = Counter()
        for document in self._documents:
            document_frequency.update(set(document.terms))
        self._document_frequency = document_frequency

    def search(self, query: str, top_k: int = 5) -> list[BM25Result]:
        """Return top catalog entries ranked by BM25 metadata score."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        query_terms = _tokens(query)
        total = len(self._documents)
        results: list[BM25Result] = []
        for document in self._documents:
            frequencies = Counter(document.terms)
            score = 0.0
            length = len(document.terms)
            denominator_length = self._average_length or 1.0
            for term in query_terms:
                if not frequencies[term]:
                    continue
                df = self._document_frequency[term]
                idf = math.log(1.0 + (total - df + 0.5) / (df + 0.5))
                tf = frequencies[term]
                normalization = tf + self.k1 * (1 - self.b + self.b * length / denominator_length)
                score += idf * (tf * (self.k1 + 1)) / normalization
            results.append(BM25Result(document.entry, float(score)))
        ordered = sorted(enumerate(results), key=lambda pair: (-pair[1].score, pair[0]))
        return [result for _, result in ordered[:top_k]]
