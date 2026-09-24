"""Tests for catalog-backed deeplink mapping using synthetic TEST DATA."""

from app.services.deeplink_mapper import map_action, map_actions


CATALOG = [
    {
        "id": "battery-parent",
        "target_screen": "Battery Settings",
        "description": "Battery settings menu",
        "is_parent": True,
        "deeplink": "test://battery-settings",
    },
    {
        "id": "battery-child",
        "target_screen": "Battery Usage Details",
        "description": "View battery usage details and app drain",
        "message": "Battery drains quickly",
        "deeplink": "test://battery-usage-details",
    },
    {
        "id": "camera",
        "target_screen": "Camera Settings",
        "description": "Camera cannot open or focus",
        "deeplink": "test://camera-settings",
    },
    {
        "id": "network-basic",
        "target_screen": "Network Settings",
        "description": "Network settings",
        "deeplink": "test://network",
    },
    {
        "id": "network-advanced",
        "target_screen": "Network Settings Advanced",
        "description": "Network settings",
        "deeplink": "test://network-advanced",
    },
]


def test_exact_action_copies_uri_verbatim() -> None:
    result = map_action({"target_screen": "Camera Settings"}, CATALOG)
    assert result.resolved is True
    assert result.target_screen == "Camera Settings"
    assert result.deeplink == "test://camera-settings"
    assert result.confidence == 1.0
    assert result.evidence["retrieval"]


def test_paraphrase_uses_metadata_and_hybrid_retrieval() -> None:
    result = map_action({"description": "my battery drains quickly"}, CATALOG)
    assert result.resolved is True
    assert result.target_screen == "Battery Usage Details"
    assert result.deeplink == "test://battery-usage-details"


def test_ambiguous_action_is_rejected() -> None:
    result = map_action({"description": "network settings"}, CATALOG)
    assert result.resolved is False
    assert result.deeplink is None
    assert result.ambiguous is True


def test_manual_action_has_no_actionable_deeplink() -> None:
    result = map_action({"action": "Restart the phone", "action_type": "manual"}, CATALOG)
    assert result.manual is True
    assert result.resolved is False
    assert result.deeplink is None


def test_multiple_interactions_remain_one_action_mapping() -> None:
    result = map_action(
        {
            "target_screen": "Battery Usage Details",
            "interactions": ["open battery usage", "review app drain"],
        },
        CATALOG,
    )
    assert result.resolved is True
    assert result.target_screen == "Battery Usage Details"
    assert result.deeplink == "test://battery-usage-details"


def test_parent_menu_trap_is_not_accepted() -> None:
    result = map_action({"target_screen": "Battery Settings"}, CATALOG)
    assert result.resolved is False
    assert result.parent_level_only is True
    assert result.deeplink is None


def test_invalid_mapping_is_rejected_without_uri_generation() -> None:
    result = map_action({"target_screen": "Imaginary Diagnostics"}, CATALOG)
    assert result.resolved is False
    assert result.target_screen is None
    assert result.deeplink is None


def test_batch_mapping_preserves_order() -> None:
    results = map_actions(
        [{"target_screen": "Camera Settings"}, {"action": "Restart manually", "manual": True}],
        CATALOG,
    )
    assert [result.target_screen for result in results] == ["Camera Settings", None]
