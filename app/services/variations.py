"""Deterministic query paraphrases in varied registers.

The paraphrases double as the semantic cache key set for a plan, so they must
be reproducible: no randomness, no model calls.
"""

from __future__ import annotations

from app.services.query_enrichment import QueryEnricher

_MAX_CORE_WORDS = 14
_enricher = QueryEnricher()


def normalize_query(query: str) -> str:
    """Return the canonical lower-case form used for cache keys."""
    return _enricher.enrich(query).normalized_query


def _with_typo(text: str) -> str:
    """Swap two inner letters of the longest word (first one on ties)."""
    words = text.split()
    if not words:
        return text
    index = max(range(len(words)), key=lambda i: len(words[i]))
    word = words[index]
    if len(word) >= 4:
        words[index] = word[0] + word[2] + word[1] + word[3:]
    return " ".join(words)


def _sentence(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def generate_variations(query: str, topic: str) -> list[str]:
    """Return 8-10 distinct paraphrases of ``query``.

    Registers: original, formal, casual, keyword-only, frustrated, typo,
    questions, and topic-only phrasings.
    """
    enriched = _enricher.enrich(query)
    core = " ".join(enriched.core_intent.split()[:_MAX_CORE_WORDS]) or enriched.normalized_query
    keywords = " ".join(core.split()[:6])
    topic_text = topic.lower()
    candidates = [
        query.strip(),
        f"I am experiencing an issue with my Galaxy: {core}.",
        f"my phone is acting up, {core}",
        keywords,
        f"This is so annoying - {core}, please help!",
        _with_typo(core),
        f"How do I fix this: {core}?",
        f"Why does this happen: {core}?",
        f"Troubleshoot {topic_text} on my Galaxy",
        f"Help with {topic_text}",
    ]
    distinct = list(dict.fromkeys(_sentence(item) for item in candidates if item.strip()))
    return distinct[:10]
