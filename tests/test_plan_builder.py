"""End-to-end plan building over the twenty official rows."""

import re

import pytest

from app.models.official_schema import ContextDeeplinkResponse
from app.services.plan_builder import PlanBuilder

RANK = {"auto": 0, "manual": 1, "critical": 2}
GOAL = re.compile(r"^Follow these steps to perform this .+ (?:Troubleshooting|Configuration)$")
URL = re.compile(r"https?://|www\.", re.IGNORECASE)


@pytest.fixture(scope="module")
def builder(catalog):
    return PlanBuilder(catalog)


@pytest.fixture(scope="module")
def builds(builder, siis_rows):
    result = {}
    for row in siis_rows:
        siis = row["siis_response"]
        result[row["id"]] = builder.build(row["original_query"], siis["content"], siis["title"])
    return {row_id: build for row_id, build in result.items() if build is not None}


def _actions(build):
    return build.response["contexts"][0]["actions"]


def _groups(build):
    return [group for action in _actions(build) for group in action["stepGroups"]]


def test_most_rows_build_and_every_built_plan_is_rule_valid(builds):
    assert len(builds) >= 12
    for row_id, build in builds.items():
        assert build.errors == (), row_id


def test_built_plans_satisfy_the_official_schema(builds):
    for build in builds.values():
        ContextDeeplinkResponse.model_validate(build.response)


def test_goal_title_score_and_variations(builds):
    for build in builds.values():
        context = build.response["contexts"][0]
        assert GOAL.match(context["goal"])
        assert 2 <= len(context["title"].split()) <= 3
        assert 0.0 <= context["score"] <= 1.0
        assert 8 <= len(build.query_variations) <= 10


def test_actions_are_ordered_auto_manual_critical(builds):
    for build in builds.values():
        ranks = [RANK[action["category"]] for action in _actions(build)]
        assert ranks == sorted(ranks)


def test_only_auto_actions_carry_deeplinks(builds):
    for build in builds.values():
        for action in _actions(build):
            for group in action["stepGroups"]:
                assert (group["actionableDeeplink"] is not None) == (action["category"] == "auto")


def test_every_deeplink_is_verbatim_from_the_catalog(builds, catalog):
    actionable = {entry["deeplink"] for entry in catalog}
    validation = {entry["validation"]["deeplink"] for entry in catalog if entry.get("validation")}
    for build in builds.values():
        for group in _groups(build):
            if group["actionableDeeplink"]:
                assert group["actionableDeeplink"]["deeplink"] in actionable
            if group["validationDeeplink"]:
                assert group["validationDeeplink"]["deeplink"] in validation


def test_no_urls_in_any_plan_text(builds):
    for build in builds.values():
        context = build.response["contexts"][0]
        texts = [context["goal"], context["title"]]
        for action in context["actions"]:
            texts += [action["actionName"], action["description"]]
            texts += [step for group in action["stepGroups"] for step in group["steps"]]
        assert not any(URL.search(text) for text in texts)


def test_touchscreen_plan_maps_screens_exactly(builds, catalog_by_id):
    links = {g["actionableDeeplink"]["deeplink"] for g in _groups(builds["row_21"]) if g["actionableDeeplink"]}
    assert catalog_by_id["DL-0126"]["deeplink"] in links  # enable Touch sensitivity
    assert catalog_by_id["DL-0125"]["deeplink"] in links  # disable Touch sensitivity
    assert catalog_by_id["DL-0169"]["deeplink"] in links  # Navigation bar


def test_email_plan_links_wifi_first_and_ends_critical(builds, catalog_by_id):
    actions = _actions(builds["row_1"])
    group = actions[0]["stepGroups"][0]
    assert actions[0]["category"] == "auto"
    assert group["actionableDeeplink"]["deeplink"] == catalog_by_id["DL-0313"]["deeplink"]
    assert group["validationDeeplink"]["deeplink"] == catalog_by_id["DL-0313"]["validation"]["deeplink"]
    assert actions[-1]["category"] == "critical"


def test_unrelated_query_is_refused(builder, siis_rows):
    siis = siis_rows[1]["siis_response"]
    assert builder.build("best pasta recipe", siis["content"], siis["title"]) is None


def test_unindexed_settings_screen_uses_the_placeholder(builder):
    build = builder.build("check storage settings", "## Check storage\nGo to Settings. Tap Storage.", "Storage help")
    assert build is not None and build.errors == ()
    action = build.response["contexts"][0]["actions"][0]
    link = action["stepGroups"][0]["actionableDeeplink"]
    assert action["category"] == "auto"
    assert link["deeplink"] == "bixby://dummy_positive"
    assert link["description"] == "Opens the Storage Settings screen"
    assert link["message"] == "Open the Storage screen in Settings"


def test_building_is_deterministic(builder, siis_rows):
    siis = siis_rows[0]["siis_response"]
    first = builder.build(siis_rows[0]["original_query"], siis["content"], siis["title"])
    second = builder.build(siis_rows[0]["original_query"], siis["content"], siis["title"])
    assert first == second


def test_no_title_argument_still_recovers_the_real_title_when_content_has_intro_prose(builder, siis_rows):
    # Regression: the public troubleshoot() API has no title field. row_7's content has a
    # lead-in sentence before its first heading, which used to make the title/goal fall
    # back to the generic "Device Issue" when no title argument was given at all.
    siis = next(r for r in siis_rows if r["id"] == "row_7")["siis_response"]
    build = builder.build("how do I use two apps on screen at once", siis["content"])
    assert build is not None and build.errors == ()
    assert build.response["contexts"][0]["title"] != "Device issue"


def test_no_title_argument_does_not_duplicate_troubleshooting_when_content_starts_with_a_heading(catalog):
    # Regression: content whose very first line is itself a heading ("# Battery draining
    # quickly...") used to make the topic parser re-derive a shorter, redundant title from
    # that heading's own words, producing goals like "...perform this Troubleshooting X
    # Troubleshooting". Recovering the embedded title avoids re-deriving it at all.
    content = (
        "Smartphone,Others Mobile Battery draining quickly on your Galaxy phone "
        "( Smartphone,Others Mobile): # Troubleshooting Fast Battery Drain\n"
        "Let's go through some steps to extend your battery life.\n"
        "## Turn On Power Saving\nGo to Settings. Tap Battery. Tap Power saving.\n"
    )
    build = PlanBuilder(catalog).build("my battery drains really fast", content)
    assert build is not None and build.errors == ()
    context = build.response["contexts"][0]
    assert context["title"] == "Battery draining quickly"
    assert context["goal"].count("Troubleshooting") == 1


def test_a_toggle_setting_named_with_a_critical_keyword_is_auto_not_critical(catalog, catalog_by_id):
    # "Restart the device when needed" is a benign auto-restart-schedule toggle (DL-0479/
    # DL-0480), not an instruction to restart right now. The word "restart" inside the
    # catalog's own setting name must not make this action critical, or drop its deeplink.
    content = (
        "Smartphone,Others Mobile Keep your Galaxy phone running smoothly "
        "( Smartphone,Others Mobile): ## Turn On Restart The Device When Needed\n"
        "Go to Settings. Tap Battery and device care. "
        "Tap the switch next to Restart the device when needed to turn it on.\n"
    )
    build = PlanBuilder(catalog).build("keep my phone running smoothly", content)
    assert build is not None and build.errors == ()
    action = build.response["contexts"][0]["actions"][0]
    assert action["category"] == "auto"
    link = action["stepGroups"][0]["actionableDeeplink"]
    assert link["deeplink"] == catalog_by_id["DL-0480"]["deeplink"]


def test_an_onclickurl_view_setting_named_with_a_critical_keyword_is_also_auto(catalog, catalog_by_id):
    # Same root issue, different originalType: "Inactivity restart" (DL-0124) only opens a
    # settings screen (onClickURL); it does not restart anything by itself.
    content = (
        "Smartphone,Others Mobile Keep your Galaxy phone running smoothly "
        "( Smartphone,Others Mobile): ## Check Inactivity Restart\n"
        "Go to Settings. Tap Battery and device care. Tap Inactivity restart.\n"
    )
    build = PlanBuilder(catalog).build("keep my phone running smoothly", content)
    assert build is not None and build.errors == ()
    action = build.response["contexts"][0]["actions"][0]
    assert action["category"] == "auto"
    assert action["stepGroups"][0]["actionableDeeplink"]["deeplink"] == catalog_by_id["DL-0124"]["deeplink"]


@pytest.mark.parametrize("text", [
    "Press and hold the Power button, then tap Restart. Tap Restart again to confirm.",
    "Navigate to Settings, search for and select Factory data reset, and then tap Factory data reset again. Tap Delete all.",
    "Press and hold the Power button (or Side button) and the Volume down button at the same time. Touch and hold Power off, then tap Safe mode.",
])
def test_genuine_disruptive_instructions_remain_critical_with_no_deeplink(catalog, text):
    # Regression guard for the fix above: an actual "do this destructive thing now"
    # instruction has no catalog entry to resolve to (confirmed: the catalog only ever
    # models View/Toggle/Update actions, never an immediate one-tap destructive action),
    # so it must still be classified critical with no deeplink, exactly as before the fix.
    content = f"Smartphone,Others Mobile Fix a stuck phone ( Smartphone,Others Mobile): ## Last Resort\n{text}\n"
    build = PlanBuilder(catalog).build("my phone is stuck", content)
    assert build is not None and build.errors == ()
    action = build.response["contexts"][0]["actions"][0]
    assert action["category"] == "critical"
    assert action["stepGroups"][0]["actionableDeeplink"] is None
