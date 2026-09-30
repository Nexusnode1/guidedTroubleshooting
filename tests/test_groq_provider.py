"""Groq provider against mocked HTTP responses: no network, no real API key."""

import json
import logging
from pathlib import Path

import httpx
import pytest

from app.providers.base import GenerationRequest, ProviderError, ProviderErrorKind
from app.providers.config import ProviderConfigError
from app.providers.groq import DEFAULT_MODEL, DEFAULT_TIMEOUT_SECONDS, GroqProvider

ROOT = Path(__file__).resolve().parents[1]
FAKE_KEY = "fake-groq-key-for-tests-0002"
REQUEST = GenerationRequest(
    prompt="Summarize the complaint.",
    system_instruction="Return JSON only.",
    response_schema={"type": "object", "properties": {"intent": {"type": "string"}}},
    max_output_tokens=256,
)


def _ok_body(content, finish: str = "stop") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": DEFAULT_MODEL,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
    }


def _provider(handler, key: str | None = FAKE_KEY, **kwargs) -> GroqProvider:
    return GroqProvider(api_key=key, client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError("no HTTP request may be sent")


def _status(code: int, error: dict | None = None):
    def handler(request):
        return httpx.Response(code, json={"error": error or {"message": f"status {code}", "type": "api_error"}})

    return handler


def _raise(exc_type):
    def handler(request):
        raise exc_type("simulated", request=request)

    return handler


def _fail(provider: GroqProvider, request: GenerationRequest = REQUEST) -> ProviderError:
    with pytest.raises(ProviderError) as info:
        provider.generate(request)
    return info.value


# --- configuration -----------------------------------------------------------------------

def test_missing_key_fails_without_any_network_call():
    provider = _provider(_no_network, key=None)
    assert provider.available is False
    error = _fail(provider)
    assert error.kind is ProviderErrorKind.MISSING_API_KEY and not error.retryable


def test_settings_use_only_groq_api_key_and_defaults():
    env = {"GROQ_API_KEY": FAKE_KEY, "GEMINI_API_KEY": "fake-gemini", "OPENROUTER_API_KEY": "fake-or"}
    provider = GroqProvider.from_settings(environ=env)
    assert provider.available and provider._api_key == FAKE_KEY
    assert (provider.model, provider.timeout) == (DEFAULT_MODEL, DEFAULT_TIMEOUT_SECONDS)
    assert GroqProvider.from_settings(environ={"GEMINI_API_KEY": "fake-gemini"}).available is False


def test_model_and_timeout_come_from_the_environment():
    env = {"GROQ_MODEL": "meta-llama/llama-test-model", "GROQ_TIMEOUT_SECONDS": "2.5"}
    provider = GroqProvider.from_settings(environ=env)
    assert (provider.model, provider.timeout) == ("meta-llama/llama-test-model", 2.5)


@pytest.mark.parametrize(
    "env",
    [
        {"GROQ_MODEL": "model name with spaces"},
        {"GROQ_MODEL": "model?x=1"},
        {"GROQ_TIMEOUT_SECONDS": "soon"},
        {"GROQ_TIMEOUT_SECONDS": "-1"},
        {"GROQ_TIMEOUT_SECONDS": "600"},
    ],
)
def test_invalid_model_or_timeout_is_rejected(env):
    with pytest.raises(ProviderConfigError):
        GroqProvider.from_settings(environ=env)


# --- success and JSON parsing -------------------------------------------------------------

def test_successful_structured_response_and_request_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json=_ok_body('{"intent": "screen_blank", "confidence": 0.9}'))

    result = _provider(handler).generate(REQUEST)
    assert result.data == {"intent": "screen_blank", "confidence": 0.9}
    assert (result.provider, result.model, result.finish_reason) == ("groq", DEFAULT_MODEL, "stop")
    assert result.latency_ms >= 0

    request = seen["request"]
    assert request.method == "POST"
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert FAKE_KEY not in str(request.url)
    body = json.loads(request.content)
    assert FAKE_KEY not in json.dumps(body)
    assert body["model"] == DEFAULT_MODEL
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0 and body["max_completion_tokens"] == 256
    system, user = body["messages"]
    assert (system["role"], user["role"]) == ("system", "user")
    assert user["content"] == REQUEST.prompt
    assert REQUEST.system_instruction in system["content"]
    assert json.dumps(dict(REQUEST.response_schema), sort_keys=True) in system["content"]


def test_json_mode_instruction_is_added_when_the_request_does_not_mention_json():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_body("{}"))

    _provider(handler).generate(GenerationRequest(prompt="Say ok."))
    system = seen["body"]["messages"][0]["content"]
    assert "json" in system.lower()
    assert "max_completion_tokens" not in seen["body"]


@pytest.mark.parametrize(
    "content, expected",
    [
        ('{"ok": true}', {"ok": True}),
        ('  {"nested": {"a": [1, 2]}}\n', {"nested": {"a": [1, 2]}}),
        ('{"text": "unicode \\u00e9"}', {"text": "unicode é"}),
    ],
)
def test_json_content_is_parsed(content, expected):
    assert _provider(lambda r: httpx.Response(200, json=_ok_body(content))).generate(REQUEST).data == expected


def test_request_timeout_is_passed_to_the_client():
    seen = {}

    def handler(request):
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json=_ok_body("{}"))

    _provider(handler, timeout=3.0).generate(REQUEST)
    assert seen["timeout"]["read"] == 3.0


# --- malformed responses ----------------------------------------------------------------

@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"role": "assistant"}}]}),
        httpx.Response(200, json=_ok_body(None)),
        httpx.Response(200, json=_ok_body("   ")),
        httpx.Response(200, json=_ok_body("this is not json")),
        httpx.Response(200, json=_ok_body('["a JSON array, not an object"]')),
        httpx.Response(200, json=_ok_body('{"truncated": ', finish="length")),
    ],
)
def test_malformed_response_is_a_typed_error(response):
    error = _fail(_provider(lambda r: response))
    assert error.kind is ProviderErrorKind.MALFORMED_RESPONSE and not error.retryable


def test_json_validation_failure_reported_by_groq_is_malformed():
    handler = _status(400, {"message": "Failed to generate JSON", "type": "invalid_request_error", "code": "json_validate_failed"})
    error = _fail(_provider(handler))
    assert (error.kind, error.status_code) == (ProviderErrorKind.MALFORMED_RESPONSE, 400)


def test_content_filter_is_reported_as_blocked():
    error = _fail(_provider(lambda r: httpx.Response(200, json=_ok_body("{}", finish="content_filter"))))
    assert error.kind is ProviderErrorKind.CONTENT_BLOCKED and not error.retryable


# --- HTTP and transport failures ----------------------------------------------------------

@pytest.mark.parametrize(
    "handler",
    [
        _status(401, {"message": "Invalid API Key", "type": "invalid_request_error", "code": "invalid_api_key"}),
        _status(403, {"message": "Forbidden", "type": "permission_error"}),
    ],
)
def test_authentication_failure(handler):
    error = _fail(_provider(handler))
    assert error.kind is ProviderErrorKind.AUTHENTICATION and not error.retryable


def test_rate_limit_or_quota_exhaustion():
    handler = _status(429, {"message": "Rate limit reached for model", "type": "tokens", "code": "rate_limit_exceeded"})
    error = _fail(_provider(handler))
    assert (error.kind, error.status_code, error.retryable) == (ProviderErrorKind.RATE_LIMITED, 429, True)


@pytest.mark.parametrize("code", [498, 500, 502, 503, 504])
def test_transient_server_failure(code):
    error = _fail(_provider(_status(code)))
    assert (error.kind, error.status_code, error.retryable) == (ProviderErrorKind.SERVER_ERROR, code, True)


@pytest.mark.parametrize("code", [400, 404, 413, 422])
def test_other_client_errors_are_bad_requests(code):
    error = _fail(_provider(_status(code, {"message": "bad request", "type": "invalid_request_error"})))
    assert error.kind is ProviderErrorKind.BAD_REQUEST and not error.retryable


@pytest.mark.parametrize("exc_type", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout])
def test_timeout(exc_type):
    error = _fail(_provider(_raise(exc_type)))
    assert error.kind is ProviderErrorKind.TIMEOUT and error.retryable


def test_upstream_408_is_a_timeout():
    assert _fail(_provider(_status(408))).kind is ProviderErrorKind.TIMEOUT


@pytest.mark.parametrize("exc_type", [httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError])
def test_network_failure(exc_type):
    error = _fail(_provider(_raise(exc_type)))
    assert error.kind is ProviderErrorKind.NETWORK and error.retryable


def test_errors_do_not_chain_the_original_exception():
    error = _fail(_provider(_raise(httpx.ConnectError)))
    assert error.__cause__ is None and error.__suppress_context__


# --- the key never leaks --------------------------------------------------------------------

LEAKY_HANDLERS = [
    _status(401, {"message": f"Invalid API Key {FAKE_KEY}", "code": "invalid_api_key"}),
    _status(429, {"message": f"rate limit for key {FAKE_KEY}"}),
    _status(500, {"message": f"internal error for {FAKE_KEY}"}),
    _status(400, {"message": f"bad request {FAKE_KEY}", "code": "json_validate_failed"}),
    _raise(httpx.ReadTimeout),
    _raise(httpx.ConnectError),
    lambda r: httpx.Response(200, content=b"not json"),
    lambda r: httpx.Response(200, json=_ok_body(f"echo {FAKE_KEY}")),
]


@pytest.mark.parametrize("handler", LEAKY_HANDLERS)
def test_key_never_appears_in_errors_or_logs(handler, caplog):
    provider = _provider(handler)
    with caplog.at_level(logging.DEBUG):
        error = _fail(provider)
        logging.getLogger("test").exception("provider failed: %s %r", error, error)
    for text in (str(error), repr(error), error.message, caplog.text, repr(provider), str(provider)):
        assert FAKE_KEY not in text


def test_key_is_not_in_the_success_path_logs_or_result(caplog):
    with caplog.at_level(logging.DEBUG):
        result = _provider(lambda r: httpx.Response(200, json=_ok_body('{"ok": true}'))).generate(REQUEST)
    assert FAKE_KEY not in caplog.text and FAKE_KEY not in repr(result)


def test_provider_repr_reports_only_whether_a_key_is_set():
    assert repr(_provider(_no_network)) == f"GroqProvider(model={DEFAULT_MODEL!r}, timeout=8.0, api_key_configured=True)"
    assert str(_provider(_no_network, key=None)).endswith("api_key_configured=False)")


# --- isolation from the troubleshooting path -------------------------------------------------

def test_provider_module_has_no_catalog_or_plan_dependency():
    source = (ROOT / "app" / "providers" / "groq.py").read_text(encoding="utf-8")
    for name in ("app.services", "catalog", "plan_validator", "plan_builder", "deeplink"):
        assert f"import {name}" not in source and f"from {name}" not in source
