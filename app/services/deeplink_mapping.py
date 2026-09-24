"""Map structured troubleshooting goals to catalog-backed deeplinks.

The mapper never constructs or edits URLs. A result can only contain values
read from a supplied catalog entry; missing or malformed entries are skipped.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from app.models.schemas import StructuredTroubleshootingGoal
from app.retrieval.semantic_search import SearchResult, SemanticSearcher


_DEEPLINK_FIELDS = ("deeplink", "deep_link", "url")
_SCREEN_FIELDS = ("target_screen", "screen", "screen_name", "target", "title", "name")
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class DeeplinkMatch:
    """One ranked, catalog-backed target-screen match."""

    target_screen: str
    deeplink: str
    score: float
    catalog_entry: Mapping[str, Any]


def _goal_values(goal: StructuredTroubleshootingGoal | Mapping[str, Any]) -> tuple[str, str, list[str]]:
    """Read only the query fields needed for catalog retrieval."""
    if isinstance(goal, StructuredTroubleshootingGoal):
        return goal.normalized_query, goal.core_intent, list(goal.variations)
    if isinstance(goal, Mapping):
        normalized = goal.get("normalized_query")
        core = goal.get("core_intent")
        variations = goal.get("variations", [])
        if not isinstance(normalized, str) or not isinstance(core, str):
            raise ValueError("goal requires normalized_query and core_intent strings")
        if not isinstance(variations, list) or not all(isinstance(item, str) for item in variations):
            raise ValueError("goal variations must be a list of strings")
        return normalized, core, variations
    raise TypeError("goal must be StructuredTroubleshootingGoal or a mapping")


def _field_value(entry: Mapping[str, Any], fields: Sequence[str]) -> str | None:
    """Return the first non-empty string present under the supplied field names."""
    for field in fields:
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _screen_overlap(screen: str, goal_text: str) -> int:
    """Count shared terms for exact-target tie-breaking only."""
    return len(set(_TOKEN.findall(screen.lower())) & set(_TOKEN.findall(goal_text.lower())))


def rank_catalog_matches(
    goal: StructuredTroubleshootingGoal | Mapping[str, Any],
    catalog: Iterable[Mapping[str, Any]],
    *,
    top_k: int = 5,
) -> list[DeeplinkMatch]:
    """Search and rank only entries containing existing screen/deeplink values."""
    normalized, core, variations = _goal_values(goal)
    if top_k < 1:
        raise ValueError("top_k must be positive")
    entries = list(catalog)
    searcher = SemanticSearcher(
        entries,
        text_fields=(
            "text",
            "title",
            "name",
            "description",
            "query",
            "intent",
            "label",
            "target_screen",
            "screen",
            "screen_name",
        ),
    )
    # Search all available goal forms and retain the strongest score per entry.
    queries = list(dict.fromkeys([core, normalized, *variations]))
    best: dict[int, SearchResult] = {}
    for query in queries:
        if not query.strip():
            continue
        for result in searcher.search(query, top_k=max(top_k, len(entries))):
            key = id(result.entry)
            previous = best.get(key)
            if previous is None or result.score > previous.score:
                best[key] = result
    matches: list[DeeplinkMatch] = []
    goal_text = f"{core} {normalized}"
    for result in best.values():
        target_screen = _field_value(result.entry, _SCREEN_FIELDS)
        deeplink = _field_value(result.entry, _DEEPLINK_FIELDS)
        if target_screen is None or deeplink is None:
            continue
        matches.append(DeeplinkMatch(target_screen, deeplink, result.score, result.entry))
    matches.sort(
        key=lambda match: (
            match.score,
            _screen_overlap(match.target_screen, goal_text),
            len(_TOKEN.findall(match.target_screen)),
        ),
        reverse=True,
    )
    return matches[:top_k]


def map_deeplink(
    goal: StructuredTroubleshootingGoal | Mapping[str, Any],
    catalog: Iterable[Mapping[str, Any]],
) -> DeeplinkMatch | None:
    """Select the best existing catalog deeplink for a troubleshooting goal."""
    matches = rank_catalog_matches(goal, catalog, top_k=1)
    return matches[0] if matches else None


def map_deeplinks(
    goal: StructuredTroubleshootingGoal | Mapping[str, Any],
    catalog: Iterable[Mapping[str, Any]],
    limit: int = 5,
) -> list[DeeplinkMatch]:
    """Return ranked catalog-backed matches without creating deeplinks."""
    return rank_catalog_matches(goal, catalog, top_k=limit)
