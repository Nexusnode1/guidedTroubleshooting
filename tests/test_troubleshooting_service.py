"""Online path: cache hits, fallbacks, cold builds, determinism."""

import json
from pathlib import Path

import pytest

from app.retrieval.embeddings import HashEmbeddingModel
from app.services.plan_cache import PlanCache
from app.services.troubleshooting_service import (
    MODEL_ID,
    TroubleshootingService,
    build_default_service,
    source_fingerprint,
)

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "paraphrases.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def service(catalog, siis_rows):
    instance = TroubleshootingService(catalog)
    instance.warm(siis_rows)
    return instance


def test_warm_caches_most_rows_and_reports_the_rest(catalog, siis_rows):
    results = TroubleshootingService(catalog).warm(siis_rows)
    statuses = [result.status for result in results]
    assert statuses.count("cached") >= 12
    assert "invalid" not in statuses


def test_exact_original_query_is_a_cache_hit(service, siis_rows):
    row = next(r for r in siis_rows if r["id"] == "row_2")
    body = service.troubleshoot(row["original_query"])
    assert body["meta"]["cache_hit"] is True
    assert body["meta"]["model"] == MODEL_ID and body["meta"]["cost_usd"] == 0.0
    assert "fallback" not in body["meta"]
    assert len(body["response"]["contexts"]) == 1
    assert 8 <= len(body["query_variations"]) <= 10


def test_every_cached_plan_answers_its_own_query(service, siis_rows):
    cached_ids = {entry.entry_id for entry in service.cache.entries()}
    for row in siis_rows:
        if row["id"] in cached_ids:
            assert service.troubleshoot(row["original_query"])["response"]["contexts"], row["id"]


@pytest.mark.parametrize("query", FIXTURES["negatives"])
def test_unrelated_queries_fall_back_to_no_match(service, query):
    body = service.troubleshoot(query)
    assert body["response"] == {"contexts": []}
    assert body["meta"]["fallback"] == "no_match"
    assert body["meta"]["cache_hit"] is False


def test_empty_cache_reports_no_siis_context(catalog):
    body = TroubleshootingService(catalog).troubleshoot("screen is blank")
    assert body["response"] == {"contexts": []}
    assert body["meta"]["fallback"] == "no_siis_context"


def test_cold_path_builds_from_supplied_siis_text_then_caches_it(catalog):
    service = TroubleshootingService(catalog)
    siis = "## Adjust brightness\nGo to Settings.\nTap Display.\nTap Brightness.\n"
    cold = service.troubleshoot("adjust screen brightness", siis_response=siis)
    assert cold["response"]["contexts"] and cold["meta"]["cache_hit"] is False
    warm = service.troubleshoot("adjust screen brightness")
    assert warm["meta"]["cache_hit"] is True
    assert warm["response"] == cold["response"]


def test_supplied_siis_text_with_nothing_relevant_is_no_match(catalog):
    body = TroubleshootingService(catalog).troubleshoot("best pasta recipe", siis_response="## Charge\nConnect the charger.")
    assert body["response"] == {"contexts": []}
    assert body["meta"]["fallback"] == "no_match"


def test_identical_queries_give_identical_plans(service):
    query = "my phone screen is black and will not turn on"
    first, second = service.troubleshoot(query), service.troubleshoot(query)
    assert first["response"] == second["response"]
    assert first["query_variations"] == second["query_variations"]


def test_default_service_warms_then_reloads_from_disk(tmp_path):
    path = tmp_path / "plan_cache.json"
    first = build_default_service(cache_path=path, embedder=HashEmbeddingModel())
    assert path.exists() and len(first.cache) >= 12
    second = build_default_service(cache_path=path, embedder=HashEmbeddingModel())
    assert len(second.cache) == len(first.cache)
    assert isinstance(second.cache, PlanCache)


def _saved_cache(tmp_path):
    path = tmp_path / "plan_cache.json"
    build_default_service(cache_path=path, embedder=HashEmbeddingModel())
    return path, json.loads(path.read_text(encoding="utf-8"))


def _no_warm(monkeypatch):
    def fail(self, rows):
        raise AssertionError("a usable cache must be loaded, not rebuilt")

    monkeypatch.setattr(TroubleshootingService, "warm", fail)


def test_saved_cache_records_the_source_it_was_built_from(tmp_path, catalog, siis_rows):
    path, payload = _saved_cache(tmp_path)
    assert payload["source"] == source_fingerprint(catalog, siis_rows)
    assert PlanCache.stored_source(path) == payload["source"]


def test_matching_cache_is_loaded_without_rebuilding(tmp_path, monkeypatch):
    path, payload = _saved_cache(tmp_path)
    _no_warm(monkeypatch)
    service = build_default_service(cache_path=path, embedder=HashEmbeddingModel())
    assert len(service.cache) == len(payload["entries"])


def test_valid_cache_saved_without_a_fingerprint_is_still_loaded(tmp_path, monkeypatch):
    path, payload = _saved_cache(tmp_path)
    del payload["source"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    _no_warm(monkeypatch)
    assert len(build_default_service(cache_path=path, embedder=HashEmbeddingModel()).cache) == len(payload["entries"])


def test_cache_from_an_older_catalog_is_rebuilt_instead_of_blocking_startup(tmp_path, catalog):
    path, payload = _saved_cache(tmp_path)
    # A cache written against an earlier catalog: same shape, URIs the current catalog lacks.
    stale = json.loads(json.dumps(payload).replace("voiceassist://", "legacy://"))
    del stale["source"]
    path.write_text(json.dumps(stale), encoding="utf-8")
    service = build_default_service(cache_path=path, embedder=HashEmbeddingModel())
    assert len(service.cache) == len(payload["entries"])
    assert "legacy://" not in path.read_text(encoding="utf-8")
    uris = {entry["deeplink"] for entry in catalog}
    for entry in service.cache.entries():
        for action in entry.response["contexts"][0]["actions"]:
            for group in action["stepGroups"]:
                link = group["actionableDeeplink"]
                assert link is None or link["deeplink"] in uris


def test_cache_built_from_other_source_data_is_rebuilt(tmp_path):
    path, payload = _saved_cache(tmp_path)
    payload["source"] = "0" * 64
    payload["entries"] = payload["entries"][:1]
    path.write_text(json.dumps(payload), encoding="utf-8")
    service = build_default_service(cache_path=path, embedder=HashEmbeddingModel())
    assert len(service.cache) > 1
    assert PlanCache.stored_source(path) != "0" * 64


@pytest.mark.parametrize("content", ["{not json", "[]", '{"entries": [{"id": "x"}]}'])
def test_unreadable_cache_file_is_rebuilt(tmp_path, content):
    path = tmp_path / "plan_cache.json"
    path.write_text(content, encoding="utf-8")
    service = build_default_service(cache_path=path, embedder=HashEmbeddingModel())
    assert len(service.cache) >= 12
    assert PlanCache.stored_source(path) is not None


def test_api_starts_and_is_healthy_with_a_stale_cache_on_disk(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main

    path, payload = _saved_cache(tmp_path)
    path.write_text(json.dumps(payload).replace("voiceassist://", "legacy://"), encoding="utf-8")
    original = main.build_default_service
    monkeypatch.setattr(main, "build_default_service", lambda: original(cache_path=path, embedder=HashEmbeddingModel()))
    with TestClient(main.app) as client:
        assert client.get("/health").json() == {"status": "ok"}
