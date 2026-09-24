"""Steps map to catalog entries by the exact Settings label they tap."""

import pytest

from app.services.key_matcher import DUMMY_URI, KeyIndex, normalize_label, tap_targets


def test_tap_targets_skip_the_settings_root():
    assert tap_targets(["Go to Settings.", "Tap Connections.", "Tap Wi-Fi."]) == ["Connections", "Wi-Fi"]


def test_tap_targets_trim_trailing_clauses():
    assert tap_targets(["Tap the switch next to Touch sensitivity to disable it."]) == ["Touch sensitivity"]


def test_tap_targets_ignore_action_buttons():
    assert tap_targets(["Tap Clear cache.", "Tap OK.", "Tap Restart again to confirm.", "Tap Safe mode."]) == []


def test_normalize_label_ignores_case_and_punctuation():
    assert normalize_label("Wi-Fi") == normalize_label("wi fi") == "wi fi"


@pytest.fixture(scope="module")
def index(catalog):
    return KeyIndex(catalog)


def test_wifi_opens_the_plain_screen_by_default(index, catalog_by_id):
    choice = index.find(["Go to Settings.", "Tap Connections.", "Tap Wi-Fi."], "")
    assert choice.entry["id"] == "DL-0313"
    assert choice.entry["deeplink"] == catalog_by_id["DL-0313"]["deeplink"]


@pytest.mark.parametrize("context, expected", [("Enable Wi-Fi", "DL-0574"), ("Disable Wi-Fi", "DL-0573")])
def test_toggle_direction_follows_the_text(index, context, expected):
    assert index.find(["Tap Wi-Fi."], context).entry["id"] == expected


def test_touch_sensitivity_on_and_off(index):
    steps = ["Tap Display.", "Tap the switch next to Touch sensitivity."]
    assert index.find(steps, "enable it").entry["id"] == "DL-0126"
    assert index.find(steps, "disable it").entry["id"] == "DL-0125"


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("Tap the switch next to Touch sensitivity to turn it off.", "DL-0125"),
        ("Tap the switch next to Touch sensitivity to turn it on.", "DL-0126"),
    ],
)
def test_turn_it_on_or_off_with_an_interposed_word_is_still_detected(index, phrase, expected):
    # "turn it off"/"turn it on" is natural phrasing but has a word between "turn" and
    # "off"/"on"; missing it must not leave "switch next to" (present in almost every
    # toggle instruction, and unrelated to direction) to force the *other* direction.
    assert index.find([phrase], phrase).entry["id"] == expected


def test_unindexed_labels_do_not_match(index):
    assert index.find(["Tap Safe mode."], "") is None
    assert index.find(["Tap Storage."], "") is None


def test_the_placeholder_is_never_a_match(index, catalog):
    for entry in catalog:
        choice = index.find([f"Tap {entry.get('message') or 'Nothing'}."], "")
        assert choice is None or choice.entry["deeplink"] != DUMMY_URI


def test_a_multi_word_label_containing_a_connector_word_is_not_truncated(index):
    # "Put unused apps to sleep" is the catalog's own label; the trailing-clause
    # trimmer must not mistake the "to" inside the label for a trailing clause.
    steps = ["Go to Settings.", "Tap Battery.", "Tap Put unused apps to sleep."]
    choice = index.find(steps, "")
    assert choice.entry["id"] == "DL-0544"


def test_a_longer_real_label_wins_over_a_shorter_one_that_shadows_it(index):
    # An earlier step taps a real, shorter label ("Battery"); the later, more specific
    # step ("Put unused apps to sleep") is what the instruction is actually about and
    # must be preferred, even though its own trimmed candidate is only "Put unused apps".
    steps = ["Tap Battery and device care.", "Tap the switch next to Put unused apps to sleep to enable it."]
    choice = index.find(steps, "enable it")
    assert choice.entry["id"] == "DL-0417"


def test_known_limitation_an_unmatched_specific_target_falls_back_to_an_ancestor_screen(index):
    # Documents a known, deliberately-not-fixed limitation (see key_matcher.find's
    # docstring and docs/cross_domain_generalization.md): "Optimize now" has no catalog
    # entry (DL-0538 has no validation.key), so this returns the ancestor "Battery" screen
    # instead of correctly giving up -- a parent-menu match. A fix for this regressed the
    # official row_21 case (test_touchscreen_plan_maps_screens_exactly), so it was reverted;
    # this test exists so a future attempt is judged against both cases, not just this one.
    steps = ["Go to Settings.", "Tap Battery and device care.", "Tap Optimize now."]
    choice = index.find(steps, "")
    assert choice is not None and choice.entry["id"] == "DL-0560"


def test_known_limitation_a_key_starting_with_a_not_a_screen_word_can_be_lost_to_trimming(index):
    # Narrow, discovered-but-unfixed limitation: "Restart on schedule" (DL-0419) is trimmed
    # to bare "Restart" (the trailing-clause trimmer cuts at "on"), and "restart" alone is in
    # _NOT_A_SCREEN, so the candidate is dropped before find() ever gets a chance to extend it
    # from the untrimmed text. It then falls back to the earlier "Battery" ancestor screen --
    # the same parent-menu-match pattern as the "Optimize now" limitation above, just reached
    # through the trimmer/filter instead of a missing catalog key. Confirmed to affect only
    # this one entry in the real catalog (the only key of the shape "<excluded word> on/to/...
    # <rest>"). Sidestepped in the test suite with "Inactivity restart" (no connector word)
    # instead; see test_plan_builder.py::test_an_onclickurl_view_setting_named_with_a_critical_keyword_is_also_auto.
    steps = ["Go to Settings.", "Tap Battery and device care.", "Tap Restart on schedule."]
    choice = index.find(steps, "")
    assert choice is not None and choice.entry["id"] == "DL-0560"
