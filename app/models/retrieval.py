"""Typed retrieval result models independent of any search implementation."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any


@dataclass(frozen=True)
class BM25Result:
    """A catalog entry and its keyword-retrieval score."""

    entry: Mapping[str, Any]
    score: float


@dataclass(frozen=True)
class DenseResult:
    """A catalog entry and its embedding similarity score."""

    entry: Mapping[str, Any]
    score: float


@dataclass(frozen=True)
class HybridResult:
    """A catalog entry with individual and fused retrieval scores."""

    entry: Mapping[str, Any]
    bm25_score: float
    dense_score: float
    hybrid_score: float
