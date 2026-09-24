# Smart Guided Troubleshooting Engine: Chat + Simulator Design

Date: 2026-09-21
Status: Implemented (see plan amendment)
Source of truth: `student_kit/` (official PDF contract, `schema.py`, `deeplinks.json`, `siis_responses.json`, `input.txt`, `sample_output.json`). Where this spec and the PDF disagree, the PDF wins.

## 1. Goal and scope

Build a web chat where a user types a vague Galaxy complaint and receives an ordered, validated troubleshooting plan. Each auto step has an **Open** button that "opens" its deeplink in an on-page Galaxy Settings simulator.

In scope:
- Rules-only backend engine implementing the official API contract (no LLM).
- Vite + React chat frontend with a phone simulator panel.

Out of scope (separate spec, later): fine-tuning the embedding model. This spec only guarantees the seam: retrieval and embedding sit behind one interface (`Embedder`) so a fine-tuned model is a config swap.

Approach: extend the existing `smartSolveTroubleGuide` skeleton (aligned to the official spec), not a rewrite. Existing retriever, cache, and pipeline modules are audited first; anything written without the official spec is corrected or replaced.

## 2. Backend

### 2.1 API (per PDF section 5)
- `POST /v1/troubleshoot` with body `{"query": str, "siis_response": str | null}`.
- `GET /health` returns 200 `{"status": "ok"}` only once cache, embedder, and indexes are initialised.
- The skeleton's `/api/v1/troubleshoot` is moved to `/v1/troubleshoot`.
- Response body is pure JSON (no markdown fences or preamble), shaped as in PDF Appendix B:
  `{"query", "query_variations": [8-10], "response": ContextDeeplinkResponse, "meta": {"latency_ms", "cache_hit", "model", "cost_usd", "fallback"?}}`.
- `model` is `"rules-v1"` and `cost_usd` is `0.0` until an LLM is introduced.

### 2.2 Offline warm-up (`scripts/build_plans.py`)
For each usable SIIS document, run the cold pipeline once and write validated plans to a persistent cache file.

1. **Query enrichment**: normalise colloquial text to a canonical query; generate 8-10 paraphrases (formal, casual, keyword-only, frustrated, typo-inclusive) using deterministic templates and synonym tables. The canonical query plus paraphrases form the semantic cache key set.
2. **Structure extraction (rules)**: parse SIIS `content` by its `##`/`###` headings and step lines into Goal, Actions, and StepGroups. Steps are imperative, one interaction each, with URLs, markdown links, and "provided links" phrasing stripped. Nothing is added that is not in the SIIS text.
3. **Deeplink mapping**: for each step group, match the last UI label the steps tap ("Wi-Fi", "Navigation bar") exactly against the catalog's `validation.key`, which is the literal Settings label. When several entries share a label, choose by intent: enable, disable, or the plain open entry. The URI string is never a match feature. The chosen URI is copied verbatim. (The skeleton's hybrid BM25 + dense retriever was tried first and rejected for this job: its min-max normalisation gives the top hit a score near 1.0 even for unrelated screens, e.g. "Restart in Safe Mode" scored 1.0 against "One-handed mode".) If the step opens a Settings screen with no catalog match, use `bixby://dummy_positive` with a self-written 5-7 word `description` and `message` naming the screen. Physical or service steps get no deeplink.
4. **Action ordering**: `auto` (non-invasive settings) first, then `manual`, then `critical` (factory reset, safe mode, firmware update, restart). One Action equals one screen or feature; steps on the same screen are grouped into one Action.
5. **Validation, then cache write.** Only plans that pass every validator in 2.4 are written.

### 2.3 Online path
1. Normalise the incoming query.
2. Semantic lookup against the cache (dense similarity over stored paraphrases, with an exact-key fast path).
3. Hit with similarity at or above the threshold: return the cached plan (no model call).
4. Miss with `siis_response` supplied: run the cold pipeline (2.2 steps 1-5), cache, return.
5. Miss with no `siis_response`: return `contexts: []` with `meta.fallback = "no_match"`. If the cache is empty for that domain, use `"no_siis_context"`.

Lookup is cosine similarity between the query embedding and every stored key: the original query, its paraphrases, and one "action name + first step" key per action. The default model is `sentence-transformers/all-mpnet-base-v2` with threshold 0.45; both are configuration (`EMBEDDING_MODEL`, `SIMILARITY_THRESHOLD`), so a model trained locally is a drop-in. The dependency-free hashed embedding stays as a fast test fallback (`EMBEDDING_MODEL=hash`) but reaches only 8 of 14 on the first held-out set. Measured with the default: 13 of 14 and 12 of 14 on two independent held-out sets (25 of 28, 89%), 0 of 12 unrelated queries answered, hit P95 31 ms, cold-build P95 253 ms. The second set was written before any model or scoring choice was made, and the configuration was chosen using the first set only.

### 2.4 Validators (programmatic, application layer)
Applied to every plan entering or leaving the cache:
- Pydantic conformance to the official `schema.py` (copied unmodified into `app/models/`).
- `goal` matches `Follow these steps to perform this <Topic> Troubleshooting` or `... Configuration`.
- `title` is 2-3 words, sentence case. `score` is in [0, 1].
- `actionName` is Title Case. `description` is 5-7 words and starts with "It will".
- `steps` are imperative, one interaction each, with no URLs (`http`, `https`, `www.`, markdown links).
- `category` is one of auto, manual, critical. `manual` actions have `actionableDeeplink: null`. `critical` actions come last.
- Every `actionableDeeplink.deeplink` exists verbatim in `deeplinks.json`, and its description and message are consistent with the catalog entry (or `dummy_positive` with self-written text).
- 8-10 `query_variations`.
- A plan that fails any rule is rejected and never cached. The warm-up script reports each rejection with its errors.

### 2.5 Determinism
Identical or semantically identical queries return byte-identical plans: no randomness, stable sort keys, plans served only from cache.

## 3. Frontend (Vite + React, `frontend/`)

- **Chat thread**: user bubbles and bot replies. A reply is a plan card: goal heading, then ordered action cards with numbered steps. Badges: auto, manual, critical. Critical actions carry a "back up your data first" notice. Manual actions show no Open button.
- **Open button**: fires the action's `actionableDeeplink` into the **phone simulator** panel. The simulator renders a mock Galaxy Settings screen titled from the deeplink's `message`/`description`. For `onURL`/`offURL` deeplinks it shows a toggle and updates the state; a `validationDeeplink` drives a "verified" tick. The `bixby://` URI is never navigated to in the browser.
- **Meta strip**: latency, cache hit, model, and cost from `meta`.
- **States**: loading, network error, and `no_match` ("I couldn't find a verified fix for that. Try describing the screen or symptom.").
- The frontend calls only `POST /v1/troubleshoot` and holds no engine logic.

## 4. Data caveats (design responses)

| Caveat | Response |
| --- | --- |
| Some SIIS rows do not match their query (row 8: screen mirroring for a small-screen issue; row 20: rotation for a distorted screen; rows 7 and 12: multi window for unrelated symptoms) | Best-effort lexical relevance gate (`relevance.py`). Measured on the 20 sample rows: rows 8 and 20 are refused; rows 7 and 12 still produce plans because they share ordinary words with their article. Separating those needs semantic similarity, so it is deferred to the embedding fine-tune; the gate sits behind one function to make that swap trivial. |
| Rows 6 and 18 are missing from `siis_responses.json` | No plan; queries fall to `no_match`. |
| Multi-intent queries (row 19) | Match the dominant intent; document multi-intent as a known limitation in `metrics.md`. |
| The PDF's own `sample_output.json` has action descriptions of 9 and 11 words, against the written 5-7 word rule | Follow the written rule; validate the sample against the pydantic schema only, not the rule validators. |
| Many SIIS rows are duplicates of the same article | Build one plan per unique article; map all its queries to it. |
| Row 3, 11, 17 SIIS text contains a garbled, run-together tail | Truncate the document at the first garbled section; extract only from the clean leading portion. |

## 5. Testing and verification

- pytest per stage: enrichment, extraction, mapping, ordering, each validator, cache, API.
- Golden test: run the pipeline on the sample input and compare structure against `sample_output.json`.
- Property checks over all cached plans: zero URLs, all URIs in the catalog, `manual` has no deeplink, critical last.
- `scripts/benchmark.py`: at least 30 requests per path; P50/P95 for exact hit, paraphrase hit, and cold; paraphrase hit rate on held-out paraphrases. Results go into `metrics.md` following PDF Appendix C.
- Frontend: component tests for the plan card and simulator; one end-to-end browser run (type a complaint, see a plan, press Open, see the simulator update).

Targets from the PDF: schema-valid 100%, URL leaks 0, catalog validity 100%, hit P95 at or below 300 ms, cold P95 at or below 8 s, paraphrase hit rate at or above 80%.

## 6. Build order

1. Audit and align the skeleton to the official schema; add the official data to `data/original/` unmodified.
2. Validators, then extraction, mapping, ordering, warm-up script, cache.
3. Online path and API.
4. Frontend chat and simulator.
5. Benchmarks and `metrics.md`.

## 7. Training seam (for the later embedding spec)

`Embedder` interface: `encode(list[str]) -> ndarray`. The default is a pretrained sentence-embedding model. Warm-up caches paraphrase vectors keyed by embedder id, so swapping in a fine-tuned model triggers a re-index only. Training data can come from the generated `query_variations` paired with their plans and deeplink descriptions.
