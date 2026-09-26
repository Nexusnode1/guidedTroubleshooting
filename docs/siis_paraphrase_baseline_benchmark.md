# SIIS Paraphrase Dataset: Baseline Retrieval Benchmark

No fine-tuning has happened. This measures the current, off-the-shelf embedding model
(`sentence-transformers/all-mpnet-base-v2`, similarity threshold used for cache hits: 0.45;
Recall@k/MRR below rank all cached plans and ignore that threshold, per
`PlanCache.top_matches`) against `data/processed/siis_paraphrase_dataset.json`.

Cache built from 14 train-role rows
(canonical query + 5 train-split paraphrases each). Val and test texts, including whole
held-out rows, were never added to the cache before evaluation.

## Retrieval metrics

`N` is the number of texts actually scored, not the split size in the dataset file:
a row with no valid plan (see Excluded examples below) has no target title to check
retrieval against, so it cannot be scored either way -- it is excluded, not counted
as a miss and not silently dropped from the total without explanation.

| Split | Dataset size | Excluded | N (scored) | Recall@1 | Recall@3 | Recall@5 | MRR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| val | 32 | 0 | 32 | 0.7812 | 0.9375 | 0.9375 | 0.8438 |
| test | 64 | 0 | 64 | 0.8906 | 1.0 | 1.0 | 0.9401 |

## Excluded examples

- none

## Dataset/schema quality metrics

- Schema/rule validation pass rate: 100% (20/20 rows)
- Exact deeplink accuracy (catalog membership): 100%
- Auto-action screen resolution rate (has a resolved deeplink): 100%
- exact_deeplink_accuracy and auto_action_screen_resolution_rate measure catalog membership and presence of a resolved screen, not per-query semantic correctness. Per-screen correctness is regression-tested with specific catalog IDs in tests/test_plan_builder.py, tests/test_key_matcher.py, and tests/test_domain_generalization.py.

## Misses (test split)

- `row_17` expected 'Device issue', top-1 was ['Blank black display']: "My Nexa X1 screen goes completely blank, just a dark screen with occasional scrolling and no visible content, so I can't see anything or use Data Transfer to transfer data."
- `row_19` expected 'Cracked bleeding screen', top-1 was ["Access smartphone's data"]: "My Nexa Fold X1 screen is cracked again right at the fold, touch doesn't work on certain parts of the screen, and I can hardly see anything on the display."
- `row_19` expected 'Cracked bleeding screen', top-1 was ["Access smartphone's data"]: "The screen cracked again at the fold, some spots don't respond to touch, and it's hard to see the display."
- `row_19` expected 'Cracked bleeding screen', top-1 was ["Access smartphone's data"]: 'My fold screen cracked again, touch is dead in some spots, and I can barely see anything.'
- `row_19` expected 'Cracked bleeding screen', top-1 was ["Access smartphone's data"]: 'What can I do about my screen cracking again at the fold along with touch and visibility problems?'
- `row_19` expected 'Cracked bleeding screen', top-1 was ["Access smartphone's data"]: "This is the second time it's cracked right at the fold, and now touch barely works and I can hardly see anything!"
- `row_19` expected 'Cracked bleeding screen', top-1 was ["Access smartphone's data"]: "So the fold cracked again, some parts don't respond to touch anymore, and honestly I can barely see the screen at this point."
