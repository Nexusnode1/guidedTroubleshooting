"""The pipeline must work outside the Display domain the 20 official rows cover.

The PDF describes four device domains (Battery, Display, Camera, Performance), but every
official siis_responses.json row is a Display complaint. These tests run the same
PlanBuilder against author-written Battery/Camera/Performance articles (see
tests/fixtures/domain_articles.json for provenance) so a regression specific to another
domain cannot hide behind "the Display tests all pass".
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from app.config import EMBEDDING_MODEL
from app.models.official_schema import ContextDeeplinkResponse
from app.retrieval.st_embedder import load_embedder
from app.services.plan_builder import PlanBuilder
from app.services.plan_cache import PlanCache

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE = json.loads((FIXTURE_DIR / "domain_articles.json").read_text(encoding="utf-8"))
PARAPHRASES = json.loads((FIXTURE_DIR / "paraphrases_domains.json").read_text(encoding="utf-8"))
RANK = {"auto": 0, "manual": 1, "critical": 2}
URL = re.compile(r"https?://|www\.", re.IGNORECASE)
HIT_RATE_TARGET = 0.80


@pytest.fixture(scope="module")
def builds(catalog):
    builder = PlanBuilder(catalog)
    results = {}
    for article in FIXTURE["articles"]:
        siis = article["siis_response"]
        build = builder.build(article["query"], siis["content"], siis["title"])
        assert build is not None, f"{article['id']}: article was gated as irrelevant to its own query"
        results[article["id"]] = build
    return results


def _actions(build):
    return build.response["contexts"][0]["actions"]


def _link(build, action_name: str) -> dict | None:
    for action in _actions(build):
        if action["actionName"] == action_name:
            return action["stepGroups"][0]["actionableDeeplink"]
    raise AssertionError(f"no action named {action_name!r}")


@pytest.mark.parametrize("article", FIXTURE["articles"], ids=lambda a: a["id"])
def test_every_domain_article_builds_a_rule_valid_plan(catalog, article):
    siis = article["siis_response"]
    build = PlanBuilder(catalog).build(article["query"], siis["content"], siis["title"])
    assert build is not None and build.errors == ()
    ContextDeeplinkResponse.model_validate(build.response)
    context = build.response["contexts"][0]
    assert context["title"] == article["expected_title"]
    ranks = [RANK[action["category"]] for action in context["actions"]]
    assert ranks == sorted(ranks)


def test_no_urls_in_any_domain_plan(builds):
    for build in builds.values():
        context = build.response["contexts"][0]
        texts = [context["goal"], context["title"]]
        for action in context["actions"]:
            texts += [action["actionName"], action["description"]]
            texts += [step for group in action["stepGroups"] for step in group["steps"]]
        assert not any(URL.search(text) for text in texts)


def test_every_deeplink_is_verbatim_from_the_catalog(builds, catalog):
    actionable = {entry["deeplink"] for entry in catalog}
    for build in builds.values():
        for action in _actions(build):
            for group in action["stepGroups"]:
                if group["actionableDeeplink"]:
                    assert group["actionableDeeplink"]["deeplink"] in actionable


def test_battery_plain_toggle_uses_the_view_variant_with_no_enable_wording(builds, catalog_by_id):
    link = _link(builds["battery_drain"], "Put Unused Apps To Sleep")
    assert link["deeplink"] == catalog_by_id["DL-0544"]["deeplink"]


def test_performance_explicit_enable_wording_uses_the_onurl_variant(builds, catalog_by_id):
    link = _link(builds["slow_performance"], "Put Unused Apps To Sleep")
    assert link["deeplink"] == catalog_by_id["DL-0417"]["deeplink"]


def test_performance_profile_and_camera_access_resolve_to_their_catalog_entries(builds, catalog_by_id):
    assert _link(builds["slow_performance"], "Adjust Performance Profile")["deeplink"] == catalog_by_id["DL-0418"]["deeplink"]
    assert _link(builds["camera_crash"], "Check Camera Access")["deeplink"] == catalog_by_id["DL-0197"]["deeplink"]


def test_a_camera_screen_with_no_catalog_entry_uses_the_documented_placeholder(builds):
    # There is no "Storage" deeplink in the catalog; the engine must say so honestly
    # (bixby://dummy_positive) rather than inventing or omitting the action.
    link = _link(builds["camera_crash"], "Clear The Camera App Cache")
    assert link["deeplink"] == "bixby://dummy_positive"
    assert 5 <= len(link["description"].split()) <= 7


@pytest.mark.acceptance
def test_paraphrase_hit_rate_holds_outside_the_display_domain(catalog):
    """The 80% target (tests/test_acceptance.py) must not be an artifact of Display-only data."""
    builder = PlanBuilder(catalog)
    cache = PlanCache(catalog, model=load_embedder(EMBEDDING_MODEL))
    for article in FIXTURE["articles"]:
        siis = article["siis_response"]
        build = builder.build(article["query"], siis["content"], siis["title"])
        assert build is not None and build.errors == ()
        cache.add(article["id"], article["query"], build.query_variations, build.response)

    correct = 0
    for item in PARAPHRASES["positives"]:
        hit = cache.lookup(item["query"])
        correct += bool(hit) and hit.entry.response["contexts"][0]["title"] == item["expect"]
    rate = correct / len(PARAPHRASES["positives"])
    assert rate >= HIT_RATE_TARGET, f"{correct}/{len(PARAPHRASES['positives'])} = {rate:.0%}"
    assert all(cache.lookup(query) is None for query in PARAPHRASES["negatives"])
