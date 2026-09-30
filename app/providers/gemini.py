"""Gemini structured-generation provider over the Gemini API's REST ``generateContent`` method.

Uses ``httpx`` (already a project dependency). The API key is taken only from
``GEMINI_API_KEY`` via the provider configuration and is sent in the ``x-goog-api-key``
header, never in the URL. It never appears in ``repr``, logs, or raised errors.

This module is not used by the troubleshooting service. It returns parsed JSON or raises a
typed ``ProviderError``; it has no knowledge of the deeplink catalog or plan validation.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import logging
import os
import re
import time
from typing import Any

import httpx

from app.providers.base import GenerationRequest, GenerationResult, ProviderError, ProviderErrorKind
from app.providers.config import ProviderConfigError, ProviderSettings, load_provider_settings

PROVIDER = "gemini"
MODEL_VARIABLE = "GEMINI_MODEL"
TIMEOUT_VARIABLE = "GEMINI_TIMEOUT_SECONDS"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TIMEOUT_SECONDS = 8.0
MAX_TIMEOUT_SECONDS = 120.0
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_BLOCKED_FINISH = frozenset({"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"})
_DETAIL_LIMIT = 200

logger = logging.getLogger(__name__)


def _parse_model(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return DEFAULT_MODEL
    if not _MODEL_NAME.match(value):
        raise ProviderConfigError(f"{MODEL_VARIABLE} must contain only letters, digits, '.', '-' or '_'")
    return value


def _parse_timeout(raw: str | None) -> float:
    value = (raw or "").strip()
    if not value:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        seconds = float(value)
    except ValueError:
        raise ProviderConfigError(f"{TIMEOUT_VARIABLE} must be a number of seconds") from None
    if not 0 < seconds <= MAX_TIMEOUT_SECONDS:
        raise ProviderConfigError(f"{TIMEOUT_VARIABLE} must be greater than 0 and at most {MAX_TIMEOUT_SECONDS:g}")
    return seconds


class GeminiProvider:
    """Send one structured generation request to Gemini and return its JSON object."""

    name = PROVIDER

    def __init__(
        self,
        api_key: str | None,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key or None
        self.model = _parse_model(model)
        self.timeout = timeout
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None

    @classmethod
    def from_settings(
        cls,
        settings: ProviderSettings | None = None,
        environ: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> "GeminiProvider":
        """Build from the provider configuration plus ``GEMINI_MODEL`` / ``GEMINI_TIMEOUT_SECONDS``."""
        env = os.environ if environ is None else environ
        settings = settings or load_provider_settings(env)
        return cls(
            api_key=settings.api_key(PROVIDER),
            model=_parse_model(env.get(MODEL_VARIABLE)),
            timeout=_parse_timeout(env.get(TIMEOUT_VARIABLE)),
            client=client,
        )

    @property
    def available(self) -> bool:
        """Whether an API key is configured (no network check)."""
        return self._api_key is not None

    def __repr__(self) -> str:
        return f"GeminiProvider(model={self.model!r}, timeout={self.timeout!r}, api_key_configured={self.available})"

    __str__ = __repr__

    def close(self) -> None:
        """Close the HTTP client if this provider created it."""
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "GeminiProvider":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _error(self, kind: ProviderErrorKind, message: str, status_code: int | None = None) -> ProviderError:
        logger.warning("Gemini request failed: %s (status %s)", kind.value, status_code)
        return ProviderError(PROVIDER, kind, self._redact(message), status_code)

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "[redacted]") if self._api_key else text

    def _body(self, request: GenerationRequest) -> dict[str, Any]:
        config: dict[str, Any] = {"responseMimeType": "application/json", "temperature": request.temperature}
        if request.response_schema is not None:
            config["responseSchema"] = dict(request.response_schema)
        if request.max_output_tokens is not None:
            config["maxOutputTokens"] = request.max_output_tokens
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
            "generationConfig": config,
        }
        if request.system_instruction:
            body["systemInstruction"] = {"parts": [{"text": request.system_instruction}]}
        return body

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Return the model's JSON object for ``request`` or raise ``ProviderError``."""
        if self._api_key is None:
            raise ProviderError(PROVIDER, ProviderErrorKind.MISSING_API_KEY, "GEMINI_API_KEY is not set")
        if self._client is None:
            self._client = httpx.Client()
        url = f"{self._base_url}/models/{self.model}:generateContent"
        started = time.perf_counter()
        try:
            response = self._client.post(
                url,
                json=self._body(request),
                headers={"x-goog-api-key": self._api_key, "content-type": "application/json"},
                timeout=self.timeout,
            )
        except httpx.TimeoutException:
            raise self._error(ProviderErrorKind.TIMEOUT, f"no response within {self.timeout:g} s") from None
        except httpx.TransportError as exc:
            raise self._error(ProviderErrorKind.NETWORK, f"network error ({type(exc).__name__})") from None
        latency_ms = int(round((time.perf_counter() - started) * 1000))
        if response.status_code != 200:
            raise self._http_error(response)
        return self._parse(response, latency_ms)

    def _http_error(self, response: httpx.Response) -> ProviderError:
        status = response.status_code
        detail, reason = _error_detail(response)
        if status in (401, 403) or (status == 400 and ("API_KEY" in reason or "api key" in detail.lower())):
            return self._error(ProviderErrorKind.AUTHENTICATION, f"authentication failed: {detail}", status)
        if status == 429:
            return self._error(ProviderErrorKind.RATE_LIMITED, f"rate limit or quota exhausted: {detail}", status)
        if status == 408:
            return self._error(ProviderErrorKind.TIMEOUT, f"request timed out upstream: {detail}", status)
        if status >= 500:
            return self._error(ProviderErrorKind.SERVER_ERROR, f"server error: {detail}", status)
        return self._error(ProviderErrorKind.BAD_REQUEST, f"request rejected: {detail}", status)

    def _parse(self, response: httpx.Response, latency_ms: int) -> GenerationResult:
        malformed = ProviderErrorKind.MALFORMED_RESPONSE
        try:
            payload = response.json()
        except ValueError:
            raise self._error(malformed, "response body is not JSON", response.status_code) from None
        if not isinstance(payload, dict):
            raise self._error(malformed, "response body is not a JSON object")
        feedback = payload.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            raise self._error(ProviderErrorKind.CONTENT_BLOCKED, f"prompt blocked ({feedback['blockReason']})")
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            raise self._error(malformed, "response has no candidates")
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish in _BLOCKED_FINISH:
            raise self._error(ProviderErrorKind.CONTENT_BLOCKED, f"output blocked ({finish})")
        if finish == "MAX_TOKENS":
            raise self._error(malformed, "output was truncated (MAX_TOKENS)")
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        texts = [p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)] if isinstance(parts, list) else []
        if not texts:
            raise self._error(malformed, "candidate has no text")
        try:
            data = json.loads("".join(texts))
        except ValueError:
            raise self._error(malformed, "candidate text is not valid JSON") from None
        if not isinstance(data, dict):
            raise self._error(malformed, "candidate JSON is not an object")
        return GenerationResult(PROVIDER, self.model, data, latency_ms, finish if isinstance(finish, str) else None)


def _error_detail(response: httpx.Response) -> tuple[str, str]:
    """Return a short upstream error message and any machine-readable reason codes."""
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        return f"HTTP {response.status_code}", ""
    if not isinstance(error, dict):
        return f"HTTP {response.status_code}", ""
    message = str(error.get("message") or error.get("status") or f"HTTP {response.status_code}")
    reasons = " ".join(
        str(item.get("reason", "")) for item in error.get("details", []) or [] if isinstance(item, dict)
    )
    return message[:_DETAIL_LIMIT], reasons
