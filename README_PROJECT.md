# Smart Guided Troubleshooting Engine

Samsung PRISM hackathon submission, Theme 2 ("Smart Guided Troubleshooting Engine").

## Problem

A user describes a device problem in their own vague words ("touch is laggy", "screen is
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
   same verified plan back well inside the 300 ms fast-path target instead of being rebuilt.

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

## How the evaluation criteria are met

- **Deterministic execution.** The request path has no randomness and no generative model:
  parsing, label matching, ordering and validation are rules, paraphrases come from fixed
  templates, and cache lookup is a similarity ranking in which equal scores resolve to the key
  stored first. The same input returns the same plan
  (`tests/test_troubleshooting_service.py::test_identical_queries_give_identical_plans`,
  `tests/test_cross_domain_generalization.py::test_the_same_query_produces_the_same_result_repeatedly`).
- **Exact target-screen mapping, exact catalog deeplinks.** A step maps to a catalog entry only
  when the UI label it taps equals that entry's `validation.key`; the URI is then copied
  verbatim. When no entry matches, the step gets the catalog's own placeholder or no deeplink.
- **One Action = One Screen.** Each step group carries at most one actionable deeplink, and
  adjacent actions that resolve to the same screen are folded into one action
  (`_merge_same_screen` in `app/services/plan_builder.py`).
- **Action hierarchy.** Actions are ordered auto, then manual, then critical.
- **Programmatic validation.** `app/services/plan_validator.py` checks every plan in code
  (schema, goal/title/description rules, no URLs, catalog membership, no deeplink on
  manual/critical actions, ordering) before it is cached or returned; none of these rules
  depends on prompt wording, because there is no prompt.
- **Operational metadata.** Every response carries `meta.latency_ms`, `meta.cache_hit`,
  `meta.model` and `meta.cost_usd`.
- **Cost and inference.** The request path performs no external model inference and calls no
  provider API. The only model is the sentence-embedding model used for cache lookup, which
  runs locally. There are therefore no prompt or completion tokens to report, and
  `cost_usd` is 0.0 because no per-request API charge exists; the compute cost of hosting the
  service has not been measured.

## Fast-Path semantic cache

Every validated plan is stored (`data/processed/plan_cache.json`, rebuilt deterministically from
`data/original/` by `scripts/build_plans.py`, git-ignored) under several lookup keys: the
original query, its generated paraphrases, and one "action name + first step" key per action. A
new request is embedded (`sentence-transformers/all-mpnet-base-v2` by default; swappable via
`EMBEDDING_MODEL`, see `app/config.py`) and compared by cosine similarity against every stored
key. Two kinds of key count for less (their similarity is multiplied by 0.85,
`AUXILIARY_KEY_WEIGHT` in `app/services/plan_cache.py`): paraphrases that wrap the complaint in
wording shared by every plan ("my phone is acting up, ...") and keys for critical actions
(restart, safe mode, reset), which close most plans whatever the complaint was. Action keys
describe a remedy, not the complaint, so once any plan's query, paraphrase or topic keys match
at 0.60 or above (`INTENT_CONFIDENCE`), action keys are capped just below that match and cannot
outrank it. A weighted match
at or above `SIMILARITY_THRESHOLD` (default 0.48) returns that cached, already-validated
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

    pytest                                       # backend: 494 passed, 7 skipped (last run)
    python scripts/benchmark.py                  # official-data metrics -> metrics.md
    python scripts/benchmark_paraphrase_dataset.py  # corrected paraphrase dataset -> docs/siis_paraphrase_baseline_benchmark.md
    python scripts/benchmark_cross_domain.py     # Battery/Camera/Performance fixture -> docs/cross_domain_generalization.md
    python scripts/benchmark_latency.py          # real REST latency against a live process -> docs/docker_latency_benchmark.md
    cd frontend && npm test -- --run && npm run build     # frontend tests and production build

Of the 7 skipped backend tests, 3 are placeholders for features explicitly out of scope for this
build and 4 compare `data/original/` with a `student_kit` folder next to the repository, which
was not present for that run (see their own skip reasons in-repo) -- not silently-disabled
coverage of shipped code.

## Benchmark results

All numbers below are **real, measured values already produced in this repository** -- nothing
here is estimated or extrapolated. Full detail and methodology in the linked docs.

| Metric | Value | Scope | Source |
| --- | --- | --- | --- |
| Schema-valid output / deeplink catalog validity / URL leaks | 100% / 100% / 0 | 18 plans from the 20 official rows | `metrics.md` |
| Fast-Path cache, exact repeat, P95 | 1.2 ms | **local process** (not Docker) | `docs/docker_latency_benchmark.md` |
| Fast-Path cache, unseen paraphrase, P95 | 33.8 ms | **local process** (not Docker) | `docs/docker_latency_benchmark.md` |
| Cold path (siis_response supplied), P95 | 286.9 ms | **local process** (not Docker) | `docs/docker_latency_benchmark.md` |
| Semantic cache **hit rate** (engaged fast path vs. fell back) | 98.28% (57/58) | local process, official + held-out paraphrases | `docs/docker_latency_benchmark.md` |
| Fast-Path cache, unseen paraphrase, P95 (current configuration) | 80 - 104 ms | **local machine, in-process, three single runs** (not Docker, not over HTTP) | `metrics.md` |
| Cold path, P95 (current configuration) | 1062 - 1528 ms | **local machine, in-process, three single runs** (not Docker, not over HTTP) | `metrics.md` |
| Semantic cache **hit correctness** (unseen paraphrase -> correct plan) | 89.3% (25/28) | official held-out paraphrase sets | `metrics.md` |
| Ranking on those 28 paraphrases: Recall@1 / Recall@3 / Recall@5 / MRR | 0.893 / 0.964 / 0.964 / 0.927 | official held-out paraphrase sets | `metrics.md` |
| Unrelated queries wrongly answered | 0 of 12 | fixture negatives | `metrics.md` |
| Out-of-scope device complaints wrongly answered | 6 of 49 / 4 of 38 | probe set used while tuning / second probe set scored once afterwards | `metrics.md` |
| Retrieval accuracy, Recall@1 | 89.1% (test) / 78.1% (val) | official-data paraphrase dataset, no fine-tuning | `docs/siis_paraphrase_baseline_benchmark.md` |
| Retrieval accuracy, Recall@1 / Recall@3 / Recall@5 / MRR | 100% (80/80) / 1.0 / 1.0 / 1.0 combined, deeplinks 16/16, 0 pipeline failures | **SYNTHETIC** Battery/Camera/Performance fixture (16 articles, 80 paraphrases) -- not production-scale evidence | `docs/cross_domain_generalization.md` |

The four `docs/docker_latency_benchmark.md` rows were measured on the previous version of the
official data, with the previous cache configuration (threshold 0.45, all keys at equal weight),
on different hardware, and have not been re-run; the other rows reflect the current reference
set and configuration. The two "current configuration" latency rows come from a slower, busy
development machine and are not comparable with the `docs/docker_latency_benchmark.md` rows.

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
- **Camera hard negative, corrected but close**: "camera won't open" and "camera crashes" sit
  close together in embedding space. The one query that used to retrieve the crash plan (its
  remedy step outscored both plans' complaint wording) now retrieves the right plan, because
  action keys can no longer outrank a confident intent match; all 80 cross-domain paraphrases
  rank correctly. The two plans' intent scores for that query are only 0.007 apart (0.6359
  against 0.6289), so a different embedding model could move it. Per-key breakdown in
  `docs/camera_hard_negative_analysis.md`.
- **Out-of-scope complaints can still borrow a plan**: on complaints about features the official
  rows do not cover, 6 of 49 (and 4 of 38 on a second set) were answered instead of falling back.
  Most are Bluetooth complaints matching the screen-mirroring plan, whose steps mention
  "Bluetooth and other device settings". Detail in `metrics.md` sections 4 and 6; the refused
  cases are locked in by `tests/test_retrieval_hard_negatives.py`.
- **Synthetic cross-domain fixture**: Battery/Camera/Performance generalization is checked
  against a 16-article, author-written fixture (`tests/fixtures/cross_domain_articles.json`),
  not real Samsung customer data or real SIIS content at production scale. It demonstrates the
  pipeline handles those domains correctly; it does not demonstrate production-scale accuracy
  there. Detail in `docs/cross_domain_generalization.md`.
- **Docker runtime verification pending**: see "Docker status" above -- build/run success and
  container latency remain unverified in this environment.
- The lexical relevance gate can refuse a genuinely aligned query (official `row_17` was refused
  under the earlier wording of the official data) and occasionally accepts a loosely-related one
  (rows 7, 12) -- it matches on shared ordinary words, not meaning. Words common to most of the
  official articles (vendor and product-family names) are not counted as a match; see
  `app/services/relevance.py`, `metrics.md` section 6 and `docs/siis_alignment_audit.md`.

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
