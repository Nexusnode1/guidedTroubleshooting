# Data Model

Output shape: `app/models/official_schema.py` (verbatim copy of the participant kit's `schema.py`): `ContextDeeplinkResponse` holds `Goal`s, each with `Action`s, each with `StepGroup`s carrying an optional `actionableDeeplink` and `validationDeeplink`.

Response body of `POST /v1/troubleshoot`:

    {"query", "query_variations": [8-10], "response": {"contexts": [...]}, "meta": {"latency_ms", "cache_hit", "model", "cost_usd", "fallback"?}}

`meta.fallback` is `"no_match"` (nothing relevant cached) or `"no_siis_context"` (cache empty), with `contexts: []`.

Inputs: `data/original/deeplinks.json` (578 masked deeplinks), `siis_responses.json` (20 rows), `input.txt`, `sample_output.json`. Generated and git-ignored: `data/processed/plan_cache.json`, `training_pairs.jsonl`.
