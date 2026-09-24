# Demo / Submission Readiness

Every query, output, and metric below was run against the real, live `TroubleshootingService`
in this session (not recalled from memory, not estimated). Where a number depends on the
embedding model or timing, it is labeled as a **local measurement** (see
`docs/docker_latency_benchmark.md`); Docker-container latency has not been verified (Docker is
not installed in this environment) and is not claimed here. The synthetic cross-domain fixture
(`tests/fixtures/cross_domain_articles.json`) is author-written test data, not production-scale
Battery/Camera/Performance coverage -- it demonstrates the pipeline handles those domains
correctly, not that it has been validated at production scale there.

## 1. End-to-end demo flow

```
User query (chat input or POST /v1/troubleshoot)
   |
   v
Query Enrichment            app/services/query_enrichment.py (QueryEnricher), used via
                             generate_variations()/normalize_query() -- normalises colloquial
                             text, drives cache-key normalisation and the 8-10 official
                             query_variations
   |
   v
Structure Extraction        app/services/siis_parser.py -- parse_sections/extract_steps turn
                             raw SIIS-style text into headed sections of imperative steps
                             (cold path only; a cache hit skips straight to the cached plan)
   |
   v
[cache hit?] ----yes----> Fast-Path Semantic Cache   app/services/plan_cache.py
   |                       (PlanCache.lookup, cosine similarity over the embedding model) ---+
   no                                                                                        |
   v                                                                                         |
Relevance gate + Deeplink Mapping   app/services/relevance.py (article fit) +                |
                                     app/services/key_matcher.py (KeyIndex.find: exact-label   |
                                     match against data/original/deeplinks.json, never on the |
                                     masked URI string) ------------------------------+       |
   |                                                                                  |       |
   v                                                                                  |       |
Action Ordering              app/services/action_ordering.py -- auto before manual   |       |
                              before critical                                        |       |
   |                                                                                  |       |
   v                                                                                  |       |
Validation Firewall          app/services/plan_validator.py -- schema, word counts,   |       |
                              zero-URL, catalog-membership, ordering                   |       |
   |                                                                                  |       |
   +---------------------------(validated plan cached for next time)-----------------+       |
   |                                                                                          |
   v                                                                                          v
REST API response  {"query", "query_variations", "response": {"contexts": [...]}, "meta": {...}}
                    app/api/routes.py -> app/main.py, PDF Appendix B shape
```

There is no separate BM25 + Dense Retrieval stage in the shipped deeplink-mapping path
(a documented architectural decision -- see the design spec); "Retrieval" in the diagram above
is the semantic cache lookup specifically, which *is* dense-embedding-based.

## 2-3. Strongest demo queries (verified against the live service)

| # | Category | Query | Path |
| --- | --- | --- | --- |
| 1 | Standard/auto action | "Touch responses are laggy" | cache hit |
| 2 | Multi-step flow (auto -> manual -> critical) | "My Samsung tablet screen flashes and then goes completely blank whenever I tap to open an email in Gmail" | cache hit |
| 3 | Manual/critical, no fabricated deeplink | "My Galaxy phone's screen is completely cracked, it's a total crack and I can't use the device." | cache hit |
| 4 | Paraphrase demonstrating semantic matching | "my phone screen is black and will not turn on" | cache hit (semantic, not exact-string; from `tests/fixtures/paraphrases.json`) |
| 5 | Cross-domain, outside Display (Battery) | "My Galaxy phone's battery is draining much faster than it used to." | cold path, `siis_response` supplied from `tests/fixtures/cross_domain_articles.json` |

### 1. "Touch responses are laggy" -- Standard/auto action

- **goal**: `Follow these steps to perform this Touchscreen Issues Troubleshooting`
- **title**: `Touchscreen issues` · **score**: 0.83
- First action -- **category `auto`**, `actionName`: `Factors Affecting Touchscreen Performance`, **description**: `It will help with factors affecting touchscreen`
  - **stepGroups**: `["Try enabling the \"Touch sensitivity\" option.", "Go to Settings.", "Tap Display.", "Tap the switch next to Touch sensitivity."]`
  - **actionableDeeplink**: real catalog entry, `originalType: onURL`, message `Enable Touch sensitivity`
- Two more `auto` actions follow (Navigation bar view, Touch sensitivity off), then 2 `manual`, then 3 `critical` (Restart, Safe Mode, Factory Data Reset) -- **demonstrates the required auto-before-manual-before-critical ordering in a single response**, and that the same underlying setting can be found in both its "enable" and "disable" catalog variant depending on wording.

### 2. Email flashing/blanking -- multi-step flow

- **goal**: `Follow these steps to perform this Email Server Troubleshooting` · **title**: `Email server` · **score**: 0.68
- `auto`: `Verify Your Phone's Internet Connection` -> real Wi-Fi settings deeplink (`View WiFi Settings`)
- `manual` x2: check email on a PC; review account credentials (no deeplink -- correctly so, these are not Settings actions)
- `critical` x2: clear the email app's cache/data; restart in Safe Mode (no deeplink -- physical/destructive sequences never resolve to a catalog entry, by design)
- **Demonstrates**: one query producing a genuinely ordered, multi-action plan spanning all three categories, and that "no deeplink" is a correct, intentional outcome for non-Settings steps, not a failure.

### 3. Cracked screen -- pure manual, no fabricated deeplink

- **goal**: `Follow these steps to perform this Cracked Bleeding Screen Troubleshooting` · **title**: `Cracked bleeding screen` · **score**: 0.83
- Both actions `manual`, `actionableDeeplink: null`: "Samsung Repair Services" (schedule a repair) and "Samsung Authorized Service Centers" (visit one).
- **Demonstrates**: the system does not invent a Settings deeplink for a physical hardware problem -- it correctly says "this needs a person," which is exactly the "no hallucinated steps" requirement in practice, not just in the abstract.

### 4. "my phone screen is black and will not turn on" -- semantic paraphrase match

- Not the original SIIS wording; listed verbatim in `tests/fixtures/paraphrases.json` as a positive example for "Blank black display".
- **Result**: `title: Blank black display`, `score: 0.83`, `cache_hit: true` -- matched via cosine similarity over the sentence-transformer embedding, not an exact string match.
- **Demonstrates**: the Fast-Path semantic cache generalizing beyond the literal training phrasing -- the actual point of the embedding layer.

### 5. Battery drain -- cross-domain, cold path

- Query: `"My Galaxy phone's battery is draining much faster than it used to."`, with `siis_response` supplied from the (clearly labeled synthetic) `battery_drain_fast` article.
- `meta.cache_hit: false` (genuinely took the full cold path: enrichment -> extraction -> relevance -> mapping -> ordering -> validation).
- **goal**: `Follow these steps to perform this Battery Drains Unusually Troubleshooting` · **title**: `Battery drains unusually` · **score**: 1.0
- Three `auto` actions with real, verified deeplinks (`Enable Power saving`, `Enable Adaptive Display`, `View Put unused apps to sleep`), one `critical` (restart, no deeplink).
- **Demonstrates**: the pipeline is not Display-specific -- run live, on a domain the official 20 rows never cover, with the full cold pipeline (not a shortcut), producing a fully schema-valid, catalog-backed plan.

## 4. UI/demo gaps (recommendations; two code changes made so far, see below)

- **Real, fixed**: the app's own default example chip, *"My screen is cracked and
  flickers"*, hit a camera-video-flicker plan whose steps ("disable Super steady mode",
  "adjust shutter speed in Pro Video mode") visibly have nothing to do with a cracked screen --
  the first thing a judge would see if they clicked it. This was a static string in
  `frontend/src/App.tsx`'s `EXAMPLES` array, not core logic; replaced with `"My screen is
  cracked"` (verified: correctly hits `Cracked bleeding screen`).
- **Real, fixed (later task)**: the browser UI had no way to supply `siis_response`, so demo
  query 5 (the cross-domain, cold-path capability) could not be shown through the browser at
  all -- only via `curl`/Postman/the API directly. Fixed with a collapsed "paste raw
  troubleshooting text (cold path demo)" `<details>` panel wired to the existing
  `siis_response` field, plus a "Fill in the Battery example" button that fills in the exact,
  verbatim `battery_drain_fast` fixture text. Verified end-to-end: real backend, real Vite dev
  server, a real (Playwright-driven) headless Chromium browser -- request reaches the backend
  with `siis_response` present, response renders, and the meta strip reads "cold path (raw text
  supplied)" instead of "cache hit"/"cache miss" for that reply. Clearing the textarea and
  sending a normal query afterward correctly omits `siis_response` again (no state leakage).
  `frontend/src/App.tsx`, `api.ts`, `App.test.tsx`, `styles.css`.
- **Recommendation, not implemented**: the meta strip shows latency/cache-hit/model/cost but
  not `query_variations` count or the plan's `score`; surfacing `score` next to the title would
  make the relevance gate's behavior visible to a judge without opening dev tools.
- **Not a gap**: the phone simulator, category badges, and critical-action warning banner are
  all already present and tested (`frontend/src/PlanCard.tsx`, `PhoneSimulator.tsx`).

## 5. Demo script (2-3 minutes)

Walks through all five verified queries from section 2-3, in order: Standard -> Multi-step ->
Manual -> Paraphrase -> Battery cold-path.

**0:00-0:15 -- Setup.** Have `.\scripts\dev.ps1` already running before the demo starts (model
load takes about 15-20 s if the model is already cached locally, longer on a first-ever run --
do not do this live). Open the browser tab.

**0:15-0:40 -- Standard flow (query 1).** Click the *"Touch responses are laggy"* chip.
*Say:* "The user never says 'Settings' or names a screen -- just describes the symptom." Point
out the ordered actions: auto steps first (with real one-tap Open buttons), then manual, then
critical (Factory Data Reset) last, with the warning banner. Click **Open** on the first auto
step; the phone simulator on the right shows the real, catalog-verified Settings screen
(Touch sensitivity, toggled on).

**0:40-1:05 -- Multi-step flow, one query, three categories (query 2).** Type *"My Samsung
tablet screen flashes and then goes completely blank whenever I tap to open an email in
Gmail"*. *Say:* "One complaint, one query -- and the engine still returns a fully ordered plan
spanning all three categories." Point out: one `auto` action with a real Wi-Fi deeplink, two
`manual` steps (check on a PC, review credentials -- correctly no deeplink, these aren't
Settings actions), then two `critical` steps (clear cache, Safe Mode) with the warning banner
and, again, no deeplink.

**1:05-1:25 -- Honest "no deeplink" case (query 3).** Click the *"My screen is cracked"* chip.
*Say:* "For a genuinely physical problem, it doesn't invent a Settings screen -- both steps
route to Samsung Repair Services, with no fabricated deeplink." (Optional, if time: point out
the manual/critical categories never carry an actionable deeplink at all -- that's enforced by
the schema validator, not just convention.)

**1:25-1:50 -- Semantic matching (query 4).** Type *"my phone screen is black and will not turn
on"* by hand (not a chip). *Say:* "This exact sentence isn't the training data -- the semantic
cache is matching it by meaning." Point at the meta strip: cache hit, no LLM call, ~$0.00 cost,
latency in single-digit milliseconds.

**1:50-2:30 -- Beyond Display, cold path (query 5).** Expand "paste raw troubleshooting text
(cold path demo)" in the browser UI, click "Fill in the Battery example" (or, if using a
terminal/Postman window prepared in advance, run the same request against
`POST /v1/troubleshoot` with `siis_response` supplied), and submit. *Say:* "The official sample
data is all about the display, but the same pipeline handles Battery, Camera, and Performance
live, with no retraining -- this is a full cold build, not a cache hit," pointing at the meta
strip's "cold path (raw text supplied)" label (or `meta.cache_hit: false` in Postman) and the
three real, verified deeplinks in the response.

**2:30-2:45 -- Close.** One sentence on validation: "Every one of these responses passed a
firewall that checks schema, word counts, zero URL leaks, and that every deeplink is copied
verbatim from the real catalog -- 391 automated tests confirm this holds across the whole
dataset, not just these five examples."

## 6. Architecture diagram description

See section 1's text diagram; it is the exact content to redraw. Six stages, one linear
path with a documented bypass on cache hit: **Query -> Enrichment -> Structure Extraction ->
(cache hit: jump straight to Cache) / (cache miss: Relevance + Deeplink Mapping -> Action
Ordering -> Validation) -> Cache -> REST API.** No box for "BM25 + Dense Retrieval" as a
deeplink-mapping stage should appear in a diagram of what's actually shipped -- if a reviewer
asks about it, the honest answer is that it was tried and rejected for that purpose, and dense
retrieval is used instead, only for the semantic cache lookup box.

## 7. Submission checklist

| Item | Status | Evidence |
| --- | --- | --- |
| README | Ready | `README_PROJECT.md` updated this task (documentation only) to list every doc/script/fixture added since it was first written |
| Setup commands | Ready | `README_PROJECT.md`'s "Run it" section, verified working this session (`npm test`, `npm run build`, backend `pytest`) |
| Tests | Ready | `pytest -q` -> see Final report below; `npm test -- --run` -> 18/18 passing (includes the cold-path UI tests added after this table was first written) |
| Benchmark metrics | Ready, clearly scoped | `metrics.md`, `docs/siis_paraphrase_baseline_benchmark.md`, `docs/cross_domain_generalization.md`, `docs/camera_hard_negative_analysis.md` -- all real, measured, with stated sample sizes and limitations |
| Docker status | Documented as unverified | `docs/docker_latency_benchmark.md` states plainly that Docker itself could not be built/run in this environment; local-process latency (not container latency) is reported and clearly labeled as such |
| Known limitations | Ready | Consolidated list below; each has its own doc |
| Dataset integrity | Ready | `git diff -- data/` empty; both official files confirmed byte-identical to source, repeatedly, throughout this session |
| Reproducibility | Ready | `scripts/build_plans.py`, `scripts/build_paraphrase_dataset.py`, `scripts/benchmark*.py` are all deterministic and re-runnable from the official data alone |

### Consolidated known limitations (carried forward, none resolved or reopened this task)

- "Optimize now" / "Restart on schedule" can resolve to a parent "Battery" screen instead of
  correctly giving up (`app/services/key_matcher.py`'s `find()` docstring).
- "camera won't open" vs. "camera crashes" is a known, documented, ambiguous-language hard
  negative (`docs/camera_hard_negative_analysis.md`).
- The synthetic cross-domain fixture is not production-scale Battery/Camera/Performance data.
- `row_17` (Display) is refused by the lexical relevance gate despite being a genuinely aligned
  query (`docs/siis_alignment_audit.md`).
- Docker itself has not been build/run-verified in this environment (`docs/docker_latency_benchmark.md`).
