# Smart Guided Troubleshooting Engine

Samsung PRISM hackathon submission, Theme 2 ("Smart Guided Troubleshooting Engine").

## Problem

A user describes a Galaxy problem in their own vague words ("touch is laggy", "screen is
cracked") instead of the exact wording of a support article. The engine has to turn that into
an ordered, step-by-step plan built only from verified content -- with no hallucinated steps,
no invented deeplinks, and no fabricated Settings screens -- fast enough to feel instant on a
repeat/paraphrased question, and correct enough to trust on a first-time one.

## Solution

A pure rules-based (no LLM, no generative model anywhere in this build) pipeline that:
1. Parses the official SIIS troubleshooting text into ordered, imperative steps.
2. Maps each step's tapped UI label to the *exact* verified deeplink catalog entry for it
   (never a fuzzy or invented one).
3. Orders steps auto -> manual -> critical, and marks disruptive steps so they can never carry
   an actionable deeplink.
4. Validates every plan against the official schema (zero URL leaks, catalog membership, word
   counts, ordering) before it is ever cached or returned.
5. Caches every validated plan under its own query plus generated paraphrases, so a
   semantically similar future question ("touch is unresponsive and taps land late") gets the
   same verified plan back in single-digit milliseconds instead of being rebuilt.

## Architecture / pipeline

```
Query
  |
  v
Query Enrichment        app/services/variations.py (normalize_query, generate_variations)
  |                      -- normalises colloquial text; generates the 8-10 official
  |                      query_variations and the paraphrase keys the cache is built from
  v
Structure Extraction    app/services/siis_parser.py (parse_sections, extract_steps,
  |                      embedded_title) -- turns raw SIIS-style article text into headed
  |                      sections of imperative steps (cold path only)
  v
Retrieval               app/services/plan_cache.py (PlanCache) + app/services/relevance.py
  |                      -- on a query alone: cosine-similarity lookup against cached plan
  |                      keys (this is the Fast-Path Semantic Cache, below). On a cold build
  |                      with siis_response supplied: the lexical relevance() gate decides
  |                      whether the supplied article actually fits the query at all.
  v
Deeplink Mapping        app/services/key_matcher.py (KeyIndex.find) -- exact-label match of
  |                      the tapped UI text against data/original/deeplinks.json's
  |                      validation.key; never a fuzzy/BM25/dense match at this stage, and
  |                      never on the masked URI string itself
  v
Action Ordering         app/services/action_ordering.py -- auto, then manual, then critical
  v
Validation Firewall     app/services/plan_validator.py -- schema conformance, description
  |                      word counts, zero raw-URL leaks, deeplink catalog membership,
  |                      manual/critical actions never carry an actionable deeplink, ordering
  v
Fast-Path Semantic Cache   app/services/plan_cache.py (persisted) -- only a plan that passed
  |                          validation above ever enters the cache; a future request keyed to
  |                          the same query, one of its paraphrases, or an "action name + first
  |                          step" key is served straight from here, skipping steps 2-6 entirely
  v
REST API / Frontend     app/api/routes.py -> app/main.py (FastAPI) ; frontend/ (Vite + React)
```

**Fast-path bypass, stated explicitly:** on a cache hit, the *live* request never re-runs
Structure Extraction / Deeplink Mapping / Ordering / Validation -- it jumps straight from Query
Enrichment to the cache and returns the already-validated plan. Those middle stages only run
once, offline, when a plan is first built (either at cache-warm-up time from the 20 official
rows, or the first time a truly new `siis_response` is supplied). This is what makes the
Fast-Path meet its latency target: it is a cache lookup, not a re-run of the pipeline.

**On "Retrieval":** the PDF's stage list names "BM25 + Dense Retrieval" as part of deeplink
mapping. This build does not use that architecture for deeplink mapping -- it uses exact-label
matching instead, because a real, measured trial of dense/hybrid retrieval for that specific
job scored an unrelated screen ("One-handed mode") almost as confidently as the correct one
("Restart in Safe Mode") on real catalog data; see the ablation table in `metrics.md`. Dense
embedding retrieval *is* used, for the Fast-Path Semantic Cache's query-to-plan lookup, which is
a different job (matching a paraphrased *query* to a previously validated *plan*, not matching a
tapped UI label to a deeplink). The rejected BM25/dense/hybrid deeplink-mapping experiment is
still in the repo, tested, for this ablation transparency (`app/services/bm25_retriever.py`,
`dense_retriever.py`, `hybrid_retriever.py`, `deeplink_mapper.py`, `screen_resolver.py`) -- it is
not part of the live request path (`app/services/troubleshooting_service.py` never imports it).

## Output schema

`POST /v1/troubleshoot` returns (see `app/models/official_schema.py`, a verbatim copy of the
participant kit's `schema.py`, and `DATA_MODEL.md`):

```json
{
  "query": "...",
  "query_variations": ["... 8 to 10 generated paraphrases ..."],
  "response": {
    "contexts": [
      {
        "goal": "...", "title": "...", "score": 0.0,
        "actions": [
          {
            "actionName": "...", "description": "...", "category": "auto|manual|critical",
            "stepGroups": [
              {
                "steps": ["..."],
                "actionableDeeplink": { "deeplink": "...", "message": "...", "description": "...", "originalType": "..." } ,
                "validationDeeplink": { "deeplink": "...", "key": "..." }
              }
            ]
          }
        ]
      }
    ]
  },
  "meta": { "latency_ms": 0, "cache_hit": true, "model": "rules-v1", "cost_usd": 0.0, "fallback": "no_match | no_siis_context (optional)" }
}
```

`actionableDeeplink`/`validationDeeplink` are `null` whenever no verified catalog entry exists
for that step (always true for `manual`/`critical` actions -- enforced by the validation
firewall, not just convention). `contexts: []` with `meta.fallback` set is the correct, honest
answer when nothing relevant is cached -- never a fabricated plan.

## Fast-Path semantic cache

Every validated plan is stored (`data/processed/plan_cache.json`, rebuilt deterministically from
`data/original/` by `scripts/build_plans.py`, git-ignored) under several lookup keys: the
original query, its generated paraphrases, and one "action name + first step" key per action. A
new request is embedded (`sentence-transformers/all-mpnet-base-v2` by default; swappable via
`EMBEDDING_MODEL`, see `app/config.py`) and compared by cosine similarity against every stored
key; a match above `SIMILARITY_THRESHOLD` (default 0.45) returns that cached, already-validated
plan directly -- this is the mechanism that meets the sub-300ms Fast-Path latency target and the
80% semantic-paraphrase-hit-rate target (see Benchmark results below). Nothing enters or leaves
this cache without having passed the validation firewall first.

## REST API

    GET  /health                 200 {"status":"ok"} once the service has finished loading, else 503 {"status":"initializing"}
    POST /v1/troubleshoot        {"query": "...", "siis_response": "<optional raw SIIS-style text>"}

Supplying `siis_response` forces a cold build from that exact text (skipping the cache lookup
for retrieval, though the result is still cached afterward) -- this is how the engine is
demonstrated on Battery/Camera/Performance content, which the 20 official sample rows do not
cover (see "Beyond the Display domain" below).

## Frontend demo

`frontend/` (Vite + React): a chat thread (type a complaint, get a plan back), a `PlanCard` per
response showing goal/title/score and every action grouped by auto/manual/critical with a
disruptive-action warning banner, a phone simulator that renders the real target Settings screen
when you press **Open** on an auto action's deeplink, and a collapsible "paste raw
troubleshooting text (cold path demo)" panel wired directly to the `siis_response` field above
(with a one-click, verbatim-fixture-backed Battery example) so the cold path can be demonstrated
from the browser UI itself, not only via `curl`/Postman.

## Run it

One-time setup (Python 3.11+ and Node 20):

    py -3.11 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    cd frontend; npm install; cd ..

Then, from the project root:

    .\scripts\dev.ps1

This starts the API (port 8000) and the chat UI (port 5173, or the next free port) and opens the
browser. The first start downloads the embedding model (about 420 MB) and takes a minute; later
starts take about 20 seconds.

Try: "touch is laggy and my taps register late", "my phone screen is cracked", "screen stays
black and the phone will not turn on". Press **Open** on an auto step and the phone simulator
shows the Settings screen it points to. Expand "paste raw troubleshooting text (cold path
demo)" and click "Fill in the Battery example" to see a domain the official sample data never
covers, built live through the full cold pipeline.

## Testing

    pytest                                       # backend: 391 passed, 3 skipped (last run)
    python scripts/benchmark.py                  # official-data metrics -> metrics.md
    python scripts/benchmark_paraphrase_dataset.py  # corrected paraphrase dataset -> docs/siis_paraphrase_baseline_benchmark.md
    python scripts/benchmark_cross_domain.py     # Battery/Camera/Performance fixture -> docs/cross_domain_generalization.md
    python scripts/benchmark_latency.py          # real REST latency against a live process -> docs/docker_latency_benchmark.md
    cd frontend && npm test -- --run && npm run build     # frontend tests and production build

The 3 skipped backend tests are placeholders for features explicitly out of scope for this
build (see their own skip reasons in-repo) -- not silently-disabled coverage of shipped code.

## Benchmark results

All numbers below are **real, measured values already produced in this repository** -- nothing
here is estimated or extrapolated. Full detail and methodology in the linked docs.

| Metric | Value | Scope | Source |
| --- | --- | --- | --- |
| Schema-valid output / deeplink catalog validity / URL leaks | 100% / 100% / 0 | 17 plans from the 20 official rows | `metrics.md` |
| Fast-Path cache, exact repeat, P95 | 1.2 ms | **local process** (not Docker) | `docs/docker_latency_benchmark.md` |
| Fast-Path cache, unseen paraphrase, P95 | 33.8 ms | **local process** (not Docker) | `docs/docker_latency_benchmark.md` |
| Cold path (siis_response supplied), P95 | 286.9 ms | **local process** (not Docker) | `docs/docker_latency_benchmark.md` |
| Semantic cache **hit rate** (engaged fast path vs. fell back) | 98.28% (57/58) | local process, official + held-out paraphrases | `docs/docker_latency_benchmark.md` |
| Semantic cache **hit correctness** (unseen paraphrase -> correct plan) | 89.3% (25/28) | official held-out paraphrase sets | `metrics.md` |
| Retrieval accuracy, Recall@1 | 87.3% (test) / 75.0% (val) | official-data paraphrase dataset, no fine-tuning | `docs/siis_paraphrase_baseline_benchmark.md` |
| Retrieval accuracy, Recall@1 | 98.75% combined | **SYNTHETIC** Battery/Camera/Performance fixture (16 articles, 80 paraphrases) -- not production-scale evidence | `docs/cross_domain_generalization.md` |

"Hit rate" (did the fast path engage at all) and "hit correctness" (was the plan it returned the
right one) are different measurements, kept separate above on purpose -- a high hit rate with a
lower correctness would be a bug worth knowing about, and vice versa.

## Docker status

A `Dockerfile`, `.dockerignore`, and `docker-compose.yml` exist and bake the embedding model and
plan cache in at build time (see `docs/docker_latency_benchmark.md` for the full design). **Docker
itself has not been build/run-verified in this environment** (`docker` is not installed here,
confirmed repeatedly, most recently during this submission audit). The latency numbers quoted
above and in that document are real, measured **local-process** numbers -- the same code,
dependencies, and startup path the Dockerfile uses, run directly -- not container measurements.
Do not present the numbers above as Docker-container performance.

## Known limitations

- **"Optimize now" / "Restart on schedule" parent-menu-match family**: these two catalog keys
  can resolve to the parent "Battery" screen instead of correctly giving up. A general fix was
  implemented and tested, but regressed a real official row (`row_21`'s "Navigation bar" ->
  "Buttons" case) and was reverted rather than shipped. Documented in
  `app/services/key_matcher.py`'s `find()` docstring, `docs/cross_domain_generalization.md`,
  `docs/docker_latency_benchmark.md`.
- **Camera hard-negative ambiguity**: "camera won't open" and "camera crashes" are close enough
  in embedding space that phrasing alone can occasionally pull the wrong one; a full
  per-key score breakdown (including a supplementary BM25/hybrid comparison, not shipped) is in
  `docs/camera_hard_negative_analysis.md`.
- **Synthetic cross-domain fixture**: Battery/Camera/Performance generalization is checked
  against a 16-article, author-written fixture (`tests/fixtures/cross_domain_articles.json`),
  not real Samsung customer data or real SIIS content at production scale. It demonstrates the
  pipeline handles those domains correctly; it does not demonstrate production-scale accuracy
  there. Detail in `docs/cross_domain_generalization.md`.
- **Docker runtime verification pending**: see "Docker status" above -- build/run success and
  container latency remain unverified in this environment.
- The lexical relevance gate occasionally refuses a genuinely aligned query (official `row_17`)
  and occasionally accepts a loosely-related one (rows 7, 12) -- it matches on shared ordinary
  words, not meaning; see `metrics.md` section 6 and `docs/siis_alignment_audit.md`.

## Your own model later

See `docs/training-integration.md`: export training pairs, fine-tune, evaluate with
`--embedding-model`, then set `EMBEDDING_MODEL`. No fine-tuning has been performed in this
build; the embedding model is the off-the-shelf `sentence-transformers/all-mpnet-base-v2`.

## Beyond the Display domain

The 20 official sample rows are all Display complaints, even though the PDF describes four
device domains (Battery, Display, Camera, Performance). `docs/domain-coverage.md` and
`docs/cross_domain_generalization.md` explain how the other three are tested (a clearly
labeled synthetic fixture, not additional official coverage) and the real bugs that testing
found and fixed.

## Demo and submission

`docs/demo_readiness.md` has the verified strongest demo queries (with exact expected output),
a 2-3 minute demo script, and an architecture diagram description. `docs/submission_checklist.md`
is the concise final go/no-go checklist. Read both before presenting or submitting.

## Layout

    app/services/   siis_parser, key_matcher, plan_builder, plan_cache, troubleshooting_service,
                    relevance, action_ordering, plan_validator, variations, catalog (all live);
                    bm25_retriever/dense_retriever/hybrid_retriever/deeplink_mapper/
                    screen_resolver/embedding_service are the tested-but-rejected retrieval
                    experiment referenced in metrics.md's ablation table -- not on the live path
    app/retrieval/  embeddings (hash fallback), st_embedder (sentence-transformers, local models)
    frontend/       Vite + React chat, plan card, phone simulator, cold-path demo panel
    scripts/        dev.ps1, build_plans.py, build_paraphrase_dataset.py, export_training_pairs.py,
                    benchmark.py, benchmark_paraphrase_dataset.py, benchmark_cross_domain.py,
                    benchmark_latency.py
    docs/           design spec, implementation plan, training guide, domain-coverage,
                    siis_alignment_audit / siis_dataset_quality_report / siis_hard_negatives /
                    siis_paraphrase_baseline_benchmark, cross_domain_generalization /
                    cross_domain_hard_negatives, camera_hard_negative_analysis,
                    docker_latency_benchmark, demo_readiness, submission_checklist
    tests/fixtures/ paraphrases.json / paraphrases_holdout.json (Display), domain_articles.json /
                    cross_domain_articles.json (synthetic Battery/Camera/Performance),
                    camera_hard_negative.json
