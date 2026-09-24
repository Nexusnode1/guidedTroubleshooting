# Cross-domain hard negatives (observed, not assumed)

Against **SYNTHETIC DOMAIN GENERALIZATION FIXTURE** (`tests/fixtures/cross_domain_articles.json`).
Only confusions actually produced by running `scripts/benchmark_cross_domain.py` are listed;
none are hypothesized in advance and treated as findings.

## Observed

1. **Camera app won't open vs. Camera app crashes.**
   - Query: *"This is so annoying, I tap the camera icon and literally nothing happens."*
   - Correct intent: `camera_wont_open_permission` ("Camera app won't", similarity 0.6359, rank 2)
   - Retrieved instead: `camera_crashes_freezes` ("Camera app crashes", similarity 0.6663, rank 1)
   - Why confusable: "nothing happens when I tap it" is genuinely ambiguous between "the app
     never launches" (a permission/launch problem) and "the app launches and immediately dies"
     (a crash) -- a real customer complaint in this phrasing could plausibly mean either. The
     rank gap is narrow (0.0304), meaning the two intents sit close together in embedding space
     for this specific phrasing.
   - This is the only miss across all 80 cross-domain paraphrases in this run (Recall@1 = 98.75%
     combined). It was not observed for any other Camera, Battery, or Performance paraphrase.

## Checked for but not observed

The task brief suggested several plausible pairs (battery drain vs. battery protection, camera
permission vs. camera behavior, slow performance vs. overheating). None of these were actually
confused in this run -- every other paraphrase across all three domains retrieved its correct
target at rank 1. They are not recorded as hard negatives, per the instruction not to assume a
confusion exists without observing it.

## Distinct from this document: known pipeline limitations

Three things this fixture surfaced are about the deeplink-mapping/classification pipeline
itself, not about retrieval confusions, and are documented where the code lives instead of
here. Two were fixed; one remains open:

- **Fixed.** `performance_want_scheduled_restart` was losing a real, verified deeplink
  (`DL-0480`) because the keyword-based critical-action classifier matched the word "restart"
  inside the catalog setting's own name ("Restart the device when needed", a toggle), not
  because the instruction was actually disruptive. Fixed by resolving the catalog match first:
  the catalog only ever models View/Toggle/Update actions, never an immediate destructive one,
  so a real match can never legitimately be critical. See `app/services/plan_builder.py`'s
  `_build_action` docstring; regression-tested against three genuine disruptive instructions
  (force restart, factory reset, safe mode) to confirm they remain critical with no deeplink.
- **Fixed.** "Turn it on"/"turn it off" phrasing (a word between "turn" and "on"/"off") was
  silently missed by the old adjacency-strict regex, and the unrelated "switch next to" wording
  then forced the *opposite* toggle direction. See `app/services/key_matcher.py`'s
  `_TURN_ON`/`_TURN_OFF` patterns.
- **Open, deliberately not fixed.** `performance_optimize_one_tap` resolves to the parent
  "Battery" screen instead of correctly giving up, because "Optimize Device Performance"
  (DL-0538) has no `validation.key` and cannot be matched. A related, narrower case: a real key
  of the shape "Restart on schedule" is trimmed down to the excluded word "Restart" before an
  extended match is attempted, falling back to the same "Battery" ancestor. See
  `app/services/key_matcher.py`'s `find()` docstring, which documents why a general fix was
  attempted and reverted (it regressed the official row_21 "Navigation bar" -> "Buttons" case).
