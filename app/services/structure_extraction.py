"""Extract a provisional troubleshooting structure from query enrichment."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from app.models.schemas import QueryEnrichmentResult
from app.models.structure import TroubleshootingStructure


_TOKEN = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")
_ENTITY_TERMS = frozenset(
    "battery phone mobile tablet tv camera wifi internet bluetooth screen display "
    "charger charging app network speaker microphone performance storage".split()
)
_DEVICE_TERMS = frozenset("phone mobile tablet tv camera laptop computer device android ios".split())
_SYMPTOM_TERMS = frozenset(
    "drain drains draining dying slow slowdown hot heat overheating working open crash "
    "crashing connect connecting disconnect disconnected charge charging freeze frozen "
    "blank flicker flickering broken fail failed failure".split()
)
_HIGH_SEVERITY_TERMS = frozenset("urgent emergency dangerous unusable immediately".split())
_MODERATE_SEVERITY_TERMS = frozenset("very extremely crazy quickly rapidly constantly".split())
_GENERIC_TERMS = frozenset("help issue problem thing something stuff".split())


def _as_enrichment(source: QueryEnrichmentResult | Mapping[str, Any]) -> QueryEnrichmentResult:
    """Coerce an enrichment model or mapping at the service boundary."""
    if isinstance(source, QueryEnrichmentResult):
        return source
    if isinstance(source, Mapping):
        if hasattr(QueryEnrichmentResult, "model_validate"):
            return QueryEnrichmentResult.model_validate(source)
        return QueryEnrichmentResult.parse_obj(source)
    raise TypeError("source must be QueryEnrichmentResult or a mapping")


def _tokens(text: str) -> list[str]:
    """Extract normalized lexical tokens."""
    return _TOKEN.findall(text.lower())


def _unique(values: list[str]) -> list[str]:
    """Deduplicate values while preserving source order."""
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _extract_entities(text: str) -> list[str]:
    """Return explicit entity terms, allowing one-character typos."""
    entities: list[str] = []
    for token in _tokens(text):
        if token in _ENTITY_TERMS:
            entities.append(token)
            continue
        # A small edit-distance fallback handles misspellings such as
        # ``battry`` without introducing an entity absent from the vocabulary.
        near_matches = [term for term in _ENTITY_TERMS if _edit_distance_at_most_one(token, term)]
        if len(near_matches) == 1:
            entities.append(near_matches[0])
    return _unique(entities)


def _edit_distance_at_most_one(left: str, right: str) -> bool:
    """Return whether two words differ by at most one insertion/deletion/substitution."""
    if abs(len(left) - len(right)) > 1:
        return False
    differences = 0
    left_index = right_index = 0
    while left_index < len(left) and right_index < len(right):
        if left[left_index] == right[right_index]:
            left_index += 1
            right_index += 1
            continue
        differences += 1
        if differences > 1:
            return False
        if len(left) > len(right):
            left_index += 1
        elif len(right) > len(left):
            right_index += 1
        else:
            left_index += 1
            right_index += 1
    return differences + (len(left) - left_index) + (len(right) - right_index) <= 1


def _extract_device_context(text: str) -> list[str]:
    """Return explicit device terms without inferring a device from symptoms."""
    return _unique([token for token in _tokens(text) if token in _DEVICE_TERMS])


def _extract_symptoms(text: str) -> list[str]:
    """Extract symptom-bearing clauses, retaining their explicit wording."""
    clauses = re.split(r"\s+(?:and|but|while|although)\s+|[,;]+", text.lower())
    symptoms: list[str] = []
    for clause in clauses:
        words = _tokens(clause)
        if words and any(word in _SYMPTOM_TERMS for word in words):
            symptoms.append(" ".join(words))
    return _unique(symptoms)


def _severity(text: str) -> str:
    """Classify only explicit severity language; otherwise return ``unknown``."""
    words = set(_tokens(text))
    if words & _HIGH_SEVERITY_TERMS:
        return "high"
    if words & _MODERATE_SEVERITY_TERMS:
        return "moderate"
    return "unknown"


def _ambiguity(core_intent: str, keywords: list[str]) -> tuple[bool, str | None]:
    """Flag underspecified lexical goals without selecting an unverified intent."""
    if not keywords:
        return True, "no discernible intent terms"
    if len(keywords) == 1:
        return True, "only one intent term was provided"
    if all(keyword in _GENERIC_TERMS for keyword in keywords):
        return True, "only generic help terms were provided"
    return False, None


def _possible_intents(symptoms: list[str], entities: list[str], core_intent: str) -> list[str]:
    """Build lexical candidate phrases without inventing categories or actions."""
    candidates: list[str] = []
    for symptom in symptoms:
        candidates.append(symptom)
        for entity in entities:
            if entity in symptom:
                candidates.append(symptom)
    if not candidates and core_intent:
        candidates.append(core_intent)
    return _unique(candidates)


def extract_structure(
    source: QueryEnrichmentResult | Mapping[str, Any],
) -> TroubleshootingStructure:
    """Convert query-enrichment output into a structured troubleshooting goal."""
    enriched = _as_enrichment(source)
    keywords = _unique(_tokens(enriched.core_intent))
    symptoms = _extract_symptoms(enriched.normalized_query)
    entities = _extract_entities(enriched.normalized_query)
    device_context = _extract_device_context(enriched.normalized_query)
    is_ambiguous, reason = _ambiguity(enriched.core_intent, keywords)
    return TroubleshootingStructure(
        original_query=enriched.original_query,
        normalized_query=enriched.normalized_query,
        core_intent=enriched.core_intent,
        keywords=keywords,
        variations=list(enriched.variations),
        is_ambiguous=is_ambiguous,
        symptoms=symptoms,
        entities=entities,
        device_context=device_context,
        severity=_severity(enriched.normalized_query),
        ambiguity_reason=reason,
        possible_intents=_possible_intents(symptoms, entities, enriched.core_intent),
    )


def extract_goal(
    source: QueryEnrichmentResult | Mapping[str, Any],
) -> TroubleshootingStructure:
    """Backward-compatible named alias for structured goal extraction."""
    return extract_structure(source)
