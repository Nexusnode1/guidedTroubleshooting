"""Screen resolver tests using clearly labelled synthetic TEST DATA."""

import pytest

from app.services.screen_resolver import resolve_action, resolve_actions


CATALOG = [
    {
        "id": "battery-parent-test",
        "description": "Battery settings menu",
        "target_screen": "Battery Settings",
        "deeplink": "test://battery-settings",
        "is_parent": True,
    },
    {
        "id": "battery-child-test",
        "description": "Battery usage details and app drain",
        "message": "View battery usage details",
        "target_screen": "Battery Usage Details",
        "control_type": "list",
        "deeplink": "test://battery-usage-details",
    },
    {
        "id": "display-test",
        "qna_description": "Adjust display brightness",
        "target_screen": "Display Brightness",
        "deeplink": "test://display-brightness",
    },
    {
        "id": "camera-test",
        "message": "Camera cannot open",
        "target_screen": "Camera Settings",
        "deeplink": "test://camera-settings",
    },
]


def test_exact_screen_match_preserves_catalog_uri() -> None:
    """An exact target screen resolves with high confidence."""
    result = resolve_action({"target_screen": "Battery Usage Details"}, CATALOG)
    assert result.resolved is True
    assert result.target_screen == "Battery Usage Details"
    assert result.deeplink == "test://battery-usage-details"
    assert result.confidence == pytest.approx(1.0)
    assert result.evidence["exact_target_match"] is True


def test_parent_menu_is_not_silently_accepted() -> None:
    """A parent-only target is reported but not returned as resolved."""
    result = resolve_action({"target_screen": "Battery"}, [CATALOG[0]])
    assert result.parent_level_only is True
    assert result.resolved is False
    assert result.deeplink is None


def test_metadata_and_control_type_support_resolution() -> None:
    """Descriptive metadata can resolve an action without URI matching."""
    result = resolve_action({"description": "adjust display brightness", "control_type": "slider"}, CATALOG)
    assert result.resolved is True
    assert result.target_screen == "Display Brightness"
    assert result.evidence["metadata"]


def test_ambiguous_similar_screens_are_not_accepted() -> None:
    """Near-tied candidates produce an explicit ambiguous result."""
    similar = [
        {"description": "network settings", "target_screen": "Network Settings", "deeplink": "test://network"},
        {"description": "network settings", "target_screen": "Network Settings Advanced", "deeplink": "test://network-advanced"},
    ]
    result = resolve_action({"description": "network settings"}, similar)
    assert result.ambiguous is True
    assert result.resolved is False
    assert result.deeplink is None


def test_similar_screen_selects_stronger_explicit_target() -> None:
    """A target with stronger lexical overlap wins over a similar screen."""
    similar = [
        {"description": "camera settings", "target_screen": "Camera Settings", "deeplink": "test://camera"},
        {"description": "camera permissions", "target_screen": "Camera Permissions", "deeplink": "test://permissions"},
    ]
    result = resolve_action({"target_screen": "Camera Settings"}, similar)
    assert result.resolved is True
    assert result.target_screen == "Camera Settings"


def test_nonexistent_screen_returns_unresolved() -> None:
    """No matching catalog screen is represented as unresolved."""
    result = resolve_action({"target_screen": "Imaginary Screen"}, CATALOG)
    assert result.resolved is False
    assert result.target_screen is None
    assert result.deeplink is None
    assert result.confidence == 0.0


def test_manual_action_without_screen_is_unresolved() -> None:
    """Manual actions without a catalog screen do not receive a URI."""
    result = resolve_action({"action": "Restart the phone manually"}, CATALOG)
    assert result.resolved is False
    assert result.deeplink is None


def test_uri_alias_selection_is_stable_and_preserves_catalog_value() -> None:
    """When aliases coexist, the documented URI precedence is deterministic."""
    catalog = [{
        "target_screen": "Wi-Fi Settings",
        "url": "test://url-alias",
        "deeplink": "test://canonical-deeplink",
    }]
    result = resolve_action({"target_screen": "Wi-Fi Settings"}, catalog)
    assert result.resolved is True
    assert result.deeplink == "test://canonical-deeplink"
    assert result.evidence["catalog_uri_field"] == "deeplink"


def test_multiple_actions_are_resolved_independently() -> None:
    """Batch resolution preserves action order."""
    results = resolve_actions(
        [{"target_screen": "Camera Settings"}, {"target_screen": "Display Brightness"}],
        CATALOG,
    )
    assert [result.target_screen for result in results] == ["Camera Settings", "Display Brightness"]
