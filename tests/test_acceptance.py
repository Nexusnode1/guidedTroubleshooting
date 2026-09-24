"""Acceptance criteria, checked with the real embedding model (no fixtures tuned to pass).

- Semantic cache hit rate on unseen paraphrases >= 80%, with no unrelated query answered.
- P95 latency <= 300 ms on cache hits and <= 8 s on cold builds.
- Every cached plan is rule-valid and contains no URLs.
- A model saved to a local directory (what your own training will produce) loads and behaves the same.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import time

import numpy as np
import pytest

from app.config import EMBEDDING_MODEL
from app.retrieval.st_embedder import SentenceTransformerEmbedding, load_embedder
from app.services.plan_cache import PlanCache
from app.services.plan_validator import validate_plan
from app.services.troubleshooting_service import TroubleshootingService

pytestmark = pytest.mark.acceptance

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_SETS = ["paraphrases.json", "paraphrases_holdout.json"]
HIT_RATE_TARGET = 0.80
HIT_P95_MS = 300.0
COLD_P95_MS = 8000.0
REQUESTS = 30
URL = re.compile(r"https?://|www\.", re.IGNORECASE)


@pytest.fixture(scope="module")
def service(catalog, siis_rows):
    instance = TroubleshootingService(catalog, PlanCache(catalog, model=load_embedder(EMBEDDING_MODEL)))
    instance.warm(siis_rows)
    return instance


def _fixtures(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _p95(values: list[float]) -> float:
    return float(np.percentile(values, 95))


@pytest.mark.parametrize("name", FIXTURE_SETS)
def test_paraphrase_hit_rate_meets_target_and_no_unrelated_query_is_answered(service, name):
    fixtures = _fixtures(name)
    correct = 0
    for item in fixtures["positives"]:
        contexts = service.troubleshoot(item["query"])["response"]["contexts"]
        correct += bool(contexts) and contexts[0]["title"] == item["expect"]
    rate = correct / len(fixtures["positives"])
    assert rate >= HIT_RATE_TARGET, f"{name}: {correct}/{len(fixtures['positives'])} = {rate:.0%}"
    answered = [q for q in fixtures["negatives"] if service.troubleshoot(q)["response"]["contexts"]]
    assert answered == []


def test_cache_hit_latency_p95_is_within_300_ms(service):
    exact = service.cache.entries()[0].query
    paraphrases = [p["query"] for name in FIXTURE_SETS for p in _fixtures(name)["positives"]]
    for label, queries in (("exact", [exact] * REQUESTS), ("paraphrase", (paraphrases * REQUESTS)[:REQUESTS])):
        timings = []
        for query in queries:
            started = time.perf_counter()
            service.troubleshoot(query)
            timings.append((time.perf_counter() - started) * 1000)
        assert _p95(timings) <= HIT_P95_MS, f"{label} P95 {_p95(timings):.1f} ms"


def test_cold_build_latency_p95_is_within_8_seconds(service, siis_rows):
    row = next(r for r in siis_rows if r["id"] == "row_2")
    content = row["siis_response"]["content"]
    timings = []
    for index in range(REQUESTS):
        started = time.perf_counter()
        body = service.troubleshoot(f"{row['original_query']} variant {index}", siis_response=content)
        timings.append((time.perf_counter() - started) * 1000)
        assert body["response"]["contexts"]
    assert _p95(timings) <= COLD_P95_MS


def test_every_cached_plan_is_valid_and_url_free(service, catalog):
    for entry in service.cache.entries():
        assert validate_plan({**entry.response, "query_variations": list(entry.variations)}, catalog).valid
        assert not URL.search(json.dumps({k: v for k, v in entry.response.items()}).replace("bixby://", ""))


def test_a_model_saved_to_a_local_directory_loads_and_matches(tmp_path):
    """The path your own trained model will take: save, point EMBEDDING_MODEL at the folder, load."""
    from sentence_transformers import SentenceTransformer

    source = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    SentenceTransformer(source).save(str(tmp_path / "my-embedder"))
    local = load_embedder(str(tmp_path / "my-embedder"))
    original = SentenceTransformerEmbedding(source)
    text = "my screen keeps flickering"
    assert isinstance(local, SentenceTransformerEmbedding)
    assert np.allclose(local.embed(text), original.embed(text), atol=1e-5)
    assert abs(float(np.linalg.norm(local.embed(text))) - 1.0) < 1e-4
