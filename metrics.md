# System Performance Metrics & Evaluation Report
**Model(s):** none (rules-v1: deterministic parsing, exact-label deeplink matching; no generative model)
**Embeddings:** sentence-transformers/all-mpnet-base-v2 (similarity threshold 0.48; boilerplate-paraphrase keys and critical-action keys weighted 0.85; action keys capped below any intent match of 0.60 or more)
**Environment:** win32, Python 3.11.2

---

## 1. Schema & Rule Compliance
Evaluated over the 18 plans built from the official sample rows.

| Metric | Target | Measured Value |
| :--- | :--- | :--- |
| Schema-valid output lines | >= 99% | 100.0% |
| Rule compliance (Goal / Title / Description syntax) | >= 95% | 100.0% |
| Absolute URL leaks | 0 | 0 |
| Deeplink catalog validity (exact URI match) | 100% | 100.0% |
| Auto actions carrying valid actionable deeplink | >= 90% | 100.0% |

---

## 2. Accuracy Benchmarks
No ground-truth plans were supplied, so step accuracy and deeplink relevance were not scored.

| Evaluation Metric | Scale / Anchor | Score |
| :--- | :--- | :--- |
| Step accuracy (completeness, correctness, ordering) | 0.0 - 3.0 | not scored |
| Deeplink relevance (exact target screen vs. parent menu) | 0.0 - 2.0 | not scored |

---

## 3. Latency Benchmarks (N = 30 requests per path)

| Execution Path | Target (P95) | P50 (ms) | P95 (ms) | Result |
| :--- | :--- | :--- | :--- | :--- |
| Cache hit - exact query match | <= 300 ms | 0.2 - 0.4 | 0.2 - 0.6 | met |
| Cache hit - unseen semantic paraphrase | <= 300 ms | 61.1 - 77.2 | 80.3 - 104.4 | met |
| Cold query - full pipeline extraction & mapping | <= 8000 ms | 922.1 - 1130.7 | 1062.1 - 1528.4 | met |

Each cell is the range over three separate single runs of `scripts/benchmark.py` on one local
development machine (CPU only, in-process calls, not a container and not over HTTP), taken
while other work was running on the same machine. The most recent run, on the final
configuration, measured P95 0.3 ms (exact), 80.3 ms (paraphrase) and 1156.9 ms (cold). They
are not a controlled measurement and are not Docker figures; absolute values depend on the
hardware.

---

## 4. Operational Cost & Cache Efficacy

| Metric Item | Target | Measured Value |
| :--- | :--- | :--- |
| Cold query average inference cost | Tracked | $0.00 |
| Cache hit inference cost | $0.00 | $0.00 |
| Semantic cache hit rate (unseen paraphrases, correct plan) | >= 80% | 89.3% (25 of 28; 2 hit a wrong plan, 1 fell back) - met |
| Per held-out set | | paraphrases: 13/14; paraphrases_holdout: 12/14 |
| Ranking on the 28 held-out paraphrases (by plan title) | - | Recall@1 0.893; Recall@3 0.964; Recall@5 0.964; MRR 0.927 |
| Unrelated queries wrongly answered | 0 | 0 of 12 |
| Out-of-scope device complaints wrongly answered (probe set used while tuning) | 0 | 6 of 49 |
| Out-of-scope device complaints wrongly answered (second probe set, scored once after tuning) | 0 | 4 of 38 |
| Cost derivation method | - | no generative calls; (prompt tokens + completion tokens) x rate = 0 |
| External model inference in the request path | - | none: the only model is the local sentence-embedding model used for cache lookup, so no token usage exists to report; hosting/compute cost was not measured |

The two probe sets are complaints about features the official rows do not cover (Bluetooth,
Wi-Fi, mobile network, sound, battery, storage, notifications, calls, accounts, security,
permissions, shutdown, generic Settings questions), so any answer is a false positive. They
were written for this evaluation and are not stored in the repository; 27 of the first set
are kept as regression tests in `tests/test_retrieval_hard_negatives.py`. The threshold and
key weights were chosen using both held-out paraphrase sets and the first probe set, so the
89.3% figure is not independent of the configuration choice; the second probe set is. The
0.60 intent cap was likewise chosen with the synthetic cross-domain fixture in view, so its
80 of 80 is not an independent figure either.

---

## 5. Architectural Ablation Analysis

| Architecture Variant | Step Accuracy | Latency (P95) | Cost / Query | Key Observations |
| :--- | :--- | :--- | :--- | :--- |
| Baseline: Full LLM Deeplink Mapping | not run | not run | not run | No LLM in this version. |
| Variant A: Hybrid BM25 + Dense Embedding Retrieval | not scored | not run | $0.00 | Tried on real sections and rejected: min-max fusion scores the top hit near 1.0 even for unrelated screens (for example "Restart in Safe Mode" against "One-handed mode"). |
| Variant B: Pure Rules-Based Deeplink Mapping | not scored | 1062.1 - 1528.4 ms cold (local, see section 3) | $0.00 | Exact match of the tapped UI label to the catalog's `validation.key`. This is what ships. |
| Cache lookup: hashed bag-of-words embedding | n/a | fast | $0.00 | 8 of 14 paraphrases on the first set. Fallback only (`EMBEDDING_MODEL=hash`). |
| Cache lookup: all-mpnet-base-v2 + action-content keys, all keys at equal weight, threshold 0.45 | n/a | not re-measured | $0.00 | Previous default. 24 of 28 (85.7%; 3 hit a wrong plan); 15 of 49 out-of-scope probes wrongly answered. |
| Cache lookup: all-mpnet-base-v2 + action-content keys, boilerplate and critical-action keys at 0.85, threshold 0.48 | n/a | not re-measured | $0.00 | Intermediate step. 25 of 28 (89.3%); 6 of 49 out-of-scope probes wrongly answered; 79 of 80 on the synthetic cross-domain fixture. |
| Cache lookup: the row above plus action keys capped below any intent match of 0.60 or more | n/a | see section 3 | $0.00 | Default. Same 25 of 28 and 6 of 49; 80 of 80 on the synthetic cross-domain fixture (the one camera query a remedy step used to win is now ranked by the complaint). Meets the hit-rate target on both held-out sets. |

---

## 6. Known Edge Cases & System Limitations
* The article-relevance gate is lexical. Rows 8 and 20 (article does not fit the complaint) are refused, but rows 7 and 12 share ordinary words with their article and still receive a plan. Fixing this needs semantic similarity.
* Remaining paraphrase misses are ambiguous complaints, for example a smashed screen where the user cannot see anything (cracked screen versus recovering data). Rows 3 and 11 yield a thin plan (a single force-restart action) because their source article is mostly unrelated text.
* Out-of-scope complaints can still borrow a plan. Bluetooth complaints match the screen-mirroring plan, whose steps mention "Bluetooth and other device settings"; other observed cases are a charging complaint answered with the touchscreen plan (its "Charger issues" action), "make my screen brighter" (multi-window plan), "games stutter and the frame rate drops" (screen-flicker plan), and "open the settings app" (data-transfer plan).
* Held-out sets are small (14 queries each); treat the percentages as indicative, not precise.
* Multi-intent complaints (row 19) are answered for the dominant intent only.
* Rows 6 and 18 do not exist in `siis_responses.json`. Rows 16 and 20 are refused by the relevance gate.
* The official `sample_output.json` has action descriptions of 9 and 11 words, against the written 5 to 7 word rule; this engine follows the written rule.
* All 20 official rows are Display complaints. Battery/Camera/Performance generalization is checked separately, against author-written test articles, in `tests/test_domain_generalization.py` (see `docs/domain-coverage.md`), not in the figures above.
