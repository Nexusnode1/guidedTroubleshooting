"""Final validation firewall for generated troubleshooting plans.

The model mirrors the supplied participant-kit schema and adds only the
documented output constraints.  Validation is reject-only: it never fills in
missing actions, rewrites text, or normalizes catalog URIs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictStr, ValidationError


class _Condition(str, Enum):
    greater = "greater"
    equal = "equal"
    less = "less"


class _ResultType(str, Enum):
    boolean = "boolean"
    integer = "integer"
    string = "str"
    float = "float"


class _ActionCategory(str, Enum):
    auto = "auto"
    manual = "manual"
    critical = "critical"


class _StrictModel(BaseModel):
    """Strict field types while retaining mapper-only fallback metadata."""

    model_config = ConfigDict(extra="allow", strict=True)


class _ValidationDeeplink(_StrictModel):
    model_config = ConfigDict(extra="allow", strict=False)
    deeplink: StrictStr
    key: StrictStr
    resultType: _ResultType | None = None
    condition: _Condition | None = None
    value: StrictStr | None = None


class _ActionableDeeplink(_StrictModel):
    deeplink: StrictStr
    description: StrictStr
    message: StrictStr | None = ""
    classes: dict[StrictStr, StrictStr] | None = None
    originalType: StrictStr | None = None


class _StepGroup(_StrictModel):
    steps: list[StrictStr]
    validationDeeplink: _ValidationDeeplink | None = None
    actionableDeeplink: _ActionableDeeplink | None = None


class _Action(_StrictModel):
    # Pydantic's strict mode rejects the official JSON string values for an
    # Enum before enum validation can run; the other fields remain strict via
    # their Strict* annotations.
    model_config = ConfigDict(extra="allow", strict=False)
    actionName: StrictStr
    description: StrictStr
    stepGroups: list[_StepGroup]
    category: _ActionCategory = _ActionCategory.manual


class _Goal(_StrictModel):
    goal: StrictStr
    title: StrictStr
    actions: list[_Action]
    score: StrictFloat = Field(ge=0.0, le=1.0)


class _ContextResponse(_StrictModel):
    contexts: list[_Goal]


@dataclass(frozen=True)
class PlanValidationResult:
    """Deterministic validation outcome with ordered, human-readable errors."""

    valid: bool
    errors: tuple[str, ...] = ()
    plan: Mapping[str, Any] | None = None

    def raise_for_errors(self) -> None:
        """Raise a concise error if this result is invalid."""
        if not self.valid:
            raise ValueError("; ".join(self.errors))


_WORD = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")
_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\([^)]*\)")
_WEB_URL = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_ANY_URI = re.compile(r"\b[a-z][a-z0-9+.-]{1,20}://", re.IGNORECASE)
_MULTI_STEP = re.compile(
    r";|\b(?:and|then)\s+(?:open|enable|disable|turn\s+on|turn\s+off|change|select|tap|choose|press|click|navigate|go|restart|reset|check|review)\b",
    re.IGNORECASE,
)
_MULTI_SCREEN = re.compile(
    r"\b(?:battery|display|camera|network|wifi|screen|storage|settings)\b\s*(?:and|&|/)\s*"
    r"\b(?:battery|display|camera|network|wifi|screen|storage|settings)\b",
    re.IGNORECASE,
)
_ORDER = {"auto": 0, "manual": 1, "critical": 2}
_GOAL = re.compile(r"^Follow these steps to perform this .+ (?:Troubleshooting|Configuration)$")


def _catalog_entries(catalog: Mapping[str, Any] | Iterable[Mapping[str, Any]] | None) -> list[Mapping[str, Any]]:
    """Read catalog records without changing their URI values."""
    if catalog is None:
        return []
    if isinstance(catalog, Mapping):
        values = catalog.get("deeplinks")
        if not isinstance(values, list):
            return []
        return [entry for entry in values if isinstance(entry, Mapping)]
    return [entry for entry in catalog if isinstance(entry, Mapping)]


def _catalog_uri_sets(entries: Iterable[Mapping[str, Any]]) -> tuple[set[str], set[str]]:
    """Return actionable and validation URI sets with exact string identity."""
    actionable: set[str] = set()
    validation: set[str] = set()
    for entry in entries:
        uri = entry.get("deeplink")
        if isinstance(uri, str):
            actionable.add(uri)
        nested = entry.get("validation")
        if isinstance(nested, Mapping) and isinstance(nested.get("deeplink"), str):
            validation.add(nested["deeplink"])
    return actionable, validation


def _envelope(plan: Mapping[str, Any]) -> tuple[Mapping[str, Any], Any]:
    """Support the official contexts object and the participant-kit wrapper."""
    if isinstance(plan.get("response"), Mapping) and "contexts" not in plan:
        body = plan["response"]
    else:
        body = plan
    return body, plan.get("query_variations", body.get("query_variations"))


def _scan_urls(value: Any, path: tuple[str, ...], errors: list[str]) -> None:
    """Reject web, markdown, and unapproved URI strings without normalizing."""
    if isinstance(value, str):
        if _WEB_URL.search(value) or _MARKDOWN_LINK.search(value):
            errors.append(f"external/web URL or markdown link at {'.'.join(path)}")
            return
        if _ANY_URI.search(value):
            allowed_deeplink_field = path and path[-1] == "deeplink" and any(
                part in {"actionableDeeplink", "validationDeeplink"} for part in path
            )
            if not allowed_deeplink_field:
                errors.append(f"external URI at {'.'.join(path)}")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _scan_urls(child, (*path, str(key)), errors)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _scan_urls(child, (*path, str(index)), errors)


def _sentence_case_title(title: str) -> bool:
    """Require an initial capital and lowercase-starting later words.

    Tokens beginning with digits (for example ``5G``) and technical tokens
    beginning with lowercase letters (for example ``eSIM``) remain allowed.
    """
    words = _WORD.findall(title)
    if not words or title.upper() == title:
        return False
    return all(not word[0].isupper() for word in words[1:])


def _contains_actionable_deeplink(value: Any) -> bool:
    """Return whether a raw plan contains any actionable deeplink object."""
    if isinstance(value, Mapping):
        if value.get("actionableDeeplink") is not None:
            return True
        return any(_contains_actionable_deeplink(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_actionable_deeplink(child) for child in value)
    return False


def _validate_plan_rules(
    raw_body: Mapping[str, Any],
    raw_variations: Any,
    parsed: _ContextResponse,
    actionable_uris: set[str],
    validation_uris: set[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(raw_variations, list) or not all(isinstance(item, str) for item in raw_variations):
        errors.append("query_variations must be a list of strings")
    elif not 8 <= len(raw_variations) <= 10:
        errors.append("query_variations must contain 8 to 10 values")
    elif len(set(raw_variations)) != len(raw_variations):
        errors.append("query_variations must not contain duplicates")

    raw_contexts = raw_body.get("contexts")
    if not isinstance(raw_contexts, list) or not raw_contexts:
        errors.append("contexts must be a non-empty list")
        return errors

    for goal_index, goal in enumerate(parsed.contexts):
        prefix = f"contexts[{goal_index}]"
        if not _GOAL.match(goal.goal.strip()):
            errors.append(f"{prefix}.goal must read 'Follow these steps to perform this <Topic> Troubleshooting' or 'Configuration'")
        if not 2 <= len(_WORD.findall(goal.title)) <= 3:
            errors.append(f"{prefix}.title must contain 2 to 3 words")
        elif not _sentence_case_title(goal.title):
            errors.append(f"{prefix}.title must use sentence case")
        if not goal.actions:
            errors.append(f"{prefix}.actions must be non-empty")

        previous_priority = -1
        for action_index, action in enumerate(goal.actions):
            action_prefix = f"{prefix}.actions[{action_index}]"
            if not _WORD.findall(action.actionName):
                errors.append(f"{action_prefix}.actionName must be a physical screen/feature name")
            if _MULTI_SCREEN.search(action.actionName):
                errors.append(f"{action_prefix}.actionName must represent one physical screen/feature")
            if _MULTI_STEP.search(action.actionName) or _MULTI_STEP.search(action.description):
                errors.append(f"{action_prefix} combines multiple physical interactions")
            description_words = _WORD.findall(action.description)
            if not 5 <= len(description_words) <= 7:
                errors.append(f"{action_prefix}.description must contain 5 to 7 words")
            if not action.description.startswith("It will"):
                errors.append(f"{action_prefix}.description must start with 'It will'")
            if not action.stepGroups:
                errors.append(f"{action_prefix}.stepGroups must be non-empty")

            priority = _ORDER[action.category.value]
            if priority < previous_priority:
                errors.append(f"{action_prefix} violates auto/manual/critical ordering")
            previous_priority = priority

            for group_index, group in enumerate(action.stepGroups):
                group_prefix = f"{action_prefix}.stepGroups[{group_index}]"
                if not group.steps:
                    errors.append(f"{group_prefix}.steps must be non-empty")
                for step_index, step in enumerate(group.steps):
                    if _MULTI_STEP.search(step):
                        errors.append(f"{group_prefix}.steps[{step_index}] contains multiple interactions")

                actionable = group.actionableDeeplink
                if action.category is _ActionCategory.manual and actionable is not None:
                    errors.append(f"{group_prefix}.actionableDeeplink is forbidden for manual actions")
                if actionable is not None:
                    uri = actionable.deeplink
                    if uri == "bixby://dummy_positive":
                        placeholder_words = (
                            len(_WORD.findall(actionable.description)),
                            len(_WORD.findall(actionable.message or "")),
                        )
                        if not all(5 <= count <= 7 for count in placeholder_words):
                            errors.append(f"{group_prefix}.dummy_positive description and message must each contain 5 to 7 words")
                    elif uri not in actionable_uris:
                        errors.append(f"{group_prefix}.actionableDeeplink is not an exact catalog URI")
                    # URI membership above is authoritative; metadata is
                    # retained exactly and is not rewritten here.
                validation = group.validationDeeplink
                if validation is not None and validation.deeplink not in validation_uris:
                    errors.append(f"{group_prefix}.validationDeeplink is not an exact catalog validation URI")
    return errors


def validate_plan(
    plan: Mapping[str, Any],
    catalog: Mapping[str, Any] | Iterable[Mapping[str, Any]] | None = None,
) -> PlanValidationResult:
    """Validate a plan and return a reject-only deterministic result."""
    errors: list[str] = []
    if not isinstance(plan, Mapping):
        return PlanValidationResult(False, ("plan must be a mapping",), None)
    body, variations = _envelope(plan)
    if not isinstance(body, Mapping):
        return PlanValidationResult(False, ("plan response must be a mapping",), None)

    url_errors: list[str] = []
    _scan_urls(plan, (), url_errors)
    errors.extend(url_errors)
    entries = _catalog_entries(catalog)
    actionable_uris, validation_uris = _catalog_uri_sets(entries)
    try:
        parsed = _ContextResponse.model_validate(body)
    except ValidationError as exc:
        errors.extend(f"schema: {error['loc']}: {error['msg']}" for error in exc.errors())
        return PlanValidationResult(False, tuple(errors), None)

    if not entries and _contains_actionable_deeplink(body):
        errors.append("catalog is required for actionable deeplink validation")

    errors.extend(_validate_plan_rules(body, variations, parsed, actionable_uris, validation_uris))
    if errors:
        return PlanValidationResult(False, tuple(dict.fromkeys(errors)), None)
    return PlanValidationResult(True, (), parsed.model_dump(mode="python"))


def validate_plan_or_raise(
    plan: Mapping[str, Any],
    catalog: Mapping[str, Any] | Iterable[Mapping[str, Any]] | None = None,
) -> Mapping[str, Any]:
    """Validate or raise, for callers that require a hard firewall."""
    result = validate_plan(plan, catalog)
    result.raise_for_errors()
    return result.plan or {}
