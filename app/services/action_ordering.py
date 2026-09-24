"""Deterministically order mapped troubleshooting actions.

The catalog's ``originalType`` identifies interaction shape, not safety.  It
is used only with descriptive action metadata; explicit action categories and
risk flags always take precedence.  Objects are never copied or mutated, so
their screen/deeplink mappings remain exact.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
from typing import Any


STANDARD = "standard"
MANUAL = "manual"
CRITICAL = "critical"
UNKNOWN = "unknown"

_CATEGORY_FIELDS = (
    "action_category", "category", "action_type", "type", "kind", "risk_level",
)
_STANDARD_TERMS = frozenset((
    "auto", "standard", "configuration", "config", "settings", "setup", "diagnostic",
    "safe", "routine",
))
_MANUAL_TERMS = frozenset(("manual", "physical", "offline", "instruction"))
_CRITICAL_TERMS = frozenset((
    "critical", "disruptive", "destructive", "reset", "factory_reset", "erase",
    "last_resort",
))
_CRITICAL_TEXT = re.compile(
    r"\b(?:factory\s+reset|reset|restart|reboot|firmware|safe\s+mode|erase|wipe|recovery)\b",
    re.IGNORECASE,
)
_DESCRIPTIVE_FIELDS = (
    "action", "target_screen", "screen", "feature", "name", "label", "title",
    "description", "message", "qna_description", "intent", "query",
)
_INTERACTION_TYPES = frozenset(("onurl", "offurl", "updateurl", "onclickurl"))
_DUMMY_URI = "bixby://dummy_positive"
_RANK = {STANDARD: 0, UNKNOWN: 1, MANUAL: 1, CRITICAL: 2}


@dataclass(frozen=True)
class OrderingDecision:
    """An original action paired with its deterministic ordering explanation."""

    action: Any
    category: str
    priority: int
    reason: str
    original_index: int


def _read(action: Any, field: str, default: Any = None) -> Any:
    """Read a field from mappings, Pydantic-like objects, or dataclasses."""
    if isinstance(action, Mapping):
        return action.get(field, default)
    return getattr(action, field, default)


def _text(action: Any) -> str:
    """Collect descriptive fields while excluding URI and type-only fields."""
    values: list[str] = []
    for field in _DESCRIPTIVE_FIELDS:
        value = _read(action, field)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, (list, tuple)):
            values.extend(item.strip() for item in value if isinstance(item, str) and item.strip())
    return " ".join(values)


def _category(action: Any) -> tuple[str, str]:
    """Return an explicit category and an audit-friendly reason."""
    for field in _CATEGORY_FIELDS:
        value = _read(action, field)
        if isinstance(value, str):
            normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
            if normalized in _CRITICAL_TERMS:
                return CRITICAL, f"explicit {field}={value!r} marks a disruptive/critical action"
            if normalized in _MANUAL_TERMS:
                return MANUAL, f"explicit {field}={value!r} marks a manual/physical action"
            if normalized in _STANDARD_TERMS:
                return STANDARD, f"explicit {field}={value!r} marks a standard configuration action"

    for field in ("critical", "disruptive", "destructive"):
        if _read(action, field) is True:
            return CRITICAL, f"explicit {field}=True marks a disruptive/critical action"
    for field in ("manual", "is_manual"):
        if _read(action, field) is True:
            return MANUAL, f"explicit {field}=True marks a manual action"

    description = _text(action)
    if _CRITICAL_TEXT.search(description):
        return CRITICAL, "descriptive action text names a critical or disruptive operation"

    uri = _read(action, "deeplink")
    original_type = _read(action, "originalType")
    normalized_type = original_type.casefold() if isinstance(original_type, str) else ""
    if uri == _DUMMY_URI and "settings" in description.casefold():
        return STANDARD, "dummy_positive is a catalog fallback for a Settings screen"
    # originalType is only supporting evidence; descriptive metadata must be
    # present before an interaction is treated as standard configuration.
    if normalized_type in _INTERACTION_TYPES and description:
        return STANDARD, (
            f"descriptive metadata plus originalType={original_type!r} identifies a standard action"
        )

    return UNKNOWN, "no recognized category/risk evidence; original relative order is preserved"


def order_actions(actions: Iterable[Any]) -> list[OrderingDecision]:
    """Order mapped actions from least disruptive to most disruptive.

    Sorting is stable: actions with the same category retain input order,
    including duplicates.  Each ``OrderingDecision.action`` is the original
    object, so its action/deeplink mapping is not copied or altered.
    """
    decisions = []
    for index, action in enumerate(actions):
        category, reason = _category(action)
        decisions.append(
            OrderingDecision(
                action=action,
                category=category,
                priority=_RANK[category],
                reason=reason,
                original_index=index,
            )
        )
    return sorted(decisions, key=lambda decision: (decision.priority, decision.original_index))


def ordered_values(actions: Iterable[Any]) -> list[Any]:
    """Return only the original mapped actions in their safe order."""
    return [decision.action for decision in order_actions(actions)]


def order_mapped_actions(actions: Iterable[Any]) -> list[OrderingDecision]:
    """Descriptive alias for pipeline callers handling deeplink mappings."""
    return order_actions(actions)
