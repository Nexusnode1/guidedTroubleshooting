"""Hard negatives: a complaint about one feature must not be answered with another's plan or screen.

Three layers are covered:

- cache key weights (no embedding model needed): boilerplate-framed paraphrases and
  critical-action keys are weaker evidence than the complaint's own wording, and a
  remedy step cannot outrank a confident match on the complaint itself;
- exact-label deeplink matching against the official catalog;
- the warmed semantic cache with the real embedding model (``acceptance``): out-of-scope
  complaints fall back instead of borrowing a Display plan.
"""

from __future__ import annotations

import pytest

from app.services.key_matcher import KeyIndex
from app.services.plan_builder import PlanBuilder
from app.services.plan_cache import AUXILIARY_KEY_WEIGHT, INTENT_CONFIDENCE, PlanCache, _plan_keys
from app.services.troubleshooting_service import TroubleshootingService
from app.services.variations import framed_variations, normalize_query


class AxisModel:
    """Gives every distinct text its own axis, so raw similarities are exactly 0 or 1.

    ``alias`` makes a probe text point along the axes of other texts, which lets a test
    say "this query is equally close to these keys" without a real embedding model.
    """

    def __init__(self, size: int = 256) -> None:
        self._size = size
        self._axes: dict[str, int] = {}
        self._aliases: dict[str, list[str]] = {}

    def alias(self, text: str, *targets: str) -> str:
        self._aliases[normalize_query(text)] = [normalize_query(target) for target in targets]
        return text

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._size
        for target in self._aliases.get(text, [text]):
            vector[self._axes.setdefault(target, len(self._axes))] = 1.0
        return vector


def _build(catalog, siis_rows, row_id):
    row = next(r for r in siis_rows if r["id"] == row_id)
    siis = row["siis_response"]
    build = PlanBuilder(catalog).build(row["original_query"], siis["content"], siis["title"])
    assert build is not None and build.errors == (), row_id
    return row["original_query"], build


@pytest.fixture(scope="module")
def touch(catalog, siis_rows):
    """row_21: a plan with auto, manual, and critical actions."""
    return _build(catalog, siis_rows, "row_21")


@pytest.fixture(scope="module")
def cracked(catalog, siis_rows):
    return _build(catalog, siis_rows, "row_14")


def _cache(catalog, model, *plans, threshold=0.0):
    cache = PlanCache(catalog, model=model, threshold=threshold)
    for entry_id, (query, build) in plans:
        cache.add(entry_id, query, build.query_variations, build.response)
    return cache


def _plain_variations(query, build):
    framed = set(framed_variations(query))
    return [text for text in build.query_variations[1:] if text not in framed]


def _action_keys(build, *categories):
    actions = build.response["contexts"][0]["actions"]
    return [key for key, action in zip(_plan_keys(build.response), actions) if action["category"] in categories]


# --- cache key weights -------------------------------------------------------------------


def test_the_complaints_own_wording_scores_at_full_weight(catalog, touch):
    query, build = touch
    model = AxisModel()
    cache = _cache(catalog, model, ("touch", touch))
    for text in _plain_variations(query, build):
        hit = cache.lookup(model.alias("probe", text))
        assert hit.similarity == 1.0 and hit.exact is False, text


def test_boilerplate_framed_paraphrases_score_at_the_auxiliary_weight(catalog, touch):
    query, build = touch
    framed = framed_variations(query)
    assert len(framed) == 5 and set(framed) <= set(build.query_variations)
    assert 0.0 < AUXILIARY_KEY_WEIGHT < 1.0
    model = AxisModel()
    cache = _cache(catalog, model, ("touch", touch))
    for text in framed:
        assert cache.lookup(model.alias("probe", text)).similarity == pytest.approx(AUXILIARY_KEY_WEIGHT), text


def test_critical_action_keys_are_auxiliary_and_safe_action_keys_are_not(catalog, touch):
    _, build = touch
    critical, safe = _action_keys(build, "critical"), _action_keys(build, "auto", "manual")
    assert critical and safe
    model = AxisModel()
    cache = _cache(catalog, model, ("touch", touch))
    for text in critical:
        assert cache.lookup(model.alias("probe", text)).similarity == pytest.approx(AUXILIARY_KEY_WEIGHT), text
    for text in safe:
        assert cache.lookup(model.alias("probe", text)).similarity == 1.0, text


def test_a_query_that_only_echoes_boilerplate_falls_back(catalog, touch):
    query, build = touch
    model = AxisModel()
    cache = _cache(catalog, model, ("touch", touch), threshold=0.9)
    assert cache.lookup(model.alias("echo", framed_variations(query)[1])) is None
    assert cache.lookup(model.alias("restart", _action_keys(build, "critical")[0])) is None
    assert cache.lookup(model.alias("real", _plain_variations(query, build)[0])) is not None


def test_genuine_wording_outranks_boilerplate_at_equal_raw_similarity(catalog, touch, cracked):
    model = AxisModel()
    cache = _cache(catalog, model, ("touch", touch), ("cracked", cracked))
    probe = model.alias("probe", framed_variations(touch[0])[2], _plain_variations(*cracked)[0])
    assert cache.lookup(probe).entry.entry_id == "cracked"
    assert [hit.entry.entry_id for hit in cache.top_matches(probe, k=2)] == ["cracked", "touch"]


def test_equal_scores_resolve_to_the_plan_stored_first_every_time(catalog, touch, cracked):
    plans = {"touch": touch, "cracked": cracked}
    for order in (("touch", "cracked"), ("cracked", "touch")):
        model = AxisModel()
        cache = _cache(catalog, model, *((name, plans[name]) for name in order))
        probe = model.alias("probe", _plain_variations(*touch)[0], _plain_variations(*cracked)[0])
        assert {cache.lookup(probe).entry.entry_id for _ in range(5)} == {order[0]}
        assert [hit.entry.entry_id for hit in cache.top_matches(probe, k=2)] == list(order)


def test_weights_do_not_change_the_stored_plan_or_its_variations(catalog, touch):
    query, build = touch
    cache = _cache(catalog, AxisModel(), ("touch", touch))
    entry = cache.lookup(query).entry
    assert entry.response == build.response and list(entry.variations) == build.query_variations


# --- intent evidence over remedy evidence ------------------------------------------------


def test_a_remedy_step_cannot_outrank_a_confident_intent_match(catalog, touch, cracked):
    """Equal raw similarity to one plan's action key and another plan's complaint wording:
    the complaint decides, whichever plan was stored first."""
    plans = {"touch": touch, "cracked": cracked}
    for order in (("touch", "cracked"), ("cracked", "touch")):
        model = AxisModel()
        cache = _cache(catalog, model, *((name, plans[name]) for name in order))
        probe = model.alias("probe", _action_keys(touch[1], "auto", "manual")[0], _plain_variations(*cracked)[0])
        hit = cache.lookup(probe)
        assert hit.similarity >= INTENT_CONFIDENCE
        assert hit.entry.entry_id == "cracked", order
        ranked = cache.top_matches(probe, k=2)
        assert [match.entry.entry_id for match in ranked] == ["cracked", "touch"]
        assert ranked[1].similarity < ranked[0].similarity


def test_a_remedy_step_still_decides_when_no_complaint_is_recognised(catalog, touch, cracked):
    """Below the confidence level the intent keys have no say: the action key is the best
    evidence there is, and the query that asks for that action is answered by its plan."""
    model = AxisModel()
    cache = _cache(catalog, model, ("cracked", cracked), ("touch", touch))
    probe = model.alias(
        "probe", _action_keys(touch[1], "auto", "manual")[0], framed_variations(cracked[0])[0], "unrelated words"
    )
    hit = cache.lookup(probe)
    assert hit.entry.entry_id == "touch"
    assert hit.similarity < INTENT_CONFIDENCE


def test_a_query_that_names_only_an_action_is_answered_at_full_strength(catalog, touch):
    model = AxisModel()
    cache = _cache(catalog, model, ("touch", touch))
    for text in _action_keys(touch[1], "auto", "manual"):
        assert cache.lookup(model.alias("probe", text)).similarity == 1.0, text


def test_a_plans_own_action_and_intent_evidence_do_not_conflict(catalog, touch, cracked):
    model = AxisModel()
    cache = _cache(catalog, model, ("cracked", cracked), ("touch", touch))
    probe = model.alias("probe", _action_keys(touch[1], "auto", "manual")[0], _plain_variations(*touch)[0])
    assert cache.lookup(probe).entry.entry_id == "touch"
    assert [hit.entry.entry_id for hit in cache.top_matches(probe, k=1)] == ["touch"]


# --- exact-label deeplink matching -------------------------------------------------------


@pytest.fixture(scope="module")
def index(catalog):
    return KeyIndex(catalog)


@pytest.mark.parametrize(
    "steps, expected, never",
    [
        (["Go to Settings.", "Tap Connections.", "Tap Bluetooth."], "DL-0044", {"DL-0313", "DL-0573", "DL-0574"}),
        (["Go to Settings.", "Tap Connections.", "Tap Wi-Fi."], "DL-0313", {"DL-0044", "DL-0494", "DL-0495"}),
        (["Tap Connections.", "Tap Mobile networks."], "DL-0529", {"DL-0313", "DL-0573", "DL-0574"}),
    ],
)
def test_connectivity_screens_resolve_to_their_own_entry(index, catalog_by_id, steps, expected, never):
    entry = index.find(steps, "").entry
    assert entry["id"] == expected and entry["id"] not in never
    assert entry["deeplink"] == catalog_by_id[expected]["deeplink"]


@pytest.mark.parametrize(
    "steps, context, expected",
    [
        (["Tap Bluetooth."], "Turn on Bluetooth", "DL-0495"),
        (["Tap Bluetooth."], "Turn off Bluetooth", "DL-0494"),
        (["Tap Mobile data."], "Enable Mobile data", "DL-0082"),
        (["Tap Mobile data."], "Disable Mobile data", "DL-0081"),
    ],
)
def test_toggles_follow_the_named_feature_and_direction(index, steps, context, expected):
    assert index.find(steps, context).entry["id"] == expected


@pytest.mark.parametrize("steps", [["Go to Settings."], ["Open Settings."], ["Navigate to and open Settings."]])
def test_the_generic_settings_root_is_never_a_target_screen(index, steps):
    assert index.find(steps, "") is None


@pytest.mark.parametrize(
    "steps, expected",
    [
        (["Open Settings.", "Tap Battery."], "DL-0560"),
        (["Open Settings.", "Tap Battery.", "Tap Power saving."], "DL-0519"),
        (["Open Settings.", "Tap Display.", "Tap Brightness."], "DL-0232"),
        (["Open Settings.", "Tap Display.", "Tap Screen timeout."], "DL-0220"),
        (["Open Settings.", "Tap Notifications."], "DL-0501"),
    ],
)
def test_the_most_specific_screen_tapped_wins_over_its_parent_menu(index, steps, expected):
    assert index.find(steps, "").entry["id"] == expected


@pytest.mark.parametrize(
    "label",
    ["Display", "Storage", "Memory", "Accounts and backup", "Security and privacy", "Permission manager", "Privacy"],
)
def test_a_screen_with_no_catalog_entry_is_not_credited_to_a_similar_one(index, label):
    assert index.find([f"Tap {label}."], "") is None


@pytest.mark.parametrize("button", ["Power off", "Restart"])
def test_power_menu_buttons_never_resolve_to_a_settings_screen(index, button):
    assert index.find(["Press and hold the Power button.", f"Tap {button}."], "") is None


# --- warmed semantic cache, real embedding model -----------------------------------------

OUT_OF_SCOPE = {
    "wifi_vs_bluetooth": [
        "my wifi keeps dropping every few minutes",
        "wi-fi is connected but there is no internet",
    ],
    "mobile_network_vs_wifi": [
        "no signal bars, my phone says emergency calls only",
        "my sim card is not detected",
    ],
    "sound_vs_display": [
        "there is no sound coming from my phone speaker",
        "This is so annoying - no sound from speaker, please help!",
    ],
    "battery_vs_performance": [
        "my battery drains really fast",
        "phone gets hot and battery dies by noon",
    ],
    "storage_vs_memory": [
        "my phone says storage is full",
        "not enough memory to install the update",
        "apps keep closing because RAM is full",
    ],
    "notification_vs_call": [
        "notifications are delayed by several minutes",
        "my calls keep dropping after a few seconds",
        "people cannot hear me during phone calls",
    ],
    "account_vs_security": [
        "how do I remove my account from the phone",
        "my fingerprint unlock stopped working",
        "I forgot my lock screen PIN",
    ],
    "permissions_vs_privacy": [
        "an app keeps asking for location permission",
        "how do I clear my browsing history",
    ],
    "restart_vs_shutdown": [
        "how do I schedule an automatic restart",
        "how do I turn my phone off",
        "my phone keeps shutting down by itself",
    ],
    "generic_vs_specific_settings": [
        "how do I open settings",
        "how do I change the font size",
        "how do I change the screen timeout",
    ],
    "boilerplate_only": [
        "This is so annoying - the camera photos are blurry, please help!",
        "How do I fix this: keyboard keeps autocorrecting wrong?",
        "Why does this happen: alarm does not ring?",
    ],
}
IN_SCOPE = [
    ("my phone screen is black and will not turn on", "Blank black display"),
    ("my phone screen is cracked and broken", "Cracked bleeding screen"),
    ("touchscreen is laggy and not responding to my taps", "Touchscreen issues"),
]


@pytest.fixture(scope="module")
def service(catalog, siis_rows):
    from app.config import EMBEDDING_MODEL
    from app.retrieval.st_embedder import load_embedder

    instance = TroubleshootingService(catalog, PlanCache(catalog, model=load_embedder(EMBEDDING_MODEL)))
    instance.warm(siis_rows)
    return instance


@pytest.mark.acceptance
@pytest.mark.parametrize(
    "pair, query", [(pair, query) for pair, queries in OUT_OF_SCOPE.items() for query in queries]
)
def test_out_of_scope_complaints_fall_back_instead_of_borrowing_a_plan(service, pair, query):
    body = service.troubleshoot(query)
    assert body["response"] == {"contexts": []}, pair
    assert body["meta"]["fallback"] == "no_match" and body["meta"]["cache_hit"] is False


@pytest.mark.acceptance
@pytest.mark.parametrize("query, title", IN_SCOPE)
def test_in_scope_complaints_are_still_answered(service, query, title):
    body = service.troubleshoot(query)
    assert body["response"]["contexts"][0]["title"] == title
    assert body["meta"]["cache_hit"] is True


@pytest.mark.acceptance
def test_repeated_lookups_return_identical_plans(service):
    for query, _ in IN_SCOPE:
        first = service.troubleshoot(query)
        second = service.troubleshoot(query)
        assert first["response"] == second["response"]
        assert first["query_variations"] == second["query_variations"]
