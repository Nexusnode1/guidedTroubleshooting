# Docker + Latency Benchmark

## IMPORTANT: how these numbers were actually measured

**Docker itself was not available to build or run in the environment this work was done in**
(`docker: command not found`). The Dockerfile, `.dockerignore`, and `docker-compose.yml` below
were written and reviewed carefully, but **were not literally built or started as a
container** -- that could not be verified here. Every latency, health, and smoke-test number
in this document is a **real, measured local measurement**: the exact same application code,
dependencies, `EMBEDDING_MODEL`, and startup path the Dockerfile uses, run directly via
`uvicorn` on the machine this was written on, hit with real HTTP requests over loopback TCP via
`httpx`. Nothing here is estimated, guessed, or extrapolated. They are not container
measurements, and container overhead (typically small for a CPU-bound, no-external-dependency
service like this one, but not measured here) is not included.

## Image/build approach

- Base: `python:3.11-slim` (unchanged from the project's existing Dockerfile).
- Dependencies installed from `requirements.txt` first (Docker layer caching: this layer only
  rebuilds when dependencies change, not on every code change).
- The embedding model (`sentence-transformers/all-mpnet-base-v2`, matching `EMBEDDING_MODEL`)
  is downloaded and cached **at image build time**, into `HF_HOME=/app/.cache/huggingface`
  inside the image. This is the only network call the whole build makes; starting or
  restarting a container never touches the network for model weights.
- The plan cache (`data/processed/plan_cache.json`) is rebuilt from the official data **at
  image build time** via `scripts/build_plans.py`, rather than trusting whatever happens to be
  on the build machine's disk (`.dockerignore` excludes `data/processed/` from the build
  context for exactly this reason: the image's cache file always comes from the deterministic,
  rules-only pipeline over `data/original/`, never from a stale local file). This only bakes in
  plan *content*; `PlanCache.load()` re-embeds every key with whichever `EMBEDDING_MODEL` is
  configured at container startup and re-validates every entry against the schema (see Cache
  safety, below), so this cannot smuggle an unvalidated or stale-embedding plan into a running
  container.
- `.dockerignore` excludes `tests/`, `docs/`, `frontend/`, dev artifacts, and the git directory,
  keeping the image production-sized.
- `docker-compose.yml` (single service, no new services added) documents the port mapping and
  the two environment variables (`EMBEDDING_MODEL`, `SIMILARITY_THRESHOLD`) a reviewer would
  want to override, with the same defaults `app/config.py` already uses.

## Startup behavior

`app/main.py`'s `lifespan` builds the full service (`build_default_service()`: load the
catalog, load or build the plan cache, load the embedding model) **before** the app starts
accepting traffic; `app.state.service` is `None` until this completes.

Measured startup-to-ready time (this machine, model already cached locally by an earlier run
in this session -- a cold, never-before-run machine would additionally pay the model download
time once): **16.8 seconds**.

## Health endpoint

`GET /health` already existed and already does real readiness checking (not touched in this
task beyond confirming it): it returns `503 {"status": "initializing"}` until
`app.state.service` is set, and `200 {"status": "ok"}` only afterward. It does not fake
readiness. Existing tests (`tests/test_api.py::test_health_is_ok_when_initialised` and
`::test_health_is_503_before_initialisation`) already cover both states; no new test was
needed. The Dockerfile adds a `HEALTHCHECK` that calls this same endpoint.

## Benchmark methodology

`scripts/benchmark_latency.py`:
1. Launches `uvicorn app.main:app` as a real subprocess, polls `/health` until ready.
2. **Smoke test**: one request for a known-good official query (`row_21`, touchscreen issues).
   Validates the response against `ContextDeeplinkResponse` (the official schema), that every
   `actionableDeeplink` is either the documented placeholder or verbatim in
   `data/original/deeplinks.json`, and that no `manual` action carries one.
3. **Cold path**: 30 requests, each with `siis_response` supplied (which always takes the full
   enrichment -> extraction -> relevance -> deeplink-mapping -> ordering -> validation path,
   never the cache -- see `TroubleshootingService._resolve`), cycled across the 17 official
   SIIS rows that are not gated by the relevance gate. Each request also varies its own query
   text slightly so no two cold requests are literally identical.
4. **Fast path**: 30 exact repeats of one already-cached official query (guaranteed cache hit),
   plus all 28 held-out paraphrases from `tests/fixtures/paraphrases.json` and
   `paraphrases_holdout.json` -- the same, already-verified fixtures used for the accuracy
   benchmarks in `docs/siis_paraphrase_baseline_benchmark.md`. No new paraphrases were
   invented for this task.
5. **API overhead**: for every request in both paths, external wall-clock time minus the
   service's own self-reported `meta.latency_ms`.

## Results (N per path, P50/P95/P99, min/max)

| Path | N | Min (ms) | P50 (ms) | P95 (ms) | P99 (ms) | Max (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| Cold (siis_response supplied) | 30 | 137.8 | 209.8 | **286.9** | 310.3 | 310.3 |
| Fast -- exact repeat | 30 | 0.8 | 0.9 | 1.2 | 1.6 | 1.6 |
| Fast -- semantic paraphrase | 28 | 23.7 | 28.8 | 33.8 | 45.1 | 45.1 |
| Fast -- combined | 58 | 0.8 | 1.2 | **32.7** | 33.8 | 45.1 |

**API overhead** (external minus internal, i.e. HTTP/serialization cost on top of the
service's own reported time): cold path P50 1.7 ms / P95 2.0 ms; fast path P50 1.1 ms / P95
1.9 ms. Negligible relative to processing time in both paths.

## Cache hit rate

**98.28% (57/58)** of fast-path requests engaged the semantic cache (`meta.cache_hit == True`)
rather than falling back. The one exception is `"ink spots and coloured lines are showing on
the panel"` (from `paraphrases_holdout.json`), which returns `no_match` -- this is not a new
finding: it is the same, already-documented miss reported in
`docs/siis_paraphrase_baseline_benchmark.md` (1 of 14 misses on that held-out set).

**This is a different measurement from retrieval accuracy.** "Cache hit rate" here means "did
the fast path engage instead of falling back to cold-rebuild or no_match" -- relevant to
*latency*, since a miss is slower (falls through to a cold rebuild or an empty result) than a
hit, correct or not. It does **not** mean "retrieved the semantically correct plan"; that
question is answered separately and already in detail by
`docs/siis_paraphrase_baseline_benchmark.md` (Recall@1 87.3% test / 75.0% val) and
`docs/cross_domain_generalization.md` (98.75% combined). Nothing here changes those figures.

## Target validation

- **Fast-Path Cache P95 < 300 ms: MET.** 32.7 ms combined (33.8 ms on paraphrases alone,
  the harder of the two fast-path cases) -- roughly 9x margin under target.
- **Cold-path P95 <= ~8 s: MET.** 286.9 ms -- roughly 28x margin under target. The 8-second
  budget assumes a heavier cold-path architecture (e.g. an LLM call) than this system's
  rules-only pipeline actually uses; the large margin reflects that, not a measurement error.

## Caveats

- Not measured inside an actual Docker container (see the top of this document).
- Startup time (16.8 s here) reflects an embedding model already present in the local
  Hugging Face cache from earlier work in this session; a genuinely cold machine or a freshly
  built image's first container start would be similar, since the Dockerfile bakes the model
  into the image at *build* time specifically to avoid paying this cost at container
  *startup* beyond loading it into memory.
- Single machine, single run, no concurrent load. These are single-threaded, single-client
  measurements, not a load test.
- The 17-row cold-path cycle and the paraphrase fixtures are the same small, already-audited
  official and synthetic data used throughout this project; see the limitations sections of
  the earlier reports for their known scope.

## Environment

Measured on: Windows-11-10.0.26200-SP0, Python 3.13.3, AMD64 (AuthenticAMD), CPU-only (no
GPU used by the embedding model). Raw result JSON: `data/processed/latency_benchmark_result.json`
(git-ignored, regenerate with `python scripts/benchmark_latency.py`).

## Known limitations (carried over, unchanged by this task)

- The "Optimize now" / "Restart on schedule" parent-menu-match family remains deliberately
  unfixed (`app/services/key_matcher.py`'s `find()` docstring).
- The "camera won't open" vs. "camera crashes" hard negative remains a known, documented,
  ambiguous-language case (`docs/camera_hard_negative_analysis.md`).
- The synthetic cross-domain fixture (`tests/fixtures/cross_domain_articles.json`) is not
  representative production data for Battery/Camera/Performance.
