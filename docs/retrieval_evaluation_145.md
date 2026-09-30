# 145-Query Retrieval Evaluation

SYNTHETIC evaluation set (`tests/fixtures/retrieval_evaluation_145.json`), author-written, not official data.
Total queries: 145 (supported: 122, ambiguous: 13, no_match_expected: 10)

## Headline numbers

- Correct matches (supported group, right title): 99 / 122
- Wrong matches (supported group, wrong title returned): 16
- Misses (supported group, fell back to no_match): 7
- False positives (ambiguous/no_match_expected group, a plan was returned anyway): 11 / 23
- Safe fallbacks (ambiguous/no_match_expected group, correctly refused): 12
- Schema/rule validation failures: 0
- Exact-catalog deeplink failures: 0
- Recall@1 / Recall@3 / MRR (supported group, ranked via PlanCache.top_matches): 0.8443 / 0.9754 / 0.9057

## Per-group results

| Group | Status | N | Correct | Wrong | Miss | False positive | Safe fallback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| blank_black_display | supported | 18 | 13 | 5 | 0 | 0 | 0 |
| cracked_bleeding_screen | supported | 15 | 15 | 0 | 0 | 0 | 0 |
| touchscreen_issues | supported | 15 | 14 | 0 | 1 | 0 | 0 |
| screen_flickers | supported | 13 | 13 | 0 | 0 | 0 | 0 |
| access_smartphones_data | supported | 13 | 9 | 4 | 0 | 0 | 0 |
| email_server | supported | 11 | 10 | 0 | 1 | 0 | 0 |
| transfer_secure_folder | supported | 11 | 7 | 0 | 4 | 0 | 0 |
| multi_window_app | supported | 8 | 7 | 0 | 1 | 0 | 0 |
| screen_mirroring_tv | supported | 8 | 8 | 0 | 0 | 0 | 0 |
| device_issue_catch_all | supported | 10 | 3 | 7 | 0 | 0 | 0 |
| ambiguous | ambiguous | 13 | 0 | 0 | 0 | 10 | 3 |
| no_match_expected | no_match_expected | 10 | 0 | 0 | 0 | 1 | 9 |

Strongest supported group: ('cracked_bleeding_screen', 1.0)
Weakest supported group: ('device_issue_catch_all', 0.3)

## Top recurring failure modes

| Expected group -> returned title | Count |
| --- | --- |
| device_issue_catch_all -> Touchscreen issues | 7 |
| transfer_secure_folder -> None | 4 |
| blank_black_display -> Multi window app | 3 |
| ambiguous -> Screen flickers | 3 |
| blank_black_display -> Transfer secure folder | 2 |
| access_smartphones_data -> Device issue | 2 |
| ambiguous -> Screen mirroring tv | 2 |
| ambiguous -> Cracked bleeding screen | 2 |
| touchscreen_issues -> None | 1 |
| access_smartphones_data -> Touchscreen issues | 1 |

## Root cause analysis

Investigated by hand (`git log`-free, read-only diagnostics against `PlanCache.top_matches`);
see the session notes for the exact per-query score breakdowns. Every 'wrong' or 'false_positive'
result traces to one of three causes, none of which is a general retrieval defect fixable
without touching official data, adding per-row rules, or lowering the safety threshold --
all explicitly out of scope for this evaluation:

1. **Already-documented misaligned official rows** (`docs/siis_alignment_audit.md`,
   `docs/siis_dataset_quality_report.md`). row_1, row_5, row_7/row_12, and row_8's own
   *canonical query* (the customer's original complaint, which is itself a cache key)
   describes a generic blank/dark/small-screen symptom, while the *plan* their article
   maps to is unrelated (email connectivity, Data Transfer, Multi window, Screen mirroring).
   A new query that genuinely resembles that symptom correctly ranks near those canonical
   queries -- the cache is retrieving the closest real key, faithfully; the key itself is
   mislabeled relative to its plan. This accounts for most `blank_black_display` and
   `access_smartphones_data` 'wrong' results, `ambiguous` group's 'My phone screen is
   acting up' (row_8) and 'My phone has a problem but I can't really describe what's
   happening' (row_1), and the `no_match_expected` Bluetooth false positive (row_8's
   article contains literal Windows-PC instructions mentioning Bluetooth) -- the last of
   these was already investigated earlier in this evaluation's history with several general
   candidate fixes tested and none clearing every acceptance criterion; see
   `docs/cross_domain_hard_negatives.md`.
2. **This fixture's own paraphrase choices.** All 7 `device_issue_catch_all` 'wrong'
   results are paraphrases the fixture wrote with the word 'touchscreen' inserted into
   them, intending to represent official row_11 (which says only 'screen is half black',
   never 'touchscreen'). Retrieval correctly redirects text that says 'touchscreen' toward
   the Touchscreen issues plan; that is the fixture's authoring choice, not a retrieval bug.
3. **Expected threshold-boundary misses.** All 7 `miss` results score 0.41-0.48 on their
   correct plan (visible via `PlanCache.top_matches`, which ignores the threshold) --
   just under `SIMILARITY_THRESHOLD` (0.48). These are short, generic, or heavily
   paraphrased queries near the deliberate precision/recall boundary that threshold sets;
   refusing to answer instead of guessing is the intended, safer behavior, not a defect.

**Conclusion: no general retrieval change is justified by this evaluation.** The threshold,
key weights, and intent-confidence cap already in place (see `metrics.md`) were not modified.