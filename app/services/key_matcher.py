"""Match SIIS steps to catalog deeplinks by the exact UI label they tap.

Catalog ``validation.key`` values are the literal Settings labels ("Wi-Fi",
"Navigation bar"). The URI itself is never a match feature and is copied
verbatim from the matched entry.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

DUMMY_URI = "bixby://dummy_positive"

_TAP = re.compile(
    r"\b(?i:tap|select|touch|choose|open)(?:\s+(?i:and\s+hold))?(?:\s+(?i:on))?"
    r"(?:\s+(?i:the))?(?:\s+(?i:switch\s+next\s+to))?"
    r"\s+([A-Z][A-Za-z0-9+\-/()' ]*?)(?=\s*(?:[,.;:]|$))"
)
_TRIM = re.compile(
    r"\s+(?:to|again|for|if|when|and|then|in|on|from|at|until|so|because)\b.*$", re.IGNORECASE
)
_NOT_A_SCREEN = frozenset(
    {
        "ok", "settings", "restart", "reset", "delete all", "clear cache", "clear data",
        "safe mode", "power off", "power", "recents", "home",
    }
)
_TURN_OFF = re.compile(
    r"\b(?:turn\s+(?:\w+\s+)?off|disable|switch\s+off|toggle\s+off)\b", re.IGNORECASE
)
_TURN_ON = re.compile(
    r"\b(?:turn\s+(?:\w+\s+)?on|enable|switch\s+on|toggle\s+on|switch\s+next\s+to)\b", re.IGNORECASE
)


def normalize_label(text: str) -> str:
    """Lower-case a UI label and collapse punctuation for exact comparison."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _tap_candidates(steps: Iterable[str]) -> list[tuple[str, str]]:
    """Return (raw, trimmed) label pairs for every tap found in ``steps``, in order.

    ``raw`` keeps whatever followed the tap verb up to the next punctuation mark;
    ``trimmed`` is that same span with a likely trailing clause ("...to disable it")
    cut off. Matching prefers ``trimmed`` but falls back to ``raw`` so a catalog key
    that itself contains a connector word ("Put unused apps to sleep") is not lost
    to over-eager trimming.
    """
    candidates: list[tuple[str, str]] = []
    for step in steps:
        for match in _TAP.finditer(step):
            raw = match.group(1).strip()
            trimmed = _TRIM.sub("", raw).strip()
            if trimmed and normalize_label(trimmed) not in _NOT_A_SCREEN:
                candidates.append((raw, trimmed))
    return candidates


def tap_targets(steps: Iterable[str]) -> list[str]:
    """Return the UI labels tapped by ``steps`` in order, excluding action buttons."""
    return [trimmed for _, trimmed in _tap_candidates(steps)]


@dataclass(frozen=True)
class DeeplinkChoice:
    """A catalog entry chosen for a step group and the label that matched it."""

    entry: Mapping[str, Any]
    target: str


class KeyIndex:
    """Index of catalog entries by their exact Settings label."""

    def __init__(self, catalog: Iterable[Mapping[str, Any]]) -> None:
        self._by_key: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for entry in catalog:
            validation = entry.get("validation")
            key = validation.get("key") if isinstance(validation, Mapping) else None
            if isinstance(key, str) and entry.get("deeplink") != DUMMY_URI:
                self._by_key[normalize_label(key)].append(entry)

    def find(self, steps: Sequence[str], context: str) -> DeeplinkChoice | None:
        """Pick the entry for the last tapped label that exists in the catalog.

        A label can be trimmed short of a longer real key when the key itself contains
        a connector word ("Put unused apps **to** sleep"): the generic trailing-clause
        trimmer cuts at that word before the exact lookup ever runs. When the trimmed
        label has no exact match, this also checks whether the *untrimmed* tap text
        extends exactly one catalog key by whole words, grounding the recovery in what
        the sentence actually said rather than in catalog vocabulary alone (so a bare
        "Storage" does not get credited to the unrelated, longer key "Storage Share").

        KNOWN LIMITATION (see docs/cross_domain_generalization.md): when the last tap has
        no catalog entry, this walks back to an earlier one in the same step group. That is
        correct when the earlier tap is the real destination and the last one is just an
        in-screen option on it (official row_21: "tap Navigation bar" -> "select Buttons"
        must resolve to Navigation bar). It is wrong when the last tap was meant to be a
        more specific destination that simply is not in the catalog (synthetic
        "performance_optimize_one_tap": "Tap Battery and device care" -> "Tap Optimize now"
        wrongly resolves to the parent "Battery" screen). These two shapes are not
        distinguishable from the text alone with the current approach; fixing one
        regresses the other, confirmed by testing both. Left as the safer, official-data-
        proven behavior rather than trading a real-row regression for a synthetic-row fix.
        """
        for raw, trimmed in reversed(_tap_candidates(steps)):
            entries = self._by_key.get(normalize_label(trimmed)) or self._extended_match(normalize_label(raw))
            if entries:
                return DeeplinkChoice(_pick(entries, context), trimmed)
        return None

    def _extended_match(self, normalized_raw: str) -> list[Mapping[str, Any]] | None:
        """Return the entries of the one stored key equal to, or extended by, ``normalized_raw``."""
        candidates = [
            entries
            for key, entries in self._by_key.items()
            if normalized_raw == key or normalized_raw.startswith(key + " ")
        ]
        return candidates[0] if len(candidates) == 1 else None


def _pick(entries: Sequence[Mapping[str, Any]], context: str) -> Mapping[str, Any]:
    """Prefer the toggle direction the text asks for, else the plain open entry."""
    order = ["onClickURL", "onURL", "updateURL", "offURL"]
    if _TURN_OFF.search(context):
        order.insert(0, "offURL")
    elif _TURN_ON.search(context):
        order.insert(0, "onURL")
    for original_type in order:
        for entry in entries:
            if entry.get("originalType") == original_type:
                return entry
    return entries[0]
