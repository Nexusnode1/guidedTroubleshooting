# Architecture

## Pipeline stages

```
Query
  -> Query Enrichment          (app/services/variations.py)
  -> Structure Extraction      (app/services/siis_parser.py)          [cold build only]
  -> Retrieval                 (app/services/plan_cache.py, relevance.py)
  -> Deeplink Mapping          (app/services/key_matcher.py)          [cold build only]
  -> Action Ordering           (app/services/action_ordering.py)      [cold build only]
  -> Validation Firewall       (app/services/plan_validator.py)       [cold build only]
  -> Fast-Path Semantic Cache  (app/services/plan_cache.py, persisted)
  -> REST API / Frontend       (app/api/routes.py -> app/main.py; frontend/)
```

**Two runtime paths through the same stage list, not two different pipelines:**

- **Cache hit** (the common case for a request in production): Query Enrichment normalises the
  text, Retrieval's cosine lookup against the persisted cache finds a match above
  `SIMILARITY_THRESHOLD`, and the already-validated plan is returned directly. Structure
  Extraction, Deeplink Mapping, Action Ordering, and the Validation Firewall do **not** run
  again for this request -- they already ran once, whenever that plan was first built. This is
  what makes the Fast-Path meet its latency target.
- **Cold build** (a cache miss, or a request that supplies `siis_response` directly): every
  stage runs in the order above, end to end, and the resulting plan is validated before it is
  both returned and written into the cache for next time.

## "Retrieval", precisely

The PDF's stage list groups "BM25 + Dense Retrieval" under deeplink mapping. This build does
**not** use that architecture for deeplink mapping: `key_matcher.py`'s `KeyIndex.find()` does
exact-label matching of the tapped UI text against `data/original/deeplinks.json`'s
`validation.key`, never a fuzzy/BM25/dense match, and never against the masked URI string
itself. A real trial of dense/hybrid retrieval for that specific job is in the repo
(`app/services/bm25_retriever.py`, `dense_retriever.py`, `hybrid_retriever.py`,
`deeplink_mapper.py`, `screen_resolver.py`, with their own tests) and was rejected: on real
catalog sections, min-max score fusion rated an unrelated screen ("One-handed mode") almost as
confidently as the correct one ("Restart in Safe Mode") -- see the ablation table in
`metrics.md`. None of those modules are imported by `troubleshooting_service.py`, the live
request path.

Dense embedding retrieval *is* used in this build, in the "Retrieval" stage above, for a
different job: matching a paraphrased **query** against previously validated **plans** in the
Fast-Path Semantic Cache. `relevance()` (`app/services/relevance.py`) is a separate, lexical
check used during a *cold build* to decide whether a supplied article actually fits the query
at all -- it is not the cache's dense lookup, and it is the next candidate for a learned
replacement (see `docs/training-integration.md`).

## Cache keys

Every validated plan is stored under: the original query, its generated paraphrases (the
official 8-10 `query_variations`), and one "action name + first step" key per action.

## Swap points

`EMBEDDING_MODEL` and `SIMILARITY_THRESHOLD` (`app/config.py`) select and tune the embedding
model used for both the Fast-Path cache lookup and (if later fine-tuned) any future learned
relevance gate. See `docs/training-integration.md`.
