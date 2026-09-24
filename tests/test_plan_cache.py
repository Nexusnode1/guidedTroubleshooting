"""Only validated plans enter the cache; lookups are semantic and persistent."""

import copy
import json

import pytest

from app.services.plan_builder import PlanBuilder
from app.services.plan_cache import PlanCache

HASH_THRESHOLD = 0.3  # the hashed fallback embedder scores lower than a real model


@pytest.fixture(scope="module")
def built(catalog, siis_rows):
    row = next(r for r in siis_rows if r["id"] == "row_2")
    siis = row["siis_response"]
    build = PlanBuilder(catalog).build(row["original_query"], siis["content"], siis["title"])
    assert build is not None and build.errors == ()
    return row["original_query"], build


def test_exact_query_hits_and_paraphrase_hits_semantically(catalog, built):
    query, build = built
    cache = PlanCache(catalog, threshold=HASH_THRESHOLD)
    cache.add("row_2", query, build.query_variations, build.response)
    exact = cache.lookup(query)
    assert exact.exact is True and exact.entry.entry_id == "row_2"
    # The hashed fallback only recognises near-rephrases; real paraphrases are covered by tests/test_acceptance.py.
    paraphrase = cache.lookup("screen turns completely blank or white when I search")
    assert paraphrase is not None and paraphrase.exact is False


def test_unrelated_query_misses(catalog, built):
    query, build = built
    cache = PlanCache(catalog, threshold=HASH_THRESHOLD)
    cache.add("row_2", query, build.query_variations, build.response)
    assert cache.lookup("what is the best pasta recipe") is None


def test_invalid_plan_is_rejected_and_not_stored(catalog, built):
    query, build = built
    bad = copy.deepcopy(build.response)
    bad["contexts"][0]["goal"] = "Fix it"
    cache = PlanCache(catalog)
    with pytest.raises(ValueError):
        cache.add("row_2", query, build.query_variations, bad)
    assert len(cache) == 0


def test_save_and_load_round_trip(catalog, built, tmp_path):
    query, build = built
    cache = PlanCache(catalog)
    cache.add("row_2", query, build.query_variations, build.response)
    path = tmp_path / "cache.json"
    cache.save(path)
    loaded = PlanCache.load(path, catalog)
    assert len(loaded) == 1
    assert loaded.lookup(query).entry.response == build.response


def test_top_matches_orders_distinct_entries_by_similarity(catalog, siis_rows):
    by_id = {r["id"]: r for r in siis_rows}
    cache = PlanCache(catalog, threshold=0.0)
    for row_id in ("row_2", "row_14"):
        row = by_id[row_id]
        siis = row["siis_response"]
        build = PlanBuilder(catalog).build(row["original_query"], siis["content"], siis["title"])
        assert build is not None and build.errors == (), row_id
        cache.add(row_id, row["original_query"], build.query_variations, build.response)

    top = cache.top_matches(by_id["row_14"]["original_query"], k=2)
    assert len(top) == 2
    assert top[0].entry.entry_id == "row_14"
    assert len({hit.entry.entry_id for hit in top}) == 2  # distinct entries, not distinct keys


def test_top_matches_respects_k_and_handles_an_empty_cache(catalog):
    cache = PlanCache(catalog)
    assert cache.top_matches("anything", k=3) == []


def test_top_matches_deduplicates_multiple_keys_of_the_same_entry(catalog, siis_rows):
    row = next(r for r in siis_rows if r["id"] == "row_14")
    siis = row["siis_response"]
    build = PlanBuilder(catalog).build(row["original_query"], siis["content"], siis["title"])
    assert build is not None and build.errors == ()
    cache = PlanCache(catalog, threshold=0.0)
    cache.add("row_14", row["original_query"], build.query_variations, build.response)
    top = cache.top_matches(row["original_query"], k=5)
    assert len(top) == 1
    assert top[0].entry.entry_id == "row_14"


def test_add_lookup_keys_extends_an_existing_entry_without_reschema_ing_it(catalog, built):
    # Extra keys (e.g. hand-written evaluation paraphrases) are not the official
    # query_variations field and do not need to satisfy its 8-10-item rule.
    query, build = built
    cache = PlanCache(catalog, threshold=0.0)
    cache.add("row_2", query, build.query_variations, build.response)
    cache.add_lookup_keys("row_2", ["my screen went totally white"])
    hit = cache.lookup("my screen went totally white")
    assert hit is not None and hit.entry.entry_id == "row_2"


def test_add_lookup_keys_requires_an_existing_entry(catalog):
    cache = PlanCache(catalog)
    with pytest.raises(KeyError):
        cache.add_lookup_keys("does-not-exist", ["some text"])


def test_load_revalidates_every_entry(catalog, built, tmp_path):
    query, build = built
    cache = PlanCache(catalog)
    cache.add("row_2", query, build.query_variations, build.response)
    path = tmp_path / "cache.json"
    cache.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][0]["response"]["contexts"][0]["goal"] = "Fix it"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        PlanCache.load(path, catalog)
