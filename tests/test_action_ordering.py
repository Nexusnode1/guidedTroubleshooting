"""Tests for deterministic action ordering using synthetic mapped actions."""

from app.services.action_ordering import (
    CRITICAL,
    MANUAL,
    STANDARD,
    UNKNOWN,
    order_actions,
    ordered_values,
)


def _action(name: str, category: str, deeplink: str = "test://screen") -> dict[str, str]:
    return {"action": name, "category": category, "deeplink": deeplink}


def test_standard_precedes_critical() -> None:
    critical = _action("Factory reset", "critical", "test://reset")
    standard = _action("Open battery settings", "standard", "test://battery")
    decisions = order_actions([critical, standard])
    assert [decision.action for decision in decisions] == [standard, critical]
    assert [decision.category for decision in decisions] == [STANDARD, CRITICAL]
    assert "standard" in decisions[0].reason


def test_multiple_standard_actions_keep_input_order() -> None:
    first = _action("Open display settings", "configuration")
    second = _action("Adjust brightness", "standard")
    assert [decision.action for decision in order_actions([first, second])] == [first, second]


def test_manual_is_between_standard_and_critical() -> None:
    manual = {"action": "Remove the case manually", "manual": True, "deeplink": None}
    standard = _action("Open settings", "standard")
    critical = _action("Erase all data", "disruptive")
    decisions = order_actions([critical, manual, standard])
    assert [decision.category for decision in decisions] == [STANDARD, MANUAL, CRITICAL]
    assert decisions[1].action is manual
    assert "manual" in decisions[1].reason


def test_critical_only_plan_is_stable() -> None:
    actions = [_action("Reset network", "critical"), _action("Factory reset", "critical")]
    assert ordered_values(actions) == actions


def test_already_ordered_plan_is_unchanged() -> None:
    actions = [_action("Configure Wi-Fi", "standard"), _action("Restart manually", "manual")]
    assert ordered_values(actions) == actions


def test_duplicates_are_preserved_without_reordering_equal_items() -> None:
    duplicate = _action("Open battery settings", "standard")
    critical = _action("Reset device", "critical")
    ordered = ordered_values([duplicate, critical, duplicate])
    assert ordered == [duplicate, duplicate, critical]
    assert ordered[0] is duplicate and ordered[1] is duplicate


def test_unknown_categories_remain_stable_and_explainable() -> None:
    action = {"action": "Unclassified step", "deeplink": "test://unknown"}
    decision = order_actions([action])[0]
    assert decision.category == UNKNOWN
    assert decision.priority == 1
    assert "original relative order" in decision.reason


def test_catalog_interaction_types_use_metadata_not_original_type_alone() -> None:
    actions = [
        {"message": "Enable Wi-Fi", "originalType": "onURL", "deeplink": "test://on"},
        {"message": "Disable Wi-Fi", "originalType": "offURL", "deeplink": "test://off"},
        {"message": "Increase Wi-Fi timeout", "originalType": "updateURL", "deeplink": "test://update"},
        {"message": "Open Wi-Fi settings", "originalType": "onClickURL", "deeplink": "test://click"},
    ]
    decisions = order_actions(actions)
    assert all(decision.category == STANDARD for decision in decisions)
    assert [decision.action for decision in decisions] == actions

    type_only = {"originalType": "onURL", "deeplink": "test://unknown"}
    assert order_actions([type_only])[0].category == UNKNOWN


def test_dummy_positive_fallback_is_standard_only_for_settings_context() -> None:
    action = {
        "message": "Open the relevant Settings screen",
        "description": "Generic Settings screen fallback",
        "deeplink": "bixby://dummy_positive",
        "originalType": "placeholder",
    }
    decision = order_actions([action])[0]
    assert decision.category == STANDARD
    assert "dummy_positive" in decision.reason


def test_critical_descriptive_operation_is_last() -> None:
    standard = {"message": "Enable battery optimization", "originalType": "onURL"}
    critical = {"message": "Restart the device", "originalType": "onClickURL"}
    decisions = order_actions([critical, standard])
    assert [decision.action for decision in decisions] == [standard, critical]
    assert decisions[-1].category == CRITICAL
