"""Map structured actions to catalog-backed physical screens and deeplinks.

This module is deliberately an orchestration layer.  Retrieval proposes
catalog entries, screen resolution decides whether a specific target is safe,
and this mapper exposes the exact URI already stored in that entry.  It never
constructs, normalizes, or otherwise edits a URI.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
from typing import Any

from app.models.screen_resolution import ScreenResolution
from app.services.hybrid_retriever import HybridRetriever
from app.services.screen_resolver import resolve_action


_DESCRIPTIVE_FIELDS = (
    "target_screen", "screen", "screen_name", "target", "feature", "action",
    "name", "label", "title", "description", "message", "qna_description",
    "query", "intent", "control_type", "category", "keywords",
)
_URI_FIELDS = ("deeplink", "deep_link", "url", "uri")
_MANUAL_FIELDS = ("manual", "is_manual")
_MANUAL_TYPES = frozenset(("manual", "instruction", "offline"))
_RETRIEVAL_FIELDS = (
    "title", "description", "message", "qna_description", "text",
    "target_screen", "screen", "screen_name", "target", "intent", "category",
    "keywords", "query", "label", "name", "control_type", "originalType",
)
_MIN_HYBRID_SCORE = 0.40
_HYBRID_AMBIGUITY_MARGIN = 0.10


@dataclass(frozen=True)
class DeeplinkMapping:
    """One action mapped to at most one validated physical screen."""

    action: str
    target_screen: str | None
    deeplink: str | None
    confidence: float
    resolved: bool
    manual: bool
    parent_level_only: bool
    ambiguous: bool
    evidence: Mapping[str, Any]


def _text_value(value: Any) -> list[str]:
    """Extract searchable text from scalar or list metadata."""
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, (list, tuple)):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _action_text(action: Mapping[str, Any] | str) -> str:
    """Build descriptive action text while ignoring URI fields."""
    if isinstance(action, str):
        text = action.strip()
    elif isinstance(action, Mapping):
        values: list[str] = []
        for field in _DESCRIPTIVE_FIELDS:
            values.extend(_text_value(action.get(field)))
        # Several UI interactions may belong to one physical action/screen.
        for field in ("steps", "interactions"):
            nested = action.get(field)
            if isinstance(nested, (list, tuple)):
                for item in nested:
                    if isinstance(item, (Mapping, str)):
                        values.append(_action_text(item))
        text = " ".join(values).strip()
    else:
        raise TypeError("action must be a mapping or string")
    if not text:
        raise ValueError("action has no descriptive text")
    return text


def _is_manual(action: Mapping[str, Any] | str, text: str) -> bool:
    """Recognize explicit manual actions without guessing from a URI."""
    if isinstance(action, Mapping):
        for field in _MANUAL_FIELDS:
            if action.get(field) is True:
                return True
        for field in ("action_type", "type", "kind", "category"):
            value = action.get(field)
            if isinstance(value, str) and value.casefold() in _MANUAL_TYPES:
                return True
    return bool(re.search(r"\bmanually?\b|\boffline\b", text.casefold()))


def _screen_name(entry: Mapping[str, Any]) -> str | None:
    """Read a catalog target-screen field without consulting its URI."""
    for field in ("target_screen", "screen", "screen_name", "target"):
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _invalid_result(action_text: str, *, reason: str, manual: bool = False) -> DeeplinkMapping:
    return DeeplinkMapping(
        action=action_text,
        target_screen=None,
        deeplink=None,
        confidence=0.0,
        resolved=False,
        manual=manual,
        parent_level_only=False,
        ambiguous=False,
        evidence={"reason": reason},
    )


def map_action(
    action: Mapping[str, Any] | str,
    catalog: Iterable[Mapping[str, Any]],
    *,
    retriever: HybridRetriever | None = None,
    top_k: int | None = None,
) -> DeeplinkMapping:
    """Map one action to one exact catalog URI, or reject it safely."""
    text = _action_text(action)
    manual = _is_manual(action, text)
    if manual:
        return _invalid_result(text, reason="manual action has no actionable deeplink", manual=True)

    entries = list(catalog)
    if not entries:
        return _invalid_result(text, reason="catalog is empty")
    if top_k is not None and top_k < 1:
        raise ValueError("top_k must be positive")

    # The hybrid index is built over descriptive metadata only.  URI fields
    # are never passed as searchable text.
    searcher = retriever or HybridRetriever(entries, metadata_fields=_RETRIEVAL_FIELDS)
    result_limit = top_k or len(entries)
    retrieved = searcher.search(text, top_k=min(result_limit, len(entries)))
    candidates = [result.entry for result in retrieved if isinstance(result.entry, Mapping)]
    if not candidates:
        return _invalid_result(text, reason="hybrid retrieval returned no candidates")

    # Give screen resolution the strongest hybrid candidate only when the
    # retrieval signal is both strong and clearly separated from runner-up.
    # This lets paraphrases resolve while preventing a weak semantic guess
    # from becoming an actionable URI.
    top_result = retrieved[0]
    runner_up = retrieved[1].hybrid_score if len(retrieved) > 1 else 0.0
    inferred_screen = _screen_name(top_result.entry)
    clear_hybrid_match = (
        bool(inferred_screen)
        and top_result.hybrid_score >= _MIN_HYBRID_SCORE
        and top_result.hybrid_score - runner_up > _HYBRID_AMBIGUITY_MARGIN
    )
    resolution_input: Mapping[str, Any] | str = action
    if clear_hybrid_match:
        resolution_input = {"target_screen": inferred_screen}
    resolution: ScreenResolution = resolve_action(resolution_input, candidates)
    scores = [
        {
            "target_screen": _screen_name(result.entry),
            "bm25_score": result.bm25_score,
            "dense_score": result.dense_score,
            "hybrid_score": result.hybrid_score,
        }
        for result in retrieved
    ]
    selected_score = next(
        (item["hybrid_score"] for item in scores if item["target_screen"] == resolution.target_screen),
        0.0,
    )
    evidence = {
        "retrieval": scores,
        "selected_hybrid_score": selected_score,
        "screen_resolution": resolution.evidence,
    }
    if not resolution.resolved or not resolution.deeplink:
        return DeeplinkMapping(
            action=text,
            target_screen=resolution.target_screen if resolution.resolved else None,
            deeplink=None,
            confidence=resolution.confidence,
            resolved=False,
            manual=False,
            parent_level_only=resolution.parent_level_only,
            ambiguous=resolution.ambiguous,
            evidence=evidence,
        )

    # The URI is copied verbatim from ScreenResolution/catalog data.
    return DeeplinkMapping(
        action=text,
        target_screen=resolution.target_screen,
        deeplink=resolution.deeplink,
        confidence=resolution.confidence,
        resolved=True,
        manual=False,
        parent_level_only=False,
        ambiguous=False,
        evidence=evidence,
    )


def map_actions(
    actions: Iterable[Mapping[str, Any] | str],
    catalog: Iterable[Mapping[str, Any]],
    *,
    top_k: int | None = None,
) -> list[DeeplinkMapping]:
    """Map actions independently while preserving input order and grouping."""
    entries = list(catalog)
    searcher = HybridRetriever(entries, metadata_fields=_RETRIEVAL_FIELDS) if entries else None
    return [map_action(action, entries, retriever=searcher, top_k=top_k) for action in actions]


# Explicit aliases make the service easy to discover from future pipeline code.
map_deeplink = map_action
map_deeplinks = map_actions
