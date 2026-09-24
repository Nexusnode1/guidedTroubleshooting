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
| val | 32 | 0 | 32 | 0.75 | 0.9688 | 0.9688 | 0.8333 |
| test | 64 | 9 | 55 | 0.8727 | 1.0 | 1.0 | 0.9364 |

## Excluded examples

- [test] `row_17`: row row_17 has no valid plan (gated: article judged irrelevant to canonical_query); there is no target title to score retrieval against. Text: "My Galaxy S24 screen goes completely blank, just a dark screen with occasional scrolling and no visible content, so I can't see anything or use Smart Switch to transfer data."
- [test] `row_17`: row row_17 has no valid plan (gated: article judged irrelevant to canonical_query); there is no target title to score retrieval against. Text: "My screen goes totally dark with only a bit of scrolling visible, and I can't see anything or use Smart Switch."
- [test] `row_17`: row row_17 has no valid plan (gated: article judged irrelevant to canonical_query); there is no target title to score retrieval against. Text: "My screen's just black with like a tiny scroll thing happening, and Smart Switch won't work either."
- [test] `row_17`: row row_17 has no valid plan (gated: article judged irrelevant to canonical_query); there is no target title to score retrieval against. Text: "Screen dark, can't use Smart Switch."
- [test] `row_17`: row row_17 has no valid plan (gated: article judged irrelevant to canonical_query); there is no target title to score retrieval against. Text: "There's occasional scrolling but no real content on my screen, and I can't get Smart Switch to transfer my data."
- [test] `row_17`: row row_17 has no valid plan (gated: article judged irrelevant to canonical_query); there is no target title to score retrieval against. Text: "How do I transfer my data with Smart Switch if my screen is dark and I can't see anything?"
- [test] `row_17`: row row_17 has no valid plan (gated: article judged irrelevant to canonical_query); there is no target title to score retrieval against. Text: "My screen barely shows anything except some scrolling and Smart Switch just won't let me move my data over!"
- [test] `row_17`: row row_17 has no valid plan (gated: article judged irrelevant to canonical_query); there is no target title to score retrieval against. Text: 'The display shows minimal scrolling artifacts with no visible content, preventing me from using Smart Switch to migrate data.'
- [test] `row_17`: row row_17 has no valid plan (gated: article judged irrelevant to canonical_query); there is no target title to score retrieval against. Text: "So my screen's basically dark except for a little scrolling now and then, and I can't get Smart Switch going to save my stuff."

## Dataset/schema quality metrics

- Schema/rule validation pass rate: 95% (19/20 rows)
- Exact deeplink accuracy (catalog membership): 100%
- Auto-action screen resolution rate (has a resolved deeplink): 100%
- exact_deeplink_accuracy and auto_action_screen_resolution_rate measure catalog membership and presence of a resolved screen, not per-query semantic correctness. Per-screen correctness is regression-tested with specific catalog IDs in tests/test_plan_builder.py, tests/test_key_matcher.py, and tests/test_domain_generalization.py.

## Misses (test split)

- `row_19` expected 'Cracked bleeding screen', top-1 was ['Device issue']: "My Galaxy Z Flip 7 screen is cracked again right at the fold, touch doesn't work on certain parts of the screen, and I can hardly see anything on the display."
- `row_19` expected 'Cracked bleeding screen', top-1 was ["Access phone's data"]: "The screen cracked again at the fold, some spots don't respond to touch, and it's hard to see the display."
- `row_19` expected 'Cracked bleeding screen', top-1 was ["Access phone's data"]: 'My fold screen cracked again, touch is dead in some spots, and I can barely see anything.'
- `row_19` expected 'Cracked bleeding screen', top-1 was ["Access phone's data"]: 'What can I do about my screen cracking again at the fold along with touch and visibility problems?'
- `row_19` expected 'Cracked bleeding screen', top-1 was ["Access phone's data"]: "This is the second time it's cracked right at the fold, and now touch barely works and I can hardly see anything!"
- `row_19` expected 'Cracked bleeding screen', top-1 was ["Access phone's data"]: "So the fold cracked again, some parts don't respond to touch anymore, and honestly I can barely see the screen at this point."
- `row_22` expected 'Blank black display', top-1 was ["Access phone's data"]: 'The display remains entirely unlit and unresponsive despite no signs of physical damage.'
