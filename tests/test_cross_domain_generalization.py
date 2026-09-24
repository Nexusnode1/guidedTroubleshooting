"""Regression tests for the SYNTHETIC DOMAIN GENERALIZATION FIXTURE.

Exercises the real, shipped troubleshoot(query, siis_response=...) pipeline against
tests/fixtures/cross_domain_articles.json (author-written Battery/Camera/Performance
articles; see that file's own _disclaimer). No second, parallel pipeline is built here.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from app.retrieval.embeddings import HashEmbeddingModel
from app.services.catalog import load_catalog
from app.services.plan_cache import PlanCache
from app.services.troubleshooting_service import TroubleshootingService

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "cross_domain_articles.json").read_text(encoding="utf-8"))
DOMAINS = {"Battery", "Camera", "Performance"}
DUMMY = "bixby://dummy_positive"
URL = re.compile(r"https?://|www\.", re.IGNORECASE)
KNOWN_LIMITATIONS: set[str] = set()  # performance_want_scheduled_restart was fixed; see plan_builder._build_action


def test_fixture_is_clearly_labeled_synthetic():
    assert FIXTURE["_label"] == "SYNTHETIC DOMAIN GENERALIZATION FIXTURE"
    assert "not official" in FIXTURE["_disclaimer"] or "author-written" in FIXTURE["_disclaimer"]


def test_fixture_has_four_to_six_articles_per_domain_and_twelve_to_eighteen_total():
    counts: dict[str, int] = {}
    for article in FIXTURE["articles"]:
        counts[article["domain"]] = counts.get(article["domain"], 0) + 1
    assert set(counts) == DOMAINS
    for domain, n in counts.items():
        assert 4 <= n <= 6, f"{domain} has {n} articles"
    assert 12 <= len(FIXTURE["articles"]) <= 18


@pytest.mark.parametrize("article", FIXTURE["articles"], ids=lambda a: a["fixture_id"])
def test_every_expected_deeplink_id_exists_verbatim_in_the_real_catalog(article, catalog_by_id):
    for deeplink_id in article["expected_deeplink_ids"]:
        assert deeplink_id in catalog_by_id, f"{article['fixture_id']}: {deeplink_id} is not a real catalog entry"


@pytest.fixture(scope="module")
def service(catalog):
    return TroubleshootingService(catalog, PlanCache(catalog, model=HashEmbeddingModel()))


@pytest.fixture(scope="module")
def cold_results(service):
    """Every article's real cold-path result, keyed by fixture_id. One call each."""
    return {a["fixture_id"]: service.troubleshoot(a["canonical_query"], siis_response=a["content"]) for a in FIXTURE["articles"]}


@pytest.mark.parametrize("article", FIXTURE["articles"], ids=lambda a: a["fixture_id"])
def test_every_domain_reaches_the_real_pipeline_and_passes_the_validation_firewall(article, cold_results):
    result = cold_results[article["fixture_id"]]
    assert result["response"]["contexts"], f"{article['fixture_id']} was gated: {result['meta']}"
    assert 8 <= len(result["query_variations"]) <= 10


@pytest.mark.parametrize("article", FIXTURE["articles"], ids=lambda a: a["fixture_id"])
def test_no_deeplink_is_modified_from_its_catalog_value(article, cold_results, catalog_by_id):
    context = cold_results[article["fixture_id"]]["response"]["contexts"][0]
    for action in context["actions"]:
        for group in action["stepGroups"]:
            link = group["actionableDeeplink"]
            if link and link["deeplink"] != DUMMY:
                catalog_entry = next(e for e in catalog_by_id.values() if e["deeplink"] == link["deeplink"])
                assert link["description"] == catalog_entry["description"]
                assert link["message"] == (catalog_entry.get("message") or "")


@pytest.mark.parametrize("article", FIXTURE["articles"], ids=lambda a: a["fixture_id"])
def test_no_http_or_https_urls_appear_anywhere_in_the_output(article, cold_results):
    text = json.dumps(cold_results[article["fixture_id"]]["response"]).replace("bixby://", "")
    assert not URL.search(text)


@pytest.mark.parametrize("article", FIXTURE["articles"], ids=lambda a: a["fixture_id"])
def test_manual_actions_never_carry_an_actionable_deeplink(article, cold_results):
    context = cold_results[article["fixture_id"]]["response"]["contexts"][0]
    for action in context["actions"]:
        if action["category"] == "manual":
            for group in action["stepGroups"]:
                assert group["actionableDeeplink"] is None


@pytest.mark.parametrize("article", FIXTURE["articles"], ids=lambda a: a["fixture_id"])
def test_every_resolved_deeplink_matches_a_verified_expected_id_or_is_a_known_limitation(article, cold_results, catalog):
    if article["fixture_id"] in KNOWN_LIMITATIONS:
        pytest.skip("documented, deliberately-unfixed limitation; see key_matcher.find()")
    catalog_ids = {e["deeplink"]: e["id"] for e in catalog if e["id"] != "DL-DUMMY"}
    context = cold_results[article["fixture_id"]]["response"]["contexts"][0]
    resolved = set()
    for action in context["actions"]:
        for group in action["stepGroups"]:
            link = group["actionableDeeplink"]
            if link and link["deeplink"] != DUMMY:
                resolved.add(catalog_ids[link["deeplink"]])
    expected = set(article["expected_deeplink_ids"])
    if expected:
        assert resolved & expected, f"{article['fixture_id']}: expected one of {expected}, resolved {resolved}"
    else:
        assert not resolved, f"{article['fixture_id']}: expected no real deeplink, resolved {resolved}"


@pytest.mark.parametrize("article", FIXTURE["articles"], ids=lambda a: a["fixture_id"])
def test_the_same_query_produces_the_same_result_repeatedly(article, catalog):
    fresh_service = TroubleshootingService(catalog, PlanCache(catalog, model=HashEmbeddingModel()))
    first = fresh_service.troubleshoot(article["canonical_query"], siis_response=article["content"])
    second = fresh_service.troubleshoot(article["canonical_query"], siis_response=article["content"])
    assert first["response"] == second["response"]
    assert first["query_variations"] == second["query_variations"]


def test_an_article_with_no_relevant_content_is_rejected_not_fabricated(service):
    result = service.troubleshoot(
        "recommend a good sci-fi novel",
        siis_response="Unrelated,Category Recipe for pasta ( Unrelated,Category): # Cooking Pasta\nBoil water. Add pasta.\n",
    )
    assert result["response"] == {"contexts": []}
    assert result["meta"]["fallback"] == "no_match"


@pytest.mark.acceptance
def test_cross_domain_recall_at_1_meets_a_floor_with_the_real_embedding_model():
    """Guards against a future regression; see docs/cross_domain_generalization.md for the
    full breakdown (98.75% combined, one observed miss documented as a hard negative)."""
    from app.config import EMBEDDING_MODEL
    from app.retrieval.st_embedder import load_embedder

    catalog = load_catalog()
    real_service = TroubleshootingService(catalog, PlanCache(catalog, model=load_embedder(EMBEDDING_MODEL)))
    for article in FIXTURE["articles"]:
        build_result = real_service.troubleshoot(article["canonical_query"], siis_response=article["content"])
        assert build_result["response"]["contexts"], article["fixture_id"]

    correct = total = 0
    for article in FIXTURE["articles"]:
        expected_title = next(
            e.response["contexts"][0]["title"] for e in real_service.cache.entries() if e.query == article["canonical_query"]
        )
        for paraphrase in article["paraphrases"]:
            total += 1
            top = real_service.cache.top_matches(paraphrase, k=1)
            correct += bool(top) and top[0].entry.response["contexts"][0]["title"] == expected_title
    assert correct / total >= 0.90, f"{correct}/{total} = {correct / total:.0%}"
