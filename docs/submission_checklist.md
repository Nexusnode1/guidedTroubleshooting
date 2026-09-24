# Submission Checklist

Concise go/no-go checklist for Samsung PRISM hackathon submission. Full detail for any row is
in the linked document; this file only states the current status.

| Item | Status | Evidence |
| --- | --- | --- |
| Source datasets untouched | READY | `data/original/siis_responses.json` and `deeplinks.json` confirmed byte-identical to `../student_kit/` and `git diff -- data/` empty, verified repeatedly, most recently in this audit |
| Tests (backend) | READY | `pytest -q` -> 391 passed, 3 skipped (skips are documented placeholders for out-of-scope features, not disabled coverage) |
| Tests (frontend) | READY | `npm test -- --run` -> 18/18 passing |
| Frontend build | READY | `npm run build` -> `tsc --noEmit && vite build` succeeds |
| Demo flow | READY | `docs/demo_readiness.md` section 5: a 2:45 script covering all 5 verified queries (Standard, Multi-step, Manual, Paraphrase, Battery cold-path) |
| REST API | READY | `GET /health`, `POST /v1/troubleshoot`; schema in `DATA_MODEL.md` / `app/models/official_schema.py`; zero URL leaks and 100% catalog-verbatim deeplinks measured in `metrics.md` |
| Docker | DOCUMENTED, RUNTIME UNVERIFIED | `Dockerfile`, `.dockerignore`, `docker-compose.yml` exist and are reviewed; `docker` is not installed in this development environment (confirmed repeatedly, most recently in this audit) -- image build and container run have never been executed here. All latency numbers in `docs/docker_latency_benchmark.md` are real **local-process** measurements of the same code path, explicitly not container measurements. Do not claim Docker build/runtime success. |
| Metrics | READY, CLEARLY SCOPED | `metrics.md` (official-data schema/latency/cache benchmarks), `docs/siis_paraphrase_baseline_benchmark.md` (retrieval accuracy, official data), `docs/cross_domain_generalization.md` (retrieval accuracy, **synthetic** fixture, explicitly not production-scale evidence), `docs/docker_latency_benchmark.md` (local-process latency, cache hit *rate* vs. hit *correctness* kept separate) |
| Known limitations | READY, PRESERVED | See below -- each has its own doc and none were papered over for this submission |
| Git commit / branch | `main` @ `0d7d4cfbce4f3a98b47491c9a0be98a52bf7589c` ("Complete troubleshooting engine and demo") | `git log -1`; working tree was clean before this audit's documentation-only edits |

## Known limitations (preserved, not resolved by this audit)

- **"Optimize now" / "Restart on schedule" parent-menu-match family**: can resolve to the parent
  "Battery" screen instead of correctly giving up. A general fix regressed a real official row
  and was reverted. `app/services/key_matcher.py`'s `find()` docstring.
- **Camera hard-negative ambiguity**: "camera won't open" vs. "camera crashes" is a documented,
  ambiguous-language confusion in embedding space. `docs/camera_hard_negative_analysis.md`.
- **Synthetic cross-domain fixture**: Battery/Camera/Performance generalization is checked
  against a 16-article, author-written fixture, not production-scale real customer data.
  `docs/cross_domain_generalization.md`.
- **Docker runtime verification pending**: build/run success and container latency are
  unverified in this environment. `docs/docker_latency_benchmark.md`.
- The lexical relevance gate occasionally refuses an aligned query (official `row_17`) and
  occasionally accepts a loosely-related one (rows 7, 12). `metrics.md` section 6,
  `docs/siis_alignment_audit.md`.

## What this audit changed

Documentation only, per the explicit scope of the final packaging audit: `README_PROJECT.md`
(added explicit architecture/output-schema/Fast-Path-cache/frontend-demo/benchmark-results/
known-limitations sections), `ARCHITECTURE.md` (named the 8-stage pipeline explicitly, clarified
the fast-path bypass and the "Retrieval" naming), `docs/demo_readiness.md` (added the
multi-step-query beat to the demo script, corrected the stale "no way to supply siis_response"
gap and the stale "14/14" test count now that the cold-path UI exists), and this file (new). No
application code, tests, or data files were changed.
