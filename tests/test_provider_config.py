"""External AI provider settings: read from the environment, validated, never leak keys."""

import logging

import pytest

from app.providers.config import (
    DEFAULT_ORDER,
    KNOWN_PROVIDERS,
    ProviderConfigError,
    ProviderMode,
    load_provider_settings,
)

FAKE_KEYS = {
    "GEMINI_API_KEY": "fake-gemini-key-0001",
    "GROQ_API_KEY": "fake-groq-key-0002",
    "OPENROUTER_API_KEY": "fake-openrouter-key-0003",
}


def test_no_api_keys_is_a_valid_rules_only_configuration():
    settings = load_provider_settings({})
    assert settings.mode is ProviderMode.AUTO
    assert settings.order == DEFAULT_ORDER
    assert settings.active_providers == ()
    assert settings.uses_external_providers is False
    assert all(settings.api_key(name) is None for name in KNOWN_PROVIDERS)


def test_blank_api_keys_count_as_missing():
    settings = load_provider_settings({"GEMINI_API_KEY": "", "GROQ_API_KEY": "   "})
    assert not settings.has_api_key("gemini") and not settings.has_api_key("groq")
    assert settings.active_providers == ()


def test_environment_variables_are_read():
    settings = load_provider_settings(
        {**FAKE_KEYS, "AI_PROVIDER_MODE": "auto", "AI_PROVIDER_ORDER": "groq,gemini,openrouter"}
    )
    assert settings.api_key("gemini") == "fake-gemini-key-0001"
    assert settings.api_key("groq") == "fake-groq-key-0002"
    assert settings.api_key("openrouter") == "fake-openrouter-key-0003"
    assert settings.active_providers == ("groq", "gemini", "openrouter")


def test_defaults_to_os_environ(monkeypatch):
    for variable in (*FAKE_KEYS, "AI_PROVIDER_MODE", "AI_PROVIDER_ORDER"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key-0002")
    monkeypatch.setenv("AI_PROVIDER_ORDER", "openrouter,groq")
    settings = load_provider_settings()
    assert settings.order == ("openrouter", "groq")
    assert settings.active_providers == ("groq",)


def test_api_key_values_are_stripped():
    assert load_provider_settings({"GEMINI_API_KEY": "  fake-gemini-key-0001\n"}).api_key("gemini") == "fake-gemini-key-0001"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("gemini,groq,openrouter", ("gemini", "groq", "openrouter")),
        ("openrouter", ("openrouter",)),
        (" Groq , GEMINI ", ("groq", "gemini")),
        ("", DEFAULT_ORDER),
        ("   ", DEFAULT_ORDER),
    ],
)
def test_provider_order_parsing(raw, expected):
    assert load_provider_settings({"AI_PROVIDER_ORDER": raw}).order == expected


def test_only_listed_providers_with_keys_are_active():
    settings = load_provider_settings({**FAKE_KEYS, "AI_PROVIDER_ORDER": "openrouter,gemini"})
    assert settings.active_providers == ("openrouter", "gemini")


def test_unset_mode_defaults_to_auto_and_is_case_insensitive():
    assert load_provider_settings({}).mode is ProviderMode.AUTO
    assert load_provider_settings({"AI_PROVIDER_MODE": " LOCAL "}).mode is ProviderMode.LOCAL


def test_local_mode_never_uses_external_providers_even_with_keys():
    settings = load_provider_settings({**FAKE_KEYS, "AI_PROVIDER_MODE": "local"})
    assert settings.mode is ProviderMode.LOCAL
    assert settings.active_providers == ()
    assert settings.uses_external_providers is False


@pytest.mark.parametrize(
    "env, message",
    [
        ({"AI_PROVIDER_MODE": "cloud"}, "AI_PROVIDER_MODE must be one of: auto, local"),
        ({"AI_PROVIDER_ORDER": "gemini,acme"}, "unknown provider(s) 'acme'"),
        ({"AI_PROVIDER_ORDER": "gemini,,groq"}, "empty provider name"),
        ({"AI_PROVIDER_ORDER": "groq,groq"}, "more than once"),
    ],
)
def test_invalid_configuration_fails_clearly(env, message):
    with pytest.raises(ProviderConfigError, match=message.replace("(", r"\(").replace(")", r"\)")):
        load_provider_settings(env)


def test_unknown_provider_lookup_is_rejected():
    with pytest.raises(ProviderConfigError):
        load_provider_settings({}).api_key("unknown")


def test_keys_are_not_in_repr_or_str():
    settings = load_provider_settings(FAKE_KEYS)
    for text in (repr(settings), str(settings), f"{settings}"):
        assert all(key not in text for key in FAKE_KEYS.values())
    assert "api_keys_configured=[gemini, groq, openrouter]" in repr(settings)


def test_a_secret_pasted_into_the_wrong_variable_is_not_echoed():
    secret = "Pasted-Secret-Value-Not-A-Real-Key-1234567890"
    for env in ({"AI_PROVIDER_ORDER": f"gemini,{secret}"}, {"AI_PROVIDER_MODE": secret}):
        with pytest.raises(ProviderConfigError) as error:
            load_provider_settings({**FAKE_KEYS, **env})
        text = f"{error.value} {error.value!r}"
        assert secret not in text and secret.lower() not in text
        assert all(key not in text for key in FAKE_KEYS.values())
        assert "not shown" in text


def test_loading_settings_logs_nothing_containing_keys(caplog):
    with caplog.at_level(logging.DEBUG):
        settings = load_provider_settings({**FAKE_KEYS, "AI_PROVIDER_MODE": "auto"})
        logging.getLogger("test").info("provider settings: %s", settings)
    assert all(key not in caplog.text for key in FAKE_KEYS.values())


def test_the_application_works_without_any_api_key(monkeypatch, tmp_path, siis_rows):
    from fastapi.testclient import TestClient

    import app.main as main
    from app.retrieval.embeddings import HashEmbeddingModel

    for variable in (*FAKE_KEYS, "AI_PROVIDER_MODE", "AI_PROVIDER_ORDER"):
        monkeypatch.delenv(variable, raising=False)
    assert load_provider_settings().uses_external_providers is False
    original = main.build_default_service
    path = tmp_path / "plan_cache.json"
    monkeypatch.setattr(main, "build_default_service", lambda: original(cache_path=path, embedder=HashEmbeddingModel()))
    query = next(r for r in siis_rows if r["id"] == "row_21")["original_query"]
    with TestClient(main.app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        body = client.post("/v1/troubleshoot", json={"query": query}).json()
    assert body["response"]["contexts"] and body["meta"]["model"] == "rules-v1"
