# Cross-Domain Generalization Benchmark

**SYNTHETIC DOMAIN GENERALIZATION FIXTURE.** Author-written Battery/Camera/Performance
articles (see tests/fixtures/cross_domain_articles.json), run through the real
TroubleshootingService.troubleshoot(query, siis_response=...) pipeline. This is a
small (N=16 articles, 80 paraphrases) fixture meant to
expose domain-specific failure modes, not to make a statistically representative claim.
No fine-tuning was performed; embedding model, threshold, and retrieval weights are
unchanged (`sentence-transformers/all-mpnet-base-v2`).

## Retrieval metrics (paraphrases matched against the cache the cold calls populated)

| Domain | N | Recall@1 | Recall@3 | Recall@5 | MRR |
| --- | --- | --- | --- | --- | --- |
| Battery | 25 | 1.0 | 1.0 | 1.0 | 1.0 |
| Camera | 30 | 0.9667 | 1.0 | 1.0 | 0.9833 |
| Performance | 25 | 1.0 | 1.0 | 1.0 | 1.0 |
| combined | 80 | 0.9875 | 1.0 | 1.0 | 0.9938 |

## Pipeline diagnostics (cold path, one call per article)

- Schema/rule validation pass rate: 16/16 (100%)
- Deeplink accuracy (resolved id in the article's own verified expected set, or correctly no real deeplink where none should exist): 16/16 (100%)
- Genuine pipeline failures/limitations found: 0

| fixture_id | domain | resolved title | resolved deeplinks | expected | match | ordering ok |
| --- | --- | --- | --- | --- | --- | --- |
| battery_drain_fast | Battery | Battery drains unusually | DL-0412, DL-0398, DL-0544 | DL-0412, DL-0398, DL-0544 | yes | yes |
| battery_protection_limit | Battery | Set charging limit | DL-0410, DL-0552 | DL-0410, DL-0552 | yes | yes |
| fast_charging_slower_than_before | Battery | Charging speed troubleshooting | DL-0514 | DL-0403, DL-0404, DL-0514 | yes | yes |
| overheating_while_charging | Battery | Gets hot while | DL-0403 | DL-0403 | yes | yes |
| battery_health_check | Battery | Phone's battery health | DL-0552, DL-0477 | DL-0552, DL-0477 | yes | yes |
| camera_wont_open_permission | Camera | Camera app won't | DL-0197 | DL-0197 | yes | yes |
| camera_crashes_freezes | Camera | Camera app crashes | PLACEHOLDER | (none) | yes | yes |
| camera_vibrates_unexpectedly | Camera | Camera vibrates unexpectedly | DL-0053 | DL-0053 | yes | yes |
| camera_led_flash_notification | Camera | Camera flash | DL-0056 | DL-0056 | yes | yes |
| camera_photo_quality_blurry | Camera | Photos from camera | (none) | (none) | yes | yes |
| camera_share_webcam_not_working | Camera | Camera share as | DL-0130 | DL-0130 | yes | yes |
| performance_slow_after_update | Performance | Device runs slowly | DL-0418 | DL-0418 | yes | yes |
| performance_apps_closing_background | Performance | Apps keep closing | DL-0416 | DL-0416 | yes | yes |
| performance_want_scheduled_restart | Performance | Set up automatic | DL-0480 | DL-0480 | yes | yes |
| performance_overheating_during_gaming | Performance | Device overheats slows | DL-0418 | DL-0418 | yes | yes |
| performance_optimize_one_tap | Performance | Speed up slow | DL-0560 | DL-0560 | yes | yes |

## Pipeline stage coverage

| PDF-named stage | What actually runs | Exercised here |
| --- | --- | --- |
| Query Enrichment | `QueryEnricher`/`normalize_query` (via `generate_variations`/`PlanCache`) | yes |
| Structure Extraction | `siis_parser.parse_sections`/`extract_steps` | yes |
| Intent/Context | `relevance()` gate, `is_imperative` | yes |
| BM25 + Dense Retrieval | **not present** -- deeplink mapping uses exact-label `KeyIndex` matching instead (documented architectural deviation, see the design spec) | n/a |
| Screen Resolution / Deeplink Mapping | `KeyIndex.find()` | yes |
| Action Ordering | `order_actions`/`ordered_values` | yes |
| Validation Firewall | `validate_plan()` | yes |

## Genuine findings from this run

See `docs/cross_domain_hard_negatives.md` for observed retrieval confusions, and
`app/services/key_matcher.py`'s `find()` docstring for the two known, deliberately-
unfixed screen-resolution limitations this fixture surfaced: `performance_optimize_one_tap`
resolving to the parent "Battery" screen instead of correctly giving up (a fix regressed
official row_21 and was reverted), and the narrower, related case where a real key of the
shape "Restart on schedule" is trimmed down to the excluded word "Restart" before an
extended match is even attempted, falling back to the same "Battery" ancestor.

Two other findings from this fixture *were* fixed, with regression tests and no
official-row regression: "turn it on"/"turn it off" phrasing (an interposed word broke the
old adjacency-strict regex, silently flipping toggle direction to the opposite of the
instruction), and the critical-action classifier matching the word "restart" inside a
catalog setting's own *name* (`performance_want_scheduled_restart`, "Restart the device
when needed" -- a toggle, not an instruction to restart immediately) rather than the
instruction text -- fixed by resolving the catalog match first, since the catalog only
ever models View/Toggle/Update actions and never an immediate destructive one.

## Limitations of this fixture

- 16 articles, 5 paraphrases each: enough to expose failure modes, not enough for a
  statistical claim about accuracy in any domain.
- Author-written, not real Samsung customer language or real SIIS content.
- The catalog has very limited true "Camera app" coverage (permission, feedback,
  flash-as-notification, share-as-webcam only -- no photo quality/focus/HDR settings
  exist at all), which this fixture surfaces rather than works around.
