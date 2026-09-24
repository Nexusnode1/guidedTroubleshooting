"""Tests with clearly labelled in-memory TEST DATA, not official deeplinks."""

import pytest

from app.models.schemas import StructuredTroubleshootingGoal
from app.services.deeplink_mapping import map_deeplink, map_deeplinks


TEST_CATALOG = [
    {
        "id": "battery-parent-test",
        "text": "phone battery settings",
        "target_screen": "Battery Settings",
        "deeplink": "test://battery-settings",
    },
    {
        "id": "battery-child-test",
        "text": "battery usage and app battery drain",
        "target_screen": "Battery Usage Details",
        "deeplink": "test://battery-usage-details",
    },
    {
        "id": "camera-test",
        "text": "camera cannot open",
        "target_screen": "Camera Settings",
        "deeplink": "test://camera-settings",
    },
    {
        "id": "performance-test",
        "text": "phone performance and device care",
        "target_screen": "Device Care",
        "deeplink": "test://device-care",
    },
]


def goal(core: str, normalized: str | None = None) -> StructuredTroubleshootingGoal:
    """Build a provisional structured goal for TEST DATA."""
    normalized = normalized or core
    return StructuredTroubleshootingGoal(
        original_query=core,
        normalized_query=normalized,
        core_intent=core,
        variations=[normalized, core],
        keywords=core.split(),
        is_ambiguous=False,
    )


def test_battery_maps_to_catalog_deeplink() -> None:
    """Battery search returns an existing catalog URL only."""
    match = map_deeplink(goal("battery usage drain"), TEST_CATALOG)
    assert match is not None
    assert match.catalog_entry in TEST_CATALOG
    assert match.deeplink == match.catalog_entry["deeplink"]
    assert match.target_screen == match.catalog_entry["target_screen"]


@pytest.mark.parametrize(
    ("query", "entry_id"),
    [("camera not opening", "camera-test"), ("phone performance slow", "performance-test")],
)
def test_camera_and_performance_map_to_catalog_entries(query: str, entry_id: str) -> None:
    """Common troubleshooting goals select the matching TEST DATA entry."""
    match = map_deeplink(goal(query), TEST_CATALOG)
    assert match is not None
    assert match.catalog_entry["id"] == entry_id


def test_child_screen_is_preferred_when_retrieval_supports_it() -> None:
    """More specific matching target screens win among ranked results."""
    matches = map_deeplinks(goal("battery usage"), TEST_CATALOG)
    assert matches
    assert matches[0].target_screen == "Battery Usage Details"


def test_missing_deeplink_is_never_synthesized() -> None:
    """Entries without a catalog deeplink are excluded from results."""
    catalog = [{"text": "battery issue", "target_screen": "Battery Settings"}]
    assert map_deeplink(goal("battery issue"), catalog) is None


def test_invalid_goal_is_rejected() -> None:
    """The mapper requires the enrichment/goal query fields."""
    with pytest.raises(ValueError):
        map_deeplink({"core_intent": "camera"}, TEST_CATALOG)
