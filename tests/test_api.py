"""HTTP contract tests (PDF section 5)."""

import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.retrieval.embeddings import HashEmbeddingModel
from app.models.official_schema import ContextDeeplinkResponse


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path = tmp_path_factory.mktemp("cache") / "plan_cache.json"
    original = main.build_default_service
    main.build_default_service = lambda: original(cache_path=path, embedder=HashEmbeddingModel())
    with TestClient(main.app) as test_client:
        yield test_client
    main.build_default_service = original


def test_health_is_ok_when_initialised(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_health_is_503_before_initialisation(client):
    service = main.app.state.service
    main.app.state.service = None
    try:
        response = TestClient(main.app).get("/health")
    finally:
        main.app.state.service = service
    assert response.status_code == 503 and response.json() == {"status": "initializing"}


def test_troubleshoot_returns_a_plan_as_pure_json(client, siis_rows):
    query = next(r for r in siis_rows if r["id"] == "row_21")["original_query"]
    response = client.post("/v1/troubleshoot", json={"query": query})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.text.lstrip().startswith("{") and "```" not in response.text
    body = response.json()
    assert set(body) == {"query", "query_variations", "response", "meta"}
    ContextDeeplinkResponse.model_validate(body["response"])
    assert body["meta"]["cache_hit"] is True


def test_unrelated_query_returns_empty_contexts_and_fallback(client):
    body = client.post("/v1/troubleshoot", json={"query": "what is the best pasta recipe"}).json()
    assert body["response"] == {"contexts": []}
    assert body["meta"]["fallback"] == "no_match"


def test_supplied_siis_response_is_used(client):
    siis = "## Adjust brightness\nGo to Settings.\nTap Display.\nTap Brightness.\n"
    body = client.post("/v1/troubleshoot", json={"query": "adjust screen brightness", "siis_response": siis}).json()
    assert body["response"]["contexts"] and body["meta"]["cache_hit"] is False


def test_empty_query_is_rejected(client):
    assert client.post("/v1/troubleshoot", json={"query": ""}).status_code == 422
    assert client.post("/v1/troubleshoot", json={}).status_code == 422


def test_response_has_no_urls_outside_deeplinks(client, siis_rows):
    query = next(r for r in siis_rows if r["id"] == "row_14")["original_query"]
    text = json.dumps(client.post("/v1/troubleshoot", json={"query": query}).json()["response"])
    assert "http" not in text and "www." not in text
