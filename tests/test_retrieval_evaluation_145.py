"""145-query semantic retrieval evaluation (see scripts/evaluate_retrieval_145.py).

Imports the evaluation logic from the script the same way tests/test_benchmark_paraphrase_dataset.py
imports scripts/benchmark_paraphrase_dataset.py -- one implementation, not a parallel one.

Two kinds of assertion:

- Safety invariants that must hold regardless of how good or bad retrieval is: every non-empty
  response is schema-valid, every deeplink is an exact catalog URI, manual/critical actions
  never carry one, and repeated calls are deterministic. These can never be "fixed" by tuning
  retrieval, because they don't depend on which plan (if any) was chosen.
- A frozen baseline of the observed correctness numbers (CURRENT behavior, not a target), in
  the same spirit as tests/test_camera_hard_negative.py: a future change to retrieval must be
  a deliberate, evaluated decision that updates these numbers, not a silent regression nobody
  notices. See docs/retrieval_evaluation_145.md for the full per-group breakdown and the
  analysis of what these numbers do and don't mean (several "wrong" results trace to already-
  documented misaligned official rows or to this fixture's own paraphrase choices, not to a
  retrieval defect -- see that doc's "Root cause analysis" section).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.acceptance


@pytest.fixture(scope="module")
def evaluator():
    spec = importlib.util.spec_from_file_location("evaluate_retrieval_145", ROOT / "scripts" / "evaluate_retrieval_145.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fixture(evaluator):
    return evaluator.load_fixture()


@pytest.fixture(scope="module")
def service(evaluator, catalog, siis_rows):
    from app.config import EMBEDDING_MODEL
    from app.retrieval.st_embedder import load_embedder

    instance = evaluator.TroubleshootingService(catalog, evaluator.PlanCache(catalog, model=load_embedder(EMBEDDING_MODEL)))
    instance.warm(siis_rows)
    return instance


@pytest.fixture(scope="module")
def report(evaluator, service, fixture):
    return evaluator.evaluate_all(service, fixture)


def test_the_fixture_has_exactly_145_unique_queries(fixture):
    texts = [q["text"] for group in fixture["groups"].values() for q in group["queries"]]
    assert len(texts) == 145
    assert len(set(texts)) == 145


def test_every_expected_title_is_an_actual_cached_plan(service, fixture):
    """Guards the fixture itself: a typo'd expected_title would silently score every query in
    that group as a miss instead of failing loudly here."""
    cached_titles = {entry.response["contexts"][0]["title"] for entry in service.cache.entries()}
    for group in fixture["groups"].values():
        if group["status"] == "supported":
            assert group["expected_title"] in cached_titles, group["expected_title"]


def test_two_official_rows_behind_the_unsupported_groups_are_confirmed_gated(service):
    """row_16 (charger-triggered flashing) and row_20 (visual distortion) are why some
    'charger-triggered'/'distorted display' queries are marked ambiguous rather than
    supported -- this pins that down so the fixture's own reasoning can't go stale."""
    cached_ids = {entry.entry_id for entry in service.cache.entries()}
    assert "row_16" not in cached_ids
    assert "row_20" not in cached_ids


def test_every_matched_response_is_schema_valid_with_zero_url_leaks(report):
    offenders = [(r["group"], r["query"], r["schema_errors"]) for r in report["records"] if r["schema_errors"]]
    assert offenders == []


def test_every_returned_deeplink_is_an_exact_catalog_uri_and_never_on_a_manual_or_critical_action(report):
    offenders = [(r["group"], r["query"], r["deeplink_errors"]) for r in report["records"] if r["deeplink_errors"]]
    assert offenders == []


def test_no_query_raises_an_exception(report):
    assert report["total"] == 145
    assert len(report["records"]) == 145


def test_repeated_calls_are_deterministic(service):
    sample = [
        "My phone screen is completely black and won't turn on.",
        "My touchscreen isn't responding to my taps at all.",
        "What is the capital of France?",
    ]
    for query in sample:
        first = service.troubleshoot(query)
        second = service.troubleshoot(query)
        first["meta"].pop("latency_ms")
        second["meta"].pop("latency_ms")
        assert first == second


# --- frozen baseline: CURRENT observed behavior, not an aspiration (see module docstring) ----


def test_the_frozen_baseline_counts(report):
    assert report["total"] == 145
    assert report["supported"] == 122
    assert report["ambiguous"] == 13
    assert report["no_match_expected"] == 10
    assert report["correct"] == 99
    assert report["wrong"] == 16
    assert report["miss"] == 7
    assert report["false_positives"] == 11
    assert report["safe_fallbacks"] == 12


def test_the_frozen_baseline_ranking_metrics(report):
    assert report["recall_at_1"] == pytest.approx(0.8443, abs=1e-4)
    assert report["recall_at_3"] == pytest.approx(0.9754, abs=1e-4)
    assert report["mrr"] == pytest.approx(0.9057, abs=1e-4)


def test_no_match_expected_false_positives_stay_at_the_documented_bluetooth_collision_only(report):
    """The one false positive among genuinely out-of-domain queries (Bluetooth pairing, see
    docs/retrieval_hard_negative_fix_audit in this session's history) is already a known,
    investigated limitation (docs/cross_domain_hard_negatives.md), not a new regression."""
    offenders = [r for r in report["records"] if r["group"] == "no_match_expected" and r["outcome"] == "false_positive"]
    assert len(offenders) == 1
    assert offenders[0]["got_title"] == "Screen mirroring tv"
