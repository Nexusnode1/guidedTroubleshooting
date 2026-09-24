"""Resolve extracted UI actions to exact catalog-backed target screens."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import re
from typing import Any

from app.models.screen_resolution import ScreenResolution


_URI_FIELDS = ("deeplink", "deep_link", "url", "uri")
_URI_FIELD_SET = frozenset(_URI_FIELDS)
_SCREEN_FIELDS = ("target_screen", "screen", "screen_name", "target")
_ACTION_FIELDS = (
    "target_screen", "screen", "feature", "action", "name", "label", "title",
    "description", "message", "qna_description", "query", "intent", "control_type",
)
_METADATA_FIELDS = (
    "description", "message", "qna_description", "control_type", "target_screen",
    "screen", "screen_name", "target", "title", "name", "intent", "category",
    "keywords", "query", "label",
)
_TOKEN = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")
_PARENT_TERMS = frozenset(("settings", "menu", "home", "preferences", "overview"))
_MIN_CONFIDENCE = 0.55
_AMBIGUITY_MARGIN = 0.05


def _tokens(text: str) -> set[str]:
    """Tokenize comparable UI text."""
    return set(_TOKEN.findall(text.lower()))


def _value(entry: Mapping[str, Any], fields: Sequence[str]) -> str | None:
    """Return the first non-empty string for a field group."""
    for field in fields:
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _metadata(entry: Mapping[str, Any]) -> str:
    """Join descriptive metadata while excluding URI fields."""
    values: list[str] = []
    for field in _METADATA_FIELDS:
        if field in _URI_FIELD_SET:
            continue
        value = entry.get(field)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple)):
            values.extend(item for item in value if isinstance(item, str))
    return " ".join(values)


def _action_text(action: Mapping[str, Any] | str) -> str:
    """Extract action text without reading any URI field."""
    if isinstance(action, str):
        return action.strip()
    values: list[str] = []
    for field in _ACTION_FIELDS:
        value = action.get(field)
        if isinstance(value, str):
            values.append(value)
    if not values:
        raise ValueError("action has no searchable descriptive fields")
    return " ".join(values).strip()


def _parent_only(entry: Mapping[str, Any], screen: str) -> bool:
    """Detect explicit or clearly generic parent-menu catalog metadata."""
    if entry.get("is_parent") is True or entry.get("screen_type") == "parent":
        return True
    screen_terms = _tokens(screen)
    return bool(screen_terms) and screen_terms <= _PARENT_TERMS


def _candidate(action_text: str, entry: Mapping[str, Any]) -> tuple[float, dict[str, Any]] | None:
    """Score one catalog entry using target and descriptive metadata overlap."""
    screen = _value(entry, _SCREEN_FIELDS)
    uri = _value(entry, _URI_FIELDS)
    if screen is None or uri is None:
        return None
    query_terms = _tokens(action_text)
    screen_terms = _tokens(screen)
    metadata_terms = _tokens(_metadata(entry))
    if not query_terms:
        return None
    target_overlap = len(query_terms & screen_terms) / len(query_terms)
    metadata_overlap = len(query_terms & metadata_terms) / len(query_terms)
    exact_target = action_text.strip().casefold() == screen.casefold()
    score = 1.0 if exact_target else 0.7 * target_overlap + 0.3 * metadata_overlap
    evidence = {
        "target_screen": screen,
        "metadata": _metadata(entry),
        "matched_target_terms": sorted(query_terms & screen_terms),
        "matched_metadata_terms": sorted(query_terms & metadata_terms),
        "exact_target_match": exact_target,
        "target_overlap": target_overlap,
        "metadata_overlap": metadata_overlap,
            "catalog_uri_field": next(
                field for field in _URI_FIELDS
                if isinstance(entry.get(field), str) and entry[field].strip()
            ),
    }
    return score, evidence


def resolve_action(
    action: Mapping[str, Any] | str,
    catalog: Iterable[Mapping[str, Any]],
    *,
    ambiguity_margin: float = _AMBIGUITY_MARGIN,
) -> ScreenResolution:
    """Resolve one action, refusing low-confidence or ambiguous matches."""
    action_text = _action_text(action)
    entries = list(catalog)
    candidates: list[tuple[float, int, Mapping[str, Any], dict[str, Any]]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            continue
        scored = _candidate(action_text, entry)
        if scored is not None:
            score, evidence = scored
            candidates.append((score, index, entry, evidence))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    if not candidates:
        return ScreenResolution(
            action=action_text, confidence=0.0, resolved=False,
            parent_level_only=False, ambiguous=False,
            evidence={"candidate_count": 0, "reason": "no catalog screen/URI match"},
        )
    score, _, entry, evidence = candidates[0]
    if score <= 0.0:
        return ScreenResolution(
            action=action_text, confidence=0.0, resolved=False,
            parent_level_only=False, ambiguous=False,
            evidence={"candidate_count": len(candidates), "reason": "no overlapping screen metadata"},
        )
    screen = evidence["target_screen"]
    uri = _value(entry, _URI_FIELDS)
    parent_only = _parent_only(entry, screen)
    ambiguous = len(candidates) > 1 and score - candidates[1][0] <= ambiguity_margin
    resolved = score >= _MIN_CONFIDENCE and not parent_only and not ambiguous
    evidence = {
        **evidence,
        "candidate_count": len(candidates),
        "parent_level_only": parent_only,
        "ambiguous_margin": ambiguity_margin,
        "next_best_score": candidates[1][0] if len(candidates) > 1 else None,
    }
    return ScreenResolution(
        action=action_text,
        target_screen=screen,
        deeplink=uri if resolved else None,
        confidence=max(0.0, min(1.0, score)),
        resolved=resolved,
        parent_level_only=parent_only,
        ambiguous=ambiguous,
        evidence=evidence,
    )


def resolve_actions(
    actions: Iterable[Mapping[str, Any] | str],
    catalog: Iterable[Mapping[str, Any]],
) -> list[ScreenResolution]:
    """Resolve actions independently against the unchanged catalog."""
    entries = list(catalog)
    return [resolve_action(action, entries) for action in actions]
