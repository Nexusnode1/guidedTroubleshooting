"""Rule-based parsing of raw SIIS knowledge text into sections and imperative steps.

Nothing is invented: a step is a sentence or clause of the source that already
begins with an imperative verb. URLs and markdown links are removed here so
they can never reach a plan.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_CATEGORY_PREFIX = re.compile(r"\):\s")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HEADING = re.compile(r"(?m)^#{1,4}[ \t]+(.*)$")
_NUMBERING = re.compile(r"^(?:step\s*)?\d+\s*[:.)]\s*", re.IGNORECASE)
_GARBLED = re.compile(r"[A-Za-z,.'’-]{30,}")

_START_VERBS = (
    "tap touch swipe navigate open press select connect check restart turn enable disable "
    "clear charge contact visit schedule use ensure make increase adjust set locate insert "
    "enter remove try go pick choose toggle reset review confirm update drag hold shine "
    "eject plug disconnect reinsert uninstall install inspect examine scan sign log wipe "
    "force back send follow download perform allow reboot power"
).split()
_CHAIN_VERBS = (
    "tap touch swipe navigate open press select connect check restart turn enable disable "
    "clear charge insert enter remove try go pick choose toggle reset review confirm update "
    "drag eject plug disconnect reinsert uninstall install visit contact schedule scan"
).split()
_AND_VERBS = (
    "open|enable|disable|turn on|turn off|change|select|tap|choose|press|click|navigate|"
    "go|restart|reset|check|review"
)
_START = re.compile(rf"(?:{'|'.join(_START_VERBS)})\b", re.IGNORECASE)
_LEAD = re.compile(
    r"^(?:[-*•]\s*)?(?:please|next|then|first|now|finally|also|alternatively|simply|just)[,\s]+",
    re.IGNORECASE,
)
_MODAL = re.compile(
    r"^(?:you\s+(?:can|may|should|need\s+to|will\s+need\s+to)|you'll\s+need\s+to|let's|let\s+us)\s+(?:also\s+)?",
    re.IGNORECASE,
)
_CONDITION = re.compile(
    r"^(?:if|when|once|after|before|on|for|in\s+case|to)\b[^,:]{0,80}[,:]\s*", re.IGNORECASE
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|\n+")
_NAV_AND = re.compile(r"\b(navigate|swipe|go|scroll)\s+to\s+and\s+(?:open|tap|select)\b", re.IGNORECASE)
_NOT_A_STEP = re.compile(
    r"^(?:\w+\s+(?:it|them|this|that)|go\s+through\b.*|try\s+the\s+following\b.*)\.$", re.IGNORECASE
)
_CHAIN = re.compile(
    rf",\s*(?:and\s+)?(?:then\s+)?(?=(?:{'|'.join(_CHAIN_VERBS)})\b)"
    rf"|\s+(?:and\s+)?then\s+(?=(?:{'|'.join(_CHAIN_VERBS)})\b)"
    rf"|;\s*"
    rf"|\s+and\s+(?=(?:{_AND_VERBS})\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Section:
    """One headed block of an article and the imperative steps found in it."""

    heading: str
    body: str
    steps: tuple[str, ...]


def clean_siis_text(content: str) -> str:
    """Drop the leading category prefix, URLs, and markdown link targets."""
    match = _CATEGORY_PREFIX.search(content[:800])
    text = content[match.end():] if match else content
    text = _MARKDOWN_LINK.sub(r"\1", text)
    return _URL.sub("", text).strip()


def embedded_title(content: str) -> str | None:
    """Recover the article's own title from its "<categories> <Title> ( <categories>): " prefix.

    The category list appears twice, verbatim, around the title; that repetition (not any
    assumption about what a category name looks like) is what lets this find the title
    without a separately-supplied title field, which the public troubleshoot() API does not
    have. Returns None if the prefix is not in this exact shape.
    """
    match = _CATEGORY_PREFIX.search(content[:800])
    if not match:
        return None
    prefix = content[: match.start()]
    paren = prefix.rfind(" (")
    if paren == -1:
        return None
    categories = prefix[paren + 2 :].strip()
    before = prefix[:paren]
    if not categories or not before.startswith(categories):
        return None
    title = before[len(categories) :].strip()
    return title or None


def _clean_piece(piece: str) -> str:
    piece = piece.strip(" \t-*•:;,")
    for _ in range(3):
        stripped = _MODAL.sub("", _LEAD.sub("", piece), count=1)
        if stripped == piece:
            break
        piece = stripped
    return piece


def is_imperative(text: str) -> bool:
    """Return whether ``text`` starts with a known instruction verb."""
    return bool(_START.match(text.strip()))


def extract_steps(body: str) -> list[str]:
    """Return the imperative clauses of ``body`` in source order."""
    steps: list[str] = []
    for sentence in _SENTENCE.split(_NAV_AND.sub(r"\1 to", body)):
        sentence = _CONDITION.sub("", sentence.strip(), count=1)
        for piece in _CHAIN.split(sentence):
            piece = _clean_piece(piece)
            if not is_imperative(piece) or len(piece.split()) < 2:
                continue
            piece = piece.rstrip(" .!?:;,") + "."
            if _NOT_A_STEP.match(piece):
                continue
            steps.append(piece[0].upper() + piece[1:])
    return steps


def parse_sections(content: str, title: str = "") -> list[Section]:
    """Split an article into sections, stopping at the first garbled section."""
    parts = _HEADING.split(clean_siis_text(content))
    raw = [("", parts[0]), *zip(parts[1::2], parts[2::2])]
    sections: list[Section] = []
    for heading, body in raw:
        body = body.strip()
        if _GARBLED.search(body):
            break
        if not body:
            continue
        heading = _NUMBERING.sub("", heading.strip()) or title
        sections.append(Section(heading, body, tuple(extract_steps(body))))
    return sections
