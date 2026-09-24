"""Deterministic query normalization and variation generation.

This module deliberately has no dataset, deeplink, LLM, or retrieval
dependency. A future model-backed enricher can implement the same interface
while retaining the original query and deterministic fallback.
"""

from __future__ import annotations

import re
import unicodedata

from app.models.schemas import QueryEnrichmentResult


# Conservative corrections for frequent keyboard/orthographic errors. This
# is a fallback aid, not a domain vocabulary or an official query catalog.
_COMMON_CORRECTIONS = {
    "cant": "cannot",
    "wont": "will not",
    "doesnt": "does not",
    "isnt": "is not",
    "recieve": "receive",
    "conect": "connect",
    "conectivty": "connectivity",
    "connectivty": "connectivity",
    "wify": "wifi",
}
_COMMON_CONTRACTIONS = {
    "can't": "cannot",
    "doesn't": "does not",
    "isn't": "is not",
    "won't": "will not",
}

_LEADING_COURTESY = re.compile(
    r"^(?:hey|hi|hello|please|kindly|could you|can you|would you)\b[,:;.!\s]*",
    re.IGNORECASE,
)
_REQUEST_PREFIX = re.compile(
    r"^(?:i need help with|help me with|help with|can you help me with|i am having trouble with|i'm having trouble with)\b\s*",
    re.IGNORECASE,
)
_QUESTION_PREFIX = re.compile(
    r"^(?:what do i do if|what can i do if|how can i|how do i)\b\s*",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")

# These are grammatical stopwords only; they are not domain terms.
_STOPWORDS = frozenset(
    "a an and are can do for from has have i if in is it me my of on please the to with you "
    "ugh argh omg frustrated annoyed angry damn".split()
)


def _tokens(text: str) -> list[str]:
    """Return lowercase word tokens from normalized text."""
    return _WORD.findall(text.lower())


def normalize_query(query: str) -> str:
    """Normalize casing, Unicode, punctuation, contractions, and phrasing."""
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    normalized = unicodedata.normalize("NFKC", query).strip().lower()
    normalized = normalized.replace("’", "'")
    for contraction, expansion in _COMMON_CONTRACTIONS.items():
        normalized = re.sub(rf"\b{re.escape(contraction)}\b", expansion, normalized)
    normalized = re.sub(r"[^a-z0-9'\s-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    # Strip stacked conversational openers (for example, "hey please ...").
    previous = None
    while normalized != previous:
        previous = normalized
        normalized = _LEADING_COURTESY.sub("", normalized)
    normalized = _REQUEST_PREFIX.sub("", normalized)
    normalized = _QUESTION_PREFIX.sub("", normalized)
    words = [_COMMON_CORRECTIONS.get(word, word) for word in _tokens(normalized)]
    return " ".join(words)


def extract_core_intent(normalized_query: str) -> str:
    """Represent the core intent using content words in their original order."""
    words = _tokens(normalized_query)
    content = [word for word in words if word not in _STOPWORDS]
    return " ".join(content) or normalized_query


def generate_variations(normalized_query: str, core_intent: str) -> list[str]:
    """Generate generic retrieval variations without domain-specific guesses."""
    candidates = [normalized_query, core_intent]
    if core_intent:
        candidates.extend(
            (
                f"troubleshoot {core_intent}",
                f"help with {core_intent}",
                f"problem with {core_intent}",
            )
        )
    # Preserve order while removing empty strings and duplicates.
    return list(dict.fromkeys(candidate.strip() for candidate in candidates if candidate.strip()))


class QueryEnricher:
    """Default deterministic enricher, replaceable by a model-backed adapter."""

    def enrich(self, query: str) -> QueryEnrichmentResult:
        """Return normalized intent and retrieval variations for ``query``."""
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        normalized = normalize_query(query)
        if not normalized:
            raise ValueError("query must contain searchable text")
        core_intent = extract_core_intent(normalized)
        return QueryEnrichmentResult(
            original_query=query,
            normalized_query=normalized,
            core_intent=core_intent,
            variations=generate_variations(normalized, core_intent),
        )


def enrich_query(query: str) -> QueryEnrichmentResult:
    """Enrich a raw query with the deterministic development implementation."""
    return QueryEnricher().enrich(query)
