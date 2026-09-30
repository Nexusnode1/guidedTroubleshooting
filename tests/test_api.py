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


@pytest.mark.parametrize("query", ["   ", "\t\n", "???", "...!", "please", "https://example.com/help", "www.example.com"])
def test_query_with_no_searchable_text_is_rejected_at_the_boundary(client, query, monkeypatch):
    called = []
    monkeypatch.setattr(main.app.state.service, "troubleshoot", lambda *args, **kwargs: called.append(args))
    response = client.post("/v1/troubleshoot", json={"query": query})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "query"]
    assert called == []


def test_a_normal_query_is_still_answered(client):
    response = client.post("/v1/troubleshoot", json={"query": "my phone screen is cracked"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"query", "query_variations", "response", "meta"}
    assert isinstance(body["meta"]["latency_ms"], int)


@pytest.mark.parametrize(
    "query",
    [
        "my screen is black see http://example.com/pic for a photo",
        "screen is cracked, details at https://example.com/a?b=1 and www.example.com/x",
        "my screen flickers like in [this video](https://example.com/v)",
    ],
)
def test_urls_in_the_query_are_echoed_only_in_the_query_field(client, query):
    response = client.post("/v1/troubleshoot", json={"query": query})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == query
    variations = body["query_variations"]
    assert 8 <= len(variations) <= 10 and len(set(variations)) == len(variations)
    for text in [*variations, json.dumps(body["response"])]:
        assert "://" not in text and "www." not in text and "](" not in text


def test_a_cold_build_with_a_url_in_the_query_returns_url_free_steps_and_variations(client):
    siis = "## Adjust brightness\nGo to Settings.\nTap Display.\nSee https://example.com/help first.\nTap Brightness.\n"
    query = "adjust screen brightness as shown on https://example.com/guide"
    body = client.post("/v1/troubleshoot", json={"query": query, "siis_response": siis}).json()
    assert body["query"] == query and body["response"]["contexts"]
    ContextDeeplinkResponse.model_validate(body["response"])
    steps = [step for action in body["response"]["contexts"][0]["actions"] for group in action["stepGroups"] for step in group["steps"]]
    for text in [*steps, *body["query_variations"]]:
        assert "http" not in text and "www." not in text


def test_response_has_no_urls_outside_deeplinks(client, siis_rows):
    query = next(r for r in siis_rows if r["id"] == "row_14")["original_query"]
    text = json.dumps(client.post("/v1/troubleshoot", json={"query": query}).json()["response"])
    assert "http" not in text and "www." not in text
