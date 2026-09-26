"""End-to-end checks of the official input queries and SIIS rows through the HTTP API.

Every official query (data/original/input.txt) goes through the fast path, and every
official SIIS row goes through the cold path with its raw ``siis_response`` text. The
checks are properties the API must hold for any input, not per-query expected answers.
"""

import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import ORIGINAL_DIR
from app.models.official_schema import ContextDeeplinkResponse
from app.retrieval.embeddings import HashEmbeddingModel
from app.services.catalog import placeholder_uris
from app.services.siis_parser import embedded_title

_ORDER = {"auto": 0, "manual": 1, "critical": 2}
OFFICIAL_QUERIES = [
    line.strip() for line in (ORIGINAL_DIR / "input.txt").read_text(encoding="utf-8").splitlines() if line.strip()
]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path = tmp_path_factory.mktemp("cache") / "plan_cache.json"
    original = main.build_default_service
    main.build_default_service = lambda: original(cache_path=path, embedder=HashEmbeddingModel())
    with TestClient(main.app) as test_client:
        yield test_client
    main.build_default_service = original


@pytest.fixture(scope="module")
def cold_bodies(client, siis_rows):
    bodies = {}
    for row in siis_rows:
        payload = {"query": row["original_query"], "siis_response": row["siis_response"]["content"]}
        response = client.post("/v1/troubleshoot", json=payload)
        assert response.status_code == 200, row["id"]
        bodies[row["id"]] = response.json()
    return bodies


def _check_body(body, catalog):
    """Assert the invariants every API body must satisfy, whatever the query."""
    ContextDeeplinkResponse.model_validate(body["response"])
    assert 8 <= len(body["query_variations"]) <= 10
    actionable = {entry["deeplink"]: entry for entry in catalog}
    validation = {entry["validation"]["deeplink"] for entry in catalog if entry.get("validation")}
    placeholders = placeholder_uris(catalog)
    for context in body["response"]["contexts"]:
        assert 0.0 <= context["score"] <= 1.0
        categories = [action["category"] for action in context["actions"]]
        assert [_ORDER[c] for c in categories] == sorted(_ORDER[c] for c in categories)
        for action in context["actions"]:
            for group in action["stepGroups"]:
                link = group["actionableDeeplink"]
                if action["category"] in ("manual", "critical"):
                    assert link is None, action["actionName"]
                if link is not None:
                    entry = actionable[link["deeplink"]]  # exact catalog URI, never rewritten
                    if link["deeplink"] not in placeholders:
                        assert link["description"] == entry["description"]
                        assert link["originalType"] == entry["originalType"]
                if group["validationDeeplink"] is not None:
                    assert group["validationDeeplink"]["deeplink"] in validation


def test_the_official_input_file_has_twenty_queries():
    assert len(OFFICIAL_QUERIES) == 20


@pytest.mark.parametrize("query", OFFICIAL_QUERIES)
def test_every_official_query_is_answered_without_error(client, catalog, query):
    response = client.post("/v1/troubleshoot", json={"query": query})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == query
    _check_body(body, catalog)


def test_every_official_siis_row_is_accepted_by_the_cold_path(cold_bodies, catalog):
    for body in cold_bodies.values():
        assert body["meta"]["cache_hit"] is False
        _check_body(body, catalog)


def test_cold_path_recovers_each_article_title_and_builds_its_plan(cold_bodies, siis_rows):
    answered = 0
    for row in siis_rows:
        assert embedded_title(row["siis_response"]["content"]) == row["siis_response"]["title"], row["id"]
        answered += bool(cold_bodies[row["id"]]["response"]["contexts"])
    # Refusing a misaligned article is allowed; silently answering nothing is not the norm.
    assert answered >= 15


def test_cold_path_returns_catalog_uris_unchanged(cold_bodies, catalog):
    catalog_uris = {entry["deeplink"] for entry in catalog}
    returned = {
        group["actionableDeeplink"]["deeplink"]
        for body in cold_bodies.values()
        for context in body["response"]["contexts"]
        for action in context["actions"]
        for group in action["stepGroups"]
        if group["actionableDeeplink"] is not None
    }
    assert returned and returned <= catalog_uris
    assert "bixby://" not in json.dumps(list(cold_bodies.values()))
