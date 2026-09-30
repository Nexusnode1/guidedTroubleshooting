"""Gemini provider against mocked HTTP responses: no network, no real API key."""

import json
import logging
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from app.providers.base import GenerationRequest, ProviderError, ProviderErrorKind
from app.providers.config import ProviderConfigError
from app.providers.gemini import DEFAULT_MODEL, DEFAULT_TIMEOUT_SECONDS, GeminiProvider

ROOT = Path(__file__).resolve().parents[1]
FAKE_KEY = "fake-gemini-key-for-tests-0001"
REQUEST = GenerationRequest(
    prompt="Summarize the complaint.",
    system_instruction="Return JSON only.",
    response_schema={"type": "OBJECT", "properties": {"intent": {"type": "STRING"}}},
    max_output_tokens=256,
)


def _ok_body(text: str, finish: str = "STOP") -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}]}


def _provider(handler, key: str | None = FAKE_KEY, **kwargs) -> GeminiProvider:
    return GeminiProvider(api_key=key, client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError("no HTTP request may be sent")


def _status(code: int, error: dict | None = None):
    def handler(request):
        return httpx.Response(code, json={"error": error or {"code": code, "message": f"status {code}"}})

    return handler


def _raise(exc_type):
    def handler(request):
        raise exc_type("simulated", request=request)

    return handler


def _fail(provider: GeminiProvider) -> ProviderError:
    with pytest.raises(ProviderError) as info:
        provider.generate(REQUEST)
    return info.value


# --- configuration -----------------------------------------------------------------------

def test_missing_key_fails_without_any_network_call():
    provider = _provider(_no_network, key=None)
    assert provider.available is False
    error = _fail(provider)
    assert error.kind is ProviderErrorKind.MISSING_API_KEY and not error.retryable


def test_settings_use_only_gemini_api_key_and_defaults():
    env = {"GEMINI_API_KEY": FAKE_KEY, "GROQ_API_KEY": "fake-groq", "OPENROUTER_API_KEY": "fake-or"}
    provider = GeminiProvider.from_settings(environ=env)
    assert provider.available and provider._api_key == FAKE_KEY
    assert (provider.model, provider.timeout) == (DEFAULT_MODEL, DEFAULT_TIMEOUT_SECONDS)
    assert GeminiProvider.from_settings(environ={"GROQ_API_KEY": "fake-groq"}).available is False


def test_model_and_timeout_come_from_the_environment():
    provider = GeminiProvider.from_settings(environ={"GEMINI_MODEL": "gemini-test-model", "GEMINI_TIMEOUT_SECONDS": "2.5"})
    assert (provider.model, provider.timeout) == ("gemini-test-model", 2.5)


@pytest.mark.parametrize(
    "env",
    [
        {"GEMINI_MODEL": "../../other"},
        {"GEMINI_MODEL": "model?key=x"},
        {"GEMINI_TIMEOUT_SECONDS": "soon"},
        {"GEMINI_TIMEOUT_SECONDS": "0"},
        {"GEMINI_TIMEOUT_SECONDS": "600"},
    ],
)
def test_invalid_model_or_timeout_is_rejected(env):
    with pytest.raises(ProviderConfigError):
        GeminiProvider.from_settings(environ=env)


# --- success ------------------------------------------------------------------------------

def test_successful_structured_response_and_request_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json=_ok_body('{"intent": "screen_blank", "confidence": 0.9}'))

    result = _provider(handler).generate(REQUEST)
    assert result.data == {"intent": "screen_blank", "confidence": 0.9}
    assert (result.provider, result.model, result.finish_reason) == ("gemini", DEFAULT_MODEL, "STOP")
    assert result.latency_ms >= 0

    request = seen["request"]
    assert request.method == "POST"
    assert str(request.url) == f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_MODEL}:generateContent"
    assert request.headers["x-goog-api-key"] == FAKE_KEY
    assert FAKE_KEY not in str(request.url)
    body = json.loads(request.content)
    assert body["contents"][0]["parts"][0]["text"] == REQUEST.prompt
    assert body["systemInstruction"]["parts"][0]["text"] == REQUEST.system_instruction
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"] == REQUEST.response_schema
    assert config["maxOutputTokens"] == 256 and config["temperature"] == 0.0


def test_json_split_across_parts_is_joined():
    body = {"candidates": [{"content": {"parts": [{"text": '{"a": '}, {"text": "1}"}]}, "finishReason": "STOP"}]}
    assert _provider(lambda r: httpx.Response(200, json=body)).generate(REQUEST).data == {"a": 1}


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
        httpx.Response(200, json={"candidates": []}),
        httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]}),
        httpx.Response(200, json=_ok_body("this is not json")),
        httpx.Response(200, json=_ok_body('["a JSON array, not an object"]')),
        httpx.Response(200, json=_ok_body('{"truncated": ', finish="MAX_TOKENS")),
    ],
)
def test_malformed_response_is_a_typed_error(response):
    error = _fail(_provider(lambda r: response))
    assert error.kind is ProviderErrorKind.MALFORMED_RESPONSE and not error.retryable


@pytest.mark.parametrize(
    "body",
    [
        {"promptFeedback": {"blockReason": "SAFETY"}},
        _ok_body("{}", finish="SAFETY"),
    ],
)
def test_blocked_content_is_reported(body):
    assert _fail(_provider(lambda r: httpx.Response(200, json=body))).kind is ProviderErrorKind.CONTENT_BLOCKED


# --- HTTP and transport failures ----------------------------------------------------------

@pytest.mark.parametrize(
    "handler",
    [
        _status(401),
        _status(403, {"code": 403, "message": "Permission denied", "status": "PERMISSION_DENIED"}),
        _status(400, {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                      "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}),
    ],
)
def test_authentication_failure(handler):
    error = _fail(_provider(handler))
    assert error.kind is ProviderErrorKind.AUTHENTICATION and not error.retryable


def test_rate_limit_or_quota_exhaustion():
    error = _fail(_provider(_status(429, {"code": 429, "message": "Resource has been exhausted", "status": "RESOURCE_EXHAUSTED"})))
    assert (error.kind, error.status_code, error.retryable) == (ProviderErrorKind.RATE_LIMITED, 429, True)


@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_transient_server_failure(code):
    error = _fail(_provider(_status(code)))
    assert (error.kind, error.status_code, error.retryable) == (ProviderErrorKind.SERVER_ERROR, code, True)


def test_other_client_errors_are_bad_requests():
    error = _fail(_provider(_status(400, {"code": 400, "message": "Invalid JSON payload", "status": "INVALID_ARGUMENT"})))
    assert error.kind is ProviderErrorKind.BAD_REQUEST and not error.retryable


@pytest.mark.parametrize("exc_type", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout])
def test_timeout(exc_type):
    error = _fail(_provider(_raise(exc_type)))
    assert error.kind is ProviderErrorKind.TIMEOUT and error.retryable


@pytest.mark.parametrize("exc_type", [httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError])
def test_network_failure(exc_type):
    error = _fail(_provider(_raise(exc_type)))
    assert error.kind is ProviderErrorKind.NETWORK and error.retryable


def test_errors_do_not_chain_the_original_exception():
    error = _fail(_provider(_raise(httpx.ConnectError)))
    assert error.__cause__ is None and error.__suppress_context__


# --- the key never leaks --------------------------------------------------------------------

LEAKY_HANDLERS = [
    _status(400, {"code": 400, "message": f"API key not valid: {FAKE_KEY}", "details": [{"reason": "API_KEY_INVALID"}]}),
    _status(429, {"code": 429, "message": f"quota for key {FAKE_KEY} exhausted"}),
    _status(500, {"code": 500, "message": f"internal error for {FAKE_KEY}"}),
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
    assert repr(_provider(_no_network)) == f"GeminiProvider(model={DEFAULT_MODEL!r}, timeout=8.0, api_key_configured=True)"


# --- isolation from the troubleshooting path -------------------------------------------------

def test_provider_module_has_no_catalog_or_plan_dependency():
    source = (ROOT / "app" / "providers" / "gemini.py").read_text(encoding="utf-8")
    for name in ("app.services", "catalog", "plan_validator", "plan_builder", "deeplink"):
        assert f"import {name}" not in source and f"from {name}" not in source


def test_troubleshooting_code_does_not_import_any_provider():
    for path in [ROOT / "app" / "main.py", *(ROOT / "app" / "api").glob("*.py"), *(ROOT / "app" / "services").glob("*.py")]:
        assert "app.providers" not in path.read_text(encoding="utf-8"), path.name


def test_serving_a_request_never_loads_the_gemini_module():
    script = (
        "import sys, httpx\n"
        "from fastapi.testclient import TestClient\n"
        "import app.main as main\n"
        "from app.retrieval.embeddings import HashEmbeddingModel\n"
        "import tempfile, pathlib\n"
        "path = pathlib.Path(tempfile.mkdtemp()) / 'plan_cache.json'\n"
        "original = main.build_default_service\n"
        "main.build_default_service = lambda: original(cache_path=path, embedder=HashEmbeddingModel())\n"
        "from app.services.catalog import load_siis_rows\n"
        "query = next(r for r in load_siis_rows() if r['id'] == 'row_21')['original_query']\n"
        "with TestClient(main.app) as c:\n"
        "    body = c.post('/v1/troubleshoot', json={'query': query}).json()\n"
        "print(body['meta']['model'], body['meta']['cache_hit'], bool(body['response']['contexts']),\n"
        "      'app.providers.gemini' in sys.modules)\n"
    )
    env = {"GEMINI_API_KEY": FAKE_KEY, "PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    out = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.split()[-4:] == ["rules-v1", "True", "True", "False"]
