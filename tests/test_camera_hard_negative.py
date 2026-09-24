"""Regression tests for the observed 'camera won't open' vs. 'camera crashes' hard negative.

See docs/camera_hard_negative_analysis.md for the full analysis and
tests/fixtures/camera_hard_negative.json (SYNTHETIC HARD-NEGATIVE FIXTURE) for the fixture
itself, built from the already-verified tests/fixtures/cross_domain_articles.json. This locks
in the frozen baseline (Recall@1=0.90, Recall@3=1.00, MRR=0.95, N=10) so a future change
(fine-tuning, a reranker, or a targeted fix) can be measured against a known starting point,
and so the specific known failure cannot silently get worse without being noticed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CROSS_DOMAIN = json.loads((FIXTURE_DIR / "cross_domain_articles.json").read_text(encoding="utf-8"))
HARD_NEGATIVE = json.loads((FIXTURE_DIR / "camera_hard_negative.json").read_text(encoding="utf-8"))
ARTICLES_BY_ID = {a["fixture_id"]: a for a in CROSS_DOMAIN["articles"]}
K_VALUES = (1, 3)


def test_fixture_paraphrases_are_verbatim_copies_of_the_verified_source_fixture():
    for side in ("positive", "hard_negative"):
        article = ARTICLES_BY_ID[HARD_NEGATIVE[side]["fixture_id"]]
        assert HARD_NEGATIVE[side]["canonical_query"] == article["canonical_query"]
        assert set(HARD_NEGATIVE[side]["paraphrases"]) <= set(article["paraphrases"]) | {article["canonical_query"]}


@pytest.fixture(scope="module")
def service():
    from app.config import EMBEDDING_MODEL
    from app.retrieval.st_embedder import load_embedder
    from app.services.catalog import load_catalog
    from app.services.plan_cache import PlanCache
    from app.services.troubleshooting_service import TroubleshootingService

    catalog = load_catalog()
    svc = TroubleshootingService(catalog, PlanCache(catalog, model=load_embedder(EMBEDDING_MODEL)))
    for side in ("positive", "hard_negative"):
        article = ARTICLES_BY_ID[HARD_NEGATIVE[side]["fixture_id"]]
        svc.troubleshoot(article["canonical_query"], siis_response=article["content"])
    return svc


@pytest.fixture(scope="module")
def expected_titles(service):
    titles = {}
    for side in ("positive", "hard_negative"):
        canonical = HARD_NEGATIVE[side]["canonical_query"]
        titles[side] = next(e.response["contexts"][0]["title"] for e in service.cache.entries() if e.query == canonical)
    return titles


def _rank(service, text: str, expected_title: str) -> int | None:
    top = service.cache.top_matches(text, k=5)
    titles = [hit.entry.response["contexts"][0]["title"] for hit in top]
    return titles.index(expected_title) + 1 if expected_title in titles else None


@pytest.mark.acceptance
@pytest.mark.parametrize(
    "text",
    [p for p in HARD_NEGATIVE["positive"]["paraphrases"] if p != HARD_NEGATIVE["confusable_query"]["text"]],
)
def test_camera_wont_open_paraphrases_other_than_the_known_confusable_one_rank_first(service, expected_titles, text):
    assert _rank(service, text, expected_titles["positive"]) == 1


@pytest.mark.acceptance
@pytest.mark.parametrize("text", HARD_NEGATIVE["hard_negative"]["paraphrases"])
def test_camera_crashes_paraphrases_all_rank_first(service, expected_titles, text):
    assert _rank(service, text, expected_titles["hard_negative"]) == 1


@pytest.mark.acceptance
def test_the_known_confusable_query_still_reproduces_the_documented_frozen_baseline_miss(service, expected_titles):
    """This is a known, documented failure (docs/camera_hard_negative_analysis.md), not an
    aspiration: it asserts the CURRENT, observed behavior so that a change to it -- in either
    direction -- is visible and must be a deliberate, evaluated decision, not a silent drift."""
    text = HARD_NEGATIVE["confusable_query"]["text"]
    positive_rank = _rank(service, text, expected_titles["positive"])
    negative_rank = _rank(service, text, expected_titles["hard_negative"])
    assert positive_rank == HARD_NEGATIVE["confusable_query"]["observed_dense_scores"]["positive_rank"]
    assert negative_rank == HARD_NEGATIVE["confusable_query"]["observed_dense_scores"]["hard_negative_rank"]


@pytest.mark.acceptance
def test_the_frozen_baseline_metrics_are_recall_at_1_090_recall_at_3_100_mrr_095(service, expected_titles):
    hits = {k: 0 for k in K_VALUES}
    reciprocal_ranks = []
    total = 0
    for side in ("positive", "hard_negative"):
        for text in HARD_NEGATIVE[side]["paraphrases"]:
            total += 1
            rank = _rank(service, text, expected_titles[side])
            for k in K_VALUES:
                if rank is not None and rank <= k:
                    hits[k] += 1
            reciprocal_ranks.append(1.0 / rank if rank is not None else 0.0)
    assert total == 10
    assert hits[1] / total == pytest.approx(0.90)
    assert hits[3] / total == pytest.approx(1.00)
    assert sum(reciprocal_ranks) / total == pytest.approx(0.95)
