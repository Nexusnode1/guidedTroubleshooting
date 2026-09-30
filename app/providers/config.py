"""Settings for optional external AI providers, read from environment variables.

Nothing here makes a network call. Every API key is optional: with none set (or with
``AI_PROVIDER_MODE=local``) no external provider is available and the app runs rules-only.
API keys are never included in ``repr``/``str`` output or in error messages.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import os
import re

KNOWN_PROVIDERS = ("gemini", "groq", "openrouter")
API_KEY_VARIABLES = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
MODE_VARIABLE = "AI_PROVIDER_MODE"
ORDER_VARIABLE = "AI_PROVIDER_ORDER"
DEFAULT_ORDER = KNOWN_PROVIDERS

# A value is only echoed back in an error if it looks like a short identifier, so a
# secret pasted into the wrong variable is never repeated in an exception or log line.
_SAFE_TO_ECHO = re.compile(r"^[a-z0-9_-]{1,24}$")


class ProviderMode(str, Enum):
    """How the app may use external providers."""

    AUTO = "auto"  # use configured providers, in order; rules-only when none is configured
    LOCAL = "local"  # never use an external provider


class ProviderConfigError(ValueError):
    """Raised for invalid provider configuration. Messages never contain secret values."""


def _describe(value: str) -> str:
    return repr(value) if _SAFE_TO_ECHO.match(value) else "an unrecognised value (not shown)"


def _parse_mode(raw: str | None) -> ProviderMode:
    value = (raw or "").strip().lower()
    if not value:
        return ProviderMode.AUTO
    try:
        return ProviderMode(value)
    except ValueError:
        allowed = ", ".join(mode.value for mode in ProviderMode)
        raise ProviderConfigError(f"{MODE_VARIABLE} must be one of: {allowed}; got {_describe(value)}") from None


def _parse_order(raw: str | None) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return DEFAULT_ORDER
    names = [name.strip().lower() for name in raw.split(",")]
    if any(not name for name in names):
        raise ProviderConfigError(f"{ORDER_VARIABLE} contains an empty provider name")
    unknown = [name for name in names if name not in KNOWN_PROVIDERS]
    if unknown:
        allowed = ", ".join(KNOWN_PROVIDERS)
        shown = ", ".join(_describe(name) for name in unknown)
        raise ProviderConfigError(f"{ORDER_VARIABLE} has unknown provider(s) {shown}; allowed: {allowed}")
    if len(set(names)) != len(names):
        raise ProviderConfigError(f"{ORDER_VARIABLE} lists a provider more than once")
    return tuple(names)


@dataclass(frozen=True)
class ProviderSettings:
    """Validated provider settings. API keys are kept out of ``repr`` and ``str``."""

    mode: ProviderMode
    order: tuple[str, ...]
    _api_keys: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)

    def has_api_key(self, provider: str) -> bool:
        """Return whether an API key is configured for ``provider``."""
        return bool(self._api_keys.get(provider))

    def api_key(self, provider: str) -> str | None:
        """Return the API key for ``provider``, or ``None``. Callers must not log it."""
        if provider not in KNOWN_PROVIDERS:
            raise ProviderConfigError(f"unknown provider {_describe(provider)}")
        return self._api_keys.get(provider) or None

    @property
    def active_providers(self) -> tuple[str, ...]:
        """Providers the app may call, in order: none in local mode or when no key is set."""
        if self.mode is ProviderMode.LOCAL:
            return ()
        return tuple(name for name in self.order if self.has_api_key(name))

    @property
    def uses_external_providers(self) -> bool:
        """Whether at least one external provider is available."""
        return bool(self.active_providers)

    def __repr__(self) -> str:
        configured = ", ".join(name for name in KNOWN_PROVIDERS if self.has_api_key(name)) or "none"
        return (
            f"ProviderSettings(mode={self.mode.value!r}, order={self.order!r}, "
            f"api_keys_configured=[{configured}])"
        )

    __str__ = __repr__


def load_provider_settings(environ: Mapping[str, str] | None = None) -> ProviderSettings:
    """Read and validate provider settings from ``environ`` (``os.environ`` by default).

    Missing API keys are allowed. Raises ``ProviderConfigError`` for an unknown mode or
    provider name, an empty entry, or a duplicate in the provider order.
    """
    env = os.environ if environ is None else environ
    keys = {
        name: value.strip()
        for name, variable in API_KEY_VARIABLES.items()
        if (value := env.get(variable)) and value.strip()
    }
    return ProviderSettings(
        mode=_parse_mode(env.get(MODE_VARIABLE)),
        order=_parse_order(env.get(ORDER_VARIABLE)),
        _api_keys=keys,
    )
