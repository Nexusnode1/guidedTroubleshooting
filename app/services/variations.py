"""Deterministic query paraphrases in varied registers.

The paraphrases double as the semantic cache key set for a plan, so they must
be reproducible: no randomness, no model calls.
"""

from __future__ import annotations

import re

from app.services.query_enrichment import QueryEnricher
from app.services.query_enrichment import normalize_query as _normalize_text

_MAX_CORE_WORDS = 14
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"(?:\b[a-z][a-z0-9+.-]{1,20}://|www\.)\S*", re.IGNORECASE)
# Registers that wrap the core complaint in fixed wording: formal, casual, frustrated, and
# the two questions. The wording is the same for every plan.
_FRAMES = (
    "I am experiencing an issue with my device: {core}.",
    "my phone is acting up, {core}",
    "This is so annoying - {core}, please help!",
    "How do I fix this: {core}?",
    "Why does this happen: {core}?",
)
_enricher = QueryEnricher()


def normalize_query(query: str) -> str:
    """Return the canonical lower-case form used for cache keys."""
    return _enricher.enrich(query).normalized_query


def strip_urls(text: str) -> str:
    """Return ``text`` without URLs; a markdown link keeps its label. Other text is unchanged."""
    cleaned = _URL.sub(" ", _MARKDOWN_LINK.sub(r"\1", text))
    return text if cleaned == text else " ".join(cleaned.split())


def searchable_text(query: str) -> str:
    """Return the normalized, URL-free text of ``query``; empty when nothing searchable is left."""
    return _normalize_text(strip_urls(query))


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


def _core(query: str) -> str:
    enriched = _enricher.enrich(strip_urls(query))
    return " ".join(enriched.core_intent.split()[:_MAX_CORE_WORDS]) or enriched.normalized_query


def framed_variations(query: str) -> list[str]:
    """Return the paraphrases of ``query`` that wrap its core in fixed wording."""
    core = _core(query)
    return [_sentence(frame.format(core=core)) for frame in _FRAMES]


def generate_variations(query: str, topic: str) -> list[str]:
    """Return 8-10 distinct paraphrases of ``query``.

    Registers: original, formal, casual, keyword-only, frustrated, typo,
    questions, and topic-only phrasings. URLs in ``query`` are left out of every one.
    """
    core = _core(query)
    keywords = " ".join(core.split()[:6])
    topic_text = topic.lower()
    formal, casual, frustrated, how, why = (frame.format(core=core) for frame in _FRAMES)
    candidates = [
        strip_urls(query).strip(),
        formal,
        casual,
        keywords,
        frustrated,
        _with_typo(core),
        how,
        why,
        f"Troubleshoot {topic_text} on my device",
        f"Help with {topic_text}",
    ]
    distinct = list(dict.fromkeys(_sentence(item) for item in candidates if item.strip()))
    return distinct[:10]
