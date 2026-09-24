# Camera hard negative: "camera won't open" vs. "camera crashes"

Query: *"This is so annoying, I tap the camera icon and literally nothing happens."*
Positive target: `camera_wont_open_permission` ("Camera app won't")
Confused-with target: `camera_crashes_freezes` ("Camera app crashes")

## What the real, shipped mechanism actually is

The semantic cache lookup (`PlanCache.top_matches`, used by `troubleshoot()` when no
`siis_response` is supplied) is **dense-only**: cosine similarity between the query's
embedding and every stored key's embedding, via the configured `EMBEDDING_MODEL`
(`sentence-transformers/all-mpnet-base-v2`). There is no BM25 stage and no hybrid blend
anywhere in this path -- that architecture was tried for a different purpose (deeplink
mapping) early on and rejected (see the design spec); it was never part of query-to-plan
matching. The numbers below reflect that honestly: the "BM25"/"hybrid" figures are a
**supplementary side comparison**, built by feeding the same text into the existing (but
otherwise-unused-here) `BM25Retriever`/`HybridRetriever` classes, clearly separated from what
the real system does.

## Real mechanism: per-key dense scores

Every text is normalized (lower-cased, whitespace-collapsed) before embedding, exactly as
`PlanCache` does it.

| Key (camera_wont_open_permission, POSITIVE) | dense |
| --- | --- |
| canonical: "My camera app won't open on my Galaxy phone, it just doesn't launch at all." | 0.5600 |
| generated variation: "Help with camera app won't" | **0.6359** |
| generated variation: "This is so annoying - camera app will not open galaxy phone just does not launch at all, please help!" | 0.6214 |
| plan key: "Check Camera Access. Go to Settings." | 0.6231 |
| plan key: "Restart Your Phone. Press and hold the Power button." | 0.4566 |
| (5 other generated variations) | 0.28 - 0.56 |

| Key (camera_crashes_freezes, NEGATIVE) | dense |
| --- | --- |
| canonical: "My camera app keeps crashing or freezing whenever I try to take a photo." | 0.5964 |
| generated variation: "This is so annoying - camera app keeps crashing or freezing whenever try take photo, please help!" | **0.6663** |
| plan key: "Clear The Camera App Cache. Go to Settings." | 0.6466 |
| plan key: "Restart In Safe Mode. Press and hold the Power button." | 0.3334 |
| (6 other generated variations) | 0.43 - 0.63 |

**Rank of the correct target (positive):** 2, score 0.6359
**Rank of the incorrect target (negative):** 1, score 0.6663
**Margin:** 0.0304 (narrow)

## Isolating the cause: is it the auto-generated `query_variations`, or something more fundamental?

`generate_variations()` (used to populate the official `query_variations` field, and also
folded into the cache as extra lookup keys) uses a literal `"This is so annoying - {core},
please help!"` template for *every* cached plan. The test query also happens to open with
"This is so annoying," so there is a real risk the winning match is just template-phrase
overlap, not genuine semantic confusion. Re-scoring with those generated variations excluded
(canonical query + plan keys only):

| Entry | Best score without generated variations | Best score with them (what `top_matches` actually uses) |
| --- | --- | --- |
| camera_wont_open_permission (positive) | 0.6231 | 0.6359 |
| camera_crashes_freezes (negative) | 0.6466 | 0.6663 |

**The negative target still outscores the positive one even with the generated variations
removed entirely** (0.6466 vs. 0.6231, margin 0.0235). The generated-variation template
widens the existing gap (to 0.0304) but does not create it. The confusion is not an artifact
of candidate generation; it is present at the canonical-query/plan-key level already.

## Where the confusion actually comes from

"I tap the camera icon and literally nothing happens" is genuinely ambiguous between two
distinct real technical scenarios the fixture deliberately kept separate: the app never
launching (a permission/launch problem) and the app launching then immediately dying (a
crash). Neither the query text nor the two articles' plan-key text ("Check Camera Access" vs.
"Clear The Camera App Cache") share strong distinguishing vocabulary with this specific
phrasing -- both score in the same narrow 0.62-0.65 band. This is primarily **data/language
ambiguity**, secondarily **amplified by the generic query_variations template**, not a
retrieval-weighting, candidate-generation, or embedding-model defect.

## Downstream stages: unaffected, correctly so

Once retrieval picks a (here, wrong) target, screen resolution and deeplink mapping run
against *that* plan's own content and are completely correct for it:

- `camera_wont_open_permission`, if it had won: `Check Camera Access` -> `DL-0197` (auto).
- `camera_crashes_freezes`, the one actually returned: `Clear The Camera App Cache` ->
  `bixby://dummy_positive` (the documented placeholder; there is no "Storage" catalog entry)
  and `Restart In Safe Mode` (critical, no deeplink).

Both plans independently pass the validation firewall. The failure is entirely at the
retrieval/ranking stage, before screen resolution or deeplink mapping are reached for the
correct target -- it is not a screen-resolution or final-mapping problem.

## Frozen baseline (current, non-fine-tuned embedding model)

Computed from `tests/fixtures/camera_hard_negative.json` (5 positive + 5 hard-negative
paraphrases, including the confusable query as one of the 5 positive paraphrases), against a
cache seeded with only the two competing canonical queries -- exactly the scenario
`tests/test_camera_hard_negative.py` locks in as a regression test:

| Metric | Value |
| --- | --- |
| N | 10 |
| Recall@1 | 0.90 (9/10) |
| Recall@3 | 1.00 |
| MRR | 0.95 |
| Positive rank (confusable query) | 2 |
| Hard-negative rank (confusable query) | 1 |

The single miss is exactly the confusable query identified above; every other paraphrase on
both sides ranks first. This is the baseline any future change (fine-tuning, a reranker, or
a fix to this specific pair) should be measured against.

## Supplementary (NOT part of the shipped pipeline): BM25 and hybrid, same text

Repurposing `BM25Retriever`/`HybridRetriever` over the same key set, purely for comparison:

| Approach | Best score, positive | Best score, negative | Winner |
| --- | --- | --- | --- |
| BM25 alone | 3.6639 | 4.1078 | negative (same as dense) |
| Hybrid (0.5 BM25 + 0.5 dense, real embedder) | 0.9017 | 1.0000 | negative (same as dense) |

BM25 and the hybrid blend reproduce the same wrong ranking as the shipped dense-only
mechanism on this specific pair -- switching retrieval approach would not have avoided this
particular confusion; both approaches score "This is so annoying - camera app keeps crashing
..." as a strong keyword/semantic match to the query's own frustrated framing. This is
evidence against introducing BM25/hybrid *specifically to fix this case*.
