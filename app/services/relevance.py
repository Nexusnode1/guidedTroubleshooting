"""Lexical query-to-article relevance used to refuse articles that do not fit."""

from __future__ import annotations

import re

MIN_RELEVANCE = 0.15
MIN_SHARED_TOKENS = 2
SHORT_QUERY_TOKENS = 4

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be but by can cannot could did do does for from had has have how i if "
    "in into is it its me my no not of on or our so that the their then there this to too up "
    "was we were what when where which who why will with would you your after again all also "
    "any because before being both down each even few get got just more most much new now off "
    "only other out over own same should some such than them these they those through under "
    "until very via while".split()
)
_GENERIC = frozenset(
    "screen samsung galaxy phone mobile tablet device display app apps use using open tap try "
    "turn work make stay see give back look right need still".split()
)


def _stem(token: str) -> str:
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def content_tokens(text: str) -> set[str]:
    """Return stemmed, non-generic content words of ``text``."""
    return {
        _stem(token)
        for token in _TOKEN.findall(text.lower())
        if len(token) > 2 and not token.isdigit() and token not in _STOP and token not in _GENERIC
    }


def relevance(query: str, article_text: str, title: str = "") -> float:
    """Fraction of the query's content words found in the article, or 0.0 if unrelated.

    A word shared with the article title is enough on its own (the title names the
    topic); otherwise at least two words (one for very short queries) must be shared.
    """
    wanted = content_tokens(query)
    if not wanted:
        return 0.0
    shared = wanted & content_tokens(f"{title} {article_text}")
    in_title = bool(wanted & content_tokens(title))
    needed = 1 if len(wanted) <= SHORT_QUERY_TOKENS else MIN_SHARED_TOKENS
    if not in_title and len(shared) < needed:
        return 0.0
    ratio = len(shared) / len(wanted)
    return max(ratio, MIN_RELEVANCE) if in_title else (ratio if ratio >= MIN_RELEVANCE else 0.0)
