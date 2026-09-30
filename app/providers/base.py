"""Provider-neutral request/result types and the typed error every provider raises.

These types carry generic structured-generation data only. Nothing here selects, builds,
or edits a deeplink: plans are still produced and validated by the existing pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class GenerationRequest:
    """A structured (JSON) generation request.

    ``response_schema`` is passed to the provider to constrain its JSON output. The result
    must be a JSON object; callers validate its fields themselves.
    """

    prompt: str
    system_instruction: str | None = None
    response_schema: Mapping[str, Any] | None = None
    temperature: float = 0.0
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class GenerationResult:
    """Parsed JSON object returned by a provider, with where it came from."""

    provider: str
    model: str
    data: dict[str, Any] = field(repr=False)
    latency_ms: int
    finish_reason: str | None = None


class ProviderErrorKind(str, Enum):
    """Failure categories a router can act on."""

    MISSING_API_KEY = "missing_api_key"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER_ERROR = "server_error"
    BAD_REQUEST = "bad_request"
    CONTENT_BLOCKED = "content_blocked"
    MALFORMED_RESPONSE = "malformed_response"


_RETRYABLE = frozenset(
    {ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.TIMEOUT, ProviderErrorKind.NETWORK, ProviderErrorKind.SERVER_ERROR}
)


class ProviderError(Exception):
    """A provider call failed. The message never contains credentials."""

    def __init__(self, provider: str, kind: ProviderErrorKind, message: str, status_code: int | None = None) -> None:
        super().__init__(f"{provider}: {kind.value}: {message}")
        self.provider = provider
        self.kind = kind
        self.message = message
        self.status_code = status_code

    @property
    def retryable(self) -> bool:
        """Whether trying again later, or another provider, could succeed."""
        return self.kind in _RETRYABLE

    def __repr__(self) -> str:
        return f"ProviderError(provider={self.provider!r}, kind={self.kind.value!r}, status_code={self.status_code!r})"
