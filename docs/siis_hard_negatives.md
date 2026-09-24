# Hard negatives for the SIIS paraphrase dataset

Per the audit (`docs/siis_alignment_audit.md`) and the baseline benchmark
(`docs/siis_paraphrase_baseline_benchmark.md`). Every pair below comes from real
intents/classes already present in `data/processed/siis_paraphrase_dataset.json` or
`data/original/deeplinks.json` -- nothing here is invented. Fine-tuning has not started; this
is the input to that decision, not a training run.

## Article/intent-level pairs (confirmed by the baseline benchmark)

1. **"Blank or black display" (device won't power on) vs "Some things to check first" /
   "Access your Galaxy phone's data" (screen unresponsive, focus on data recovery).**
   Both share "screen," "black," "doesn't respond" vocabulary; the actual remedy differs
   (force-restart/charge vs USB-mouse data access). Empirically confirmed: in the baseline
   run, `row_22` ("The display remains entirely unlit and unresponsive despite no signs of
   physical damage") was retrieved as "Access phone's data" instead of "Blank black
   display" -- the exact confusion this pair predicts.
2. **"Cracked or bleeding screen" vs "Access your Galaxy phone's data."** A multi-symptom
   crack complaint that also mentions touch not working and poor visibility (`row_19`) shares
   real vocabulary with the "screen doesn't respond, need to recover data" class. Empirically
   confirmed: the baseline run misretrieved `row_19`'s canonical query and 5 of its 6
   remaining paraphrases as "Access phone's data" or "Device issue," its only correct hit
   being one very literal paraphrase. This is the single largest source of test-split misses
   in the baseline benchmark.
3. **"Blank or black display" vs "Screen flickers when using the Camera."** Both
   keyword-share "screen"; root cause and remedy are unrelated (power/hardware vs
   camera/lighting). Not yet observed as a live confusion in the small held-out set, but the
   vocabulary overlap is real and worth a held-out probe once more paraphrases exist.
4. **"Touchscreen issues" (touch lag while the display works) vs "Access your Galaxy
   phone's data" (touch completely unresponsive and/or display invisible).** Overlapping
   vocabulary ("touch," "doesn't work"), different severity and different remedy.
5. **Coverage gaps found by the audit, not confusable pairs to train against:** the
   original `row_12` (floating Assistant-Menu-style shortcut) and `row_20` (visual
   distortion) complaints have **no matching article anywhere in the 20 official rows**.
   There is nothing to contrast them against because there is nothing to retrieve for them
   either -- flagged as gaps, not negatives, in `docs/siis_alignment_audit.md`.

## Catalog-label-level pairs (for the exact-label key matcher / a future semantic relevance gate)

These are about `app/services/key_matcher.py` and `app/services/relevance.py`, not the
paraphrase dataset directly, but are the natural next probe once embedding work starts
touching those components (see `docs/domain-coverage.md`'s note on the lexical relevance
gate's false positives on rows 7 and 12).

1. `"Brightness"` (DL-0232) vs `"Extra dim"` (DL-0203/DL-0204) vs `"Adaptive brightness"`
   (DL-0020/DL-0021) -- three distinct display-intensity controls a naive semantic match
   could conflate.
2. `"Touch sensitivity"` vs `"Touch interactions"` (DL-0290/DL-0291/DL-0297/DL-0298) --
   both mention "touch," but one is input sensitivity and the other is sound/vibration
   feedback on touch.
3. `"Screen timeout"` (DL-0220) vs `"Auto lock when screen turns off"` (DL-0151) -- both
   about screen-off timing, distinct settings.

## Using these later

When fine-tuning starts (not yet), pair 2 above (Cracked/bleeding vs Access-data) is the
highest-priority hard negative: it is the only one with direct empirical failures in the
baseline benchmark, not just a hypothesized risk.
