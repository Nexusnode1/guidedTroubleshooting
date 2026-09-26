"""Lexical query-to-article relevance used to refuse articles that do not fit."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable
import re

MIN_RELEVANCE = 0.15
MIN_SHARED_TOKENS = 2
SHORT_QUERY_TOKENS = 4
# A word found in at least this share of the knowledge-base articles (vendor and product
# family names, device-class labels) cannot tell articles apart, so it is not evidence
# that a query fits one of them. Only applied when the corpus is large enough to say so.
COMMON_SHARE = 0.7
MIN_CORPUS_ARTICLES = 5

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
    "screen phone mobile tablet device display app apps use using open tap try "
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


def content_tokens(text: str, ignore: Collection[str] = frozenset()) -> set[str]:
    """Return stemmed, non-generic content words of ``text``, minus any in ``ignore``."""
    tokens = {
        _stem(token)
        for token in _TOKEN.findall(text.lower())
        if len(token) > 2 and not token.isdigit() and token not in _STOP and token not in _GENERIC
    }
    return tokens - set(ignore) if ignore else tokens


def common_tokens(articles: Iterable[str]) -> frozenset[str]:
    """Return content words present in most of ``articles`` (document frequency >= COMMON_SHARE).

    Returns an empty set when fewer than MIN_CORPUS_ARTICLES distinct articles are given.
    """
    distinct = list(dict.fromkeys(text for text in articles if text and text.strip()))
    if len(distinct) < MIN_CORPUS_ARTICLES:
        return frozenset()
    counts = Counter(token for text in distinct for token in content_tokens(text))
    return frozenset(token for token, count in counts.items() if count >= COMMON_SHARE * len(distinct))


def relevance(query: str, article_text: str, title: str = "", ignore: Collection[str] = frozenset()) -> float:
    """Fraction of the query's content words found in the article, or 0.0 if unrelated.

    A word shared with the article title is enough on its own (the title names the
    topic); otherwise at least two words (one for very short queries) must be shared.
    Words in ``ignore`` (typically ``common_tokens`` of the knowledge base) never count.
    """
    wanted = content_tokens(query, ignore)
    if not wanted:
        return 0.0
    shared = wanted & content_tokens(f"{title} {article_text}", ignore)
    in_title = bool(wanted & content_tokens(title, ignore))
    needed = 1 if len(wanted) <= SHORT_QUERY_TOKENS else MIN_SHARED_TOKENS
    if not in_title and len(shared) < needed:
        return 0.0
    ratio = len(shared) / len(wanted)
    return max(ratio, MIN_RELEVANCE) if in_title else (ratio if ratio >= MIN_RELEVANCE else 0.0)
