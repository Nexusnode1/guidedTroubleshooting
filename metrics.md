# System Performance Metrics & Evaluation Report
**Model(s):** none (rules-v1: deterministic parsing, exact-label deeplink matching; no generative model)
**Embeddings:** sentence-transformers/all-mpnet-base-v2 (similarity threshold 0.45)
**Environment:** win32, Python 3.13.3

---

## 1. Schema & Rule Compliance
Evaluated over the 17 plans built from the official sample rows.

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
| Cache hit - exact query match | <= 300 ms | 0.1 | 0.1 | met |
| Cache hit - unseen semantic paraphrase | <= 300 ms | 25.2 | 30.7 | met |
| Cold query - full pipeline extraction & mapping | <= 8000 ms | 241.0 | 251.8 | met |

---

## 4. Operational Cost & Cache Efficacy

| Metric Item | Target | Measured Value |
| :--- | :--- | :--- |
| Cold query average inference cost | Tracked | $0.00 |
| Cache hit inference cost | $0.00 | $0.00 |
| Semantic cache hit rate (unseen paraphrases, correct plan) | >= 80% | 89.3% (25 of 28; 2 hit a wrong plan) - met |
| Per held-out set | | paraphrases: 13/14; paraphrases_holdout: 12/14 |
| Unrelated queries wrongly answered | 0 | 0 of 12 |
| Cost derivation method | - | no generative calls; (prompt tokens + completion tokens) x rate = 0 |

---

## 5. Architectural Ablation Analysis

| Architecture Variant | Step Accuracy | Latency (P95) | Cost / Query | Key Observations |
| :--- | :--- | :--- | :--- | :--- |
| Baseline: Full LLM Deeplink Mapping | not run | not run | not run | No LLM in this version. |
| Variant A: Hybrid BM25 + Dense Embedding Retrieval | not scored | not run | $0.00 | Tried on real sections and rejected: min-max fusion scores the top hit near 1.0 even for unrelated screens (for example "Restart in Safe Mode" against "One-handed mode"). |
| Variant B: Pure Rules-Based Deeplink Mapping | not scored | 251.8 ms cold | $0.00 | Exact match of the tapped UI label to the catalog's `validation.key`. This is what ships. |
| Cache lookup: hashed bag-of-words embedding | n/a | fast | $0.00 | 8 of 14 paraphrases on the first set. Fallback only (`EMBEDDING_MODEL=hash`). |
| Cache lookup: all-mpnet-base-v2 + action-content keys | n/a | see section 3 | $0.00 | Default. Meets the hit-rate target on both held-out sets. |

---

## 6. Known Edge Cases & System Limitations
* The article-relevance gate is lexical. Rows 8 and 20 (article does not fit the complaint) are refused, but rows 7 and 12 share ordinary words with their article and still receive a plan. Fixing this needs semantic similarity.
* Remaining paraphrase misses are ambiguous complaints, for example a smashed screen where the user cannot see anything (cracked screen versus recovering data). Rows 3 and 11 yield a thin plan (a single force-restart action) because their source article is mostly unrelated text.
* Held-out sets are small (14 queries each); treat the percentages as indicative, not precise.
* Multi-intent complaints (row 19) are answered for the dominant intent only.
* Rows 6 and 18 do not exist in `siis_responses.json`. Rows 16, 17, and 20 are refused by the relevance gate.
* The official `sample_output.json` has action descriptions of 9 and 11 words, against the written 5 to 7 word rule; this engine follows the written rule.
* All 20 official rows are Display complaints. Battery/Camera/Performance generalization is checked separately, against author-written test articles, in `tests/test_domain_generalization.py` (see `docs/domain-coverage.md`), not in the figures above.
