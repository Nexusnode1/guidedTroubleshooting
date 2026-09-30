"""Groq structured-generation provider over Groq's OpenAI-compatible Chat Completions API.

Uses ``httpx`` (already a project dependency). The API key is taken only from
``GROQ_API_KEY`` via the provider configuration and is sent in the ``Authorization: Bearer``
header, never in the URL or body. It never appears in ``repr``, logs, or raised errors.

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

PROVIDER = "groq"
MODEL_VARIABLE = "GROQ_MODEL"
TIMEOUT_VARIABLE = "GROQ_TIMEOUT_SECONDS"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_TIMEOUT_SECONDS = 8.0
MAX_TIMEOUT_SECONDS = 120.0
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

# Groq model ids may contain an organization prefix ("org/model"); the id goes in the JSON
# body, not the URL, but is still restricted to a conservative character set.
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_DETAIL_LIMIT = 200
# JSON mode requires the conversation to ask for JSON; this is sent when the caller's own
# system instruction does not mention it.
_JSON_INSTRUCTION = "Respond with a single JSON object only."

logger = logging.getLogger(__name__)


def _parse_model(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return DEFAULT_MODEL
    if not _MODEL_NAME.match(value):
        raise ProviderConfigError(f"{MODEL_VARIABLE} must contain only letters, digits, '.', ':', '/', '-' or '_'")
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


class GroqProvider:
    """Send one structured generation request to Groq and return its JSON object."""

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
    ) -> "GroqProvider":
        """Build from the provider configuration plus ``GROQ_MODEL`` / ``GROQ_TIMEOUT_SECONDS``."""
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
        return f"GroqProvider(model={self.model!r}, timeout={self.timeout!r}, api_key_configured={self.available})"

    __str__ = __repr__

    def close(self) -> None:
        """Close the HTTP client if this provider created it."""
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "GroqProvider":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _error(self, kind: ProviderErrorKind, message: str, status_code: int | None = None) -> ProviderError:
        logger.warning("Groq request failed: %s (status %s)", kind.value, status_code)
        return ProviderError(PROVIDER, kind, self._redact(message), status_code)

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "[redacted]") if self._api_key else text

    def _body(self, request: GenerationRequest) -> dict[str, Any]:
        system_parts = [request.system_instruction] if request.system_instruction else []
        if request.response_schema is not None:
            schema = json.dumps(dict(request.response_schema), sort_keys=True)
            system_parts.append(f"The JSON object must match this schema: {schema}")
        if not any("json" in part.lower() for part in system_parts):
            system_parts.append(_JSON_INSTRUCTION)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "\n\n".join(system_parts)},
                {"role": "user", "content": request.prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": request.temperature,
        }
        if request.max_output_tokens is not None:
            body["max_completion_tokens"] = request.max_output_tokens
        return body

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Return the model's JSON object for ``request`` or raise ``ProviderError``."""
        if self._api_key is None:
            raise ProviderError(PROVIDER, ProviderErrorKind.MISSING_API_KEY, "GROQ_API_KEY is not set")
        if self._client is None:
            self._client = httpx.Client()
        started = time.perf_counter()
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                json=self._body(request),
                headers={"authorization": f"Bearer {self._api_key}", "content-type": "application/json"},
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
        detail, code = _error_detail(response)
        if status in (401, 403) or code == "invalid_api_key":
            return self._error(ProviderErrorKind.AUTHENTICATION, f"authentication failed: {detail}", status)
        if status == 429:
            return self._error(ProviderErrorKind.RATE_LIMITED, f"rate limit or quota exhausted: {detail}", status)
        if status == 408:
            return self._error(ProviderErrorKind.TIMEOUT, f"request timed out upstream: {detail}", status)
        if status == 498 or status >= 500:
            # 498 is Groq's "capacity exceeded" status; like a 5xx it is temporary.
            return self._error(ProviderErrorKind.SERVER_ERROR, f"server error: {detail}", status)
        if code == "json_validate_failed":
            return self._error(ProviderErrorKind.MALFORMED_RESPONSE, f"model did not produce valid JSON: {detail}", status)
        return self._error(ProviderErrorKind.BAD_REQUEST, f"request rejected: {detail}", status)

    def _parse(self, response: httpx.Response, latency_ms: int) -> GenerationResult:
        malformed = ProviderErrorKind.MALFORMED_RESPONSE
        try:
            payload = response.json()
        except ValueError:
            raise self._error(malformed, "response body is not JSON", response.status_code) from None
        if not isinstance(payload, dict):
            raise self._error(malformed, "response body is not a JSON object")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise self._error(malformed, "response has no choices")
        choice = choices[0]
        finish = choice.get("finish_reason")
        if finish == "content_filter":
            raise self._error(ProviderErrorKind.CONTENT_BLOCKED, "output blocked (content_filter)")
        if finish == "length":
            raise self._error(malformed, "output was truncated (length)")
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise self._error(malformed, "choice has no text content")
        try:
            data = json.loads(content)
        except ValueError:
            raise self._error(malformed, "choice content is not valid JSON") from None
        if not isinstance(data, dict):
            raise self._error(malformed, "choice JSON is not an object")
        return GenerationResult(PROVIDER, self.model, data, latency_ms, finish if isinstance(finish, str) else None)


def _error_detail(response: httpx.Response) -> tuple[str, str]:
    """Return a short upstream error message and its machine-readable code, if any."""
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        return f"HTTP {response.status_code}", ""
    if not isinstance(error, dict):
        return f"HTTP {response.status_code}", ""
    message = str(error.get("message") or error.get("type") or f"HTTP {response.status_code}")
    code = error.get("code")
    return message[:_DETAIL_LIMIT], code if isinstance(code, str) else ""
