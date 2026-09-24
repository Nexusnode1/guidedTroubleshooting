# SIIS Paraphrase Dataset: Quality Report

Date: 2026-09-22. Covers the audit, correction, and paraphrase-generation work over
`data/original/siis_responses.json` (read-only, unmodified throughout). Companion documents:
`docs/siis_alignment_audit.md` (full per-row audit), `docs/siis_hard_negatives.md`,
`docs/siis_paraphrase_baseline_benchmark.md`. No fine-tuning has happened; none is
recommended to start yet (see section 10).

## 1-6: Headline numbers

| Metric | Value |
| --- | --- |
| Rows audited | 20 |
| ALIGNED | 9 |
| PARTIALLY_ALIGNED | 2 |
| MISALIGNED | 9 |
| Corrected (PARTIALLY_ALIGNED + MISALIGNED) | 11 |
| Paraphrases generated | 160 (20 rows x 8, hand-written, no templating) |
| Unique underlying articles (classes) | 11 |
| Train / val / test texts | 84 / 32 / 64 (180 total) |

## 7. Rejected during quality checks

Every corrected row went through at least one rejected first-draft direction before the
final wording (11 rows corrected = at least 11 rejection/revision events), plus 2 further
revisions caught not by manual review but by actually running the pipeline (`row_11`,
`row_16` initially failed the live relevance gate on first pass; reworded to share real
article vocabulary and re-verified). Five representative examples, with the rule each one
broke:

1. **Row 1** (Email server). Rejected: *"My Galaxy screen flashes and goes blank whenever I
   check my email."* -- reintroduces the original unsupported display symptom the article
   never addresses (rules A/E: wrong intent, new unsupported cause).
2. **Row 5** (Smart Switch transfer). Rejected: *"My screen goes blank every time I try to
   scan a QR code with Smart Switch."* -- reintroduces "blank screen" as a QR-scan blocker,
   a failure mode the article never discusses; it only explains the normal working flow
   (rule E: no new cause).
3. **Row 8** (Screen mirroring). Rejected: *"My phone's screen is small and won't fill the
   display."* -- drops the TV-mirroring context the article requires, making it
   indistinguishable from an on-device sizing problem the article does not cover (rule D:
   same context).
4. **Row 12** (Multi Window / Edge panel). Rejected: *"How do I remove the floating
   navigation circle from my screen?"* -- this is verbatim the original unsupported entity
   (an Assistant-Menu-style floating shortcut); Multi Window never discusses one (rule A/E).
5. **Row 20** (Screen rotation). Rejected: *"My screen colors look distorted and washed
   out."* -- reintroduces the original unsupported "visual distortion" symptom; the article
   is about auto-rotate/orientation only (rule C: same symptom).

## 8. Domain/category coverage

All 20 rows fall within the PDF's "Display" domain; the 11 unique classes are: Email
connectivity, Blank/black display (6 rows), Data-access-when-unresponsive (3 rows), Smart
Switch transfer, Multi Window/App pairs (2 rows), Screen mirroring, Camera video flicker,
Cracked/bleeding screen (2 rows), Screen rotation, Touchscreen issues. Battery, Camera
(device-level, not just video flicker), and Performance are not represented in the official
20 rows at all -- a pre-existing, separately documented gap (`docs/domain-coverage.md`),
out of scope for this task, which only audits and corrects the official rows as given.

## 9. Remaining ambiguous rows

- **row_17**: an unmodified, genuinely ALIGNED query that still fails the live app's lexical
  relevance gate, exactly as it did before this audit. Left untouched rather than reworded
  to game an unrelated heuristic; documented as a pipeline limitation, not a dataset defect.
- **row_5**: the reframing (from "screen blank during QR scan" to "QR transfer not
  completing") is a reasonable but debatable choice of which real, article-supported failure
  mode best preserves the original complaint's spirit.
- **row_11**: the correction ("part of the touchscreen is black and unresponsive") is
  faithful to the article's own vocabulary but necessarily loses some of the original
  query's specificity ("half the screen, one side vs. the other").

## 10. Suitable for embedding fine-tuning?

**Conditionally yes, for a small/careful adaptation -- not for training from scratch.** The
dataset is now internally consistent, class-grounded, and leakage-free, but small: 11
classes, 180 texts, several classes with only one row's worth of held-out material. Combine
with the existing Battery/Camera/Performance test fixture from prior work
(`tests/fixtures/domain_articles.json`) before any real fine-tuning run, and treat `row_19`
(the confirmed Cracked-vs-Access-data confusion, section 11 below) as the first hard
negative to include.

## 11. Suitable for evaluation?

**Yes.** The baseline benchmark (`docs/siis_paraphrase_baseline_benchmark.md`), run with the
current, non-fine-tuned embedding model and a cache seeded only from train-role texts,
produced a credible and informative result:

| Split | N | Recall@1 | Recall@3 | Recall@5 | MRR |
| --- | --- | --- | --- | --- | --- |
| val | 32 | 75.0% | 96.9% | 96.9% | 0.833 |
| test | 55 | 87.3% | 100% | 100% | 0.936 |

(Test N is 55, not 64, because `row_17`'s 9 texts are excluded -- there is no valid target
plan to score against for a gated row.) Schema/rule validation pass rate: 95% (19/20).
Exact deeplink accuracy and auto-action screen-resolution rate (catalog membership): 100%.

The one real, reproducible failure mode found is `row_19` (Cracked/bleeding screen,
held-out): its canonical query and 5 of its 6 remaining paraphrases were retrieved as
"Access phone's data" or "Device issue" instead, because its multi-symptom wording ("touch
doesn't work," "can hardly see anything") genuinely overlaps with that other class's
vocabulary. This is documented as the top hard negative in `docs/siis_hard_negatives.md`.

## 12. Remaining data limitations

- Only 20 official rows / 11 classes. Some test-split classes have as few as one row's
  worth of paraphrases; treat the percentages above as indicative, not statistically
  representative of production traffic.
- Battery, Camera (device-level), and Performance domains are not represented in the
  official data at all (see section 8).
- The live app's lexical relevance gate (a separate component from this dataset) still has
  one known false negative (`row_17`). A side benefit of this task: the gate's two
  previously-documented false positives (rows 7 and 12, `docs/domain-coverage.md`) are now
  resolved, because those rows' queries were corrected to match articles they genuinely fit.
- `scripts/validate_data.py` is a pre-existing, unrelated bootstrap-era script that checks
  for filenames (`queries.json`, `responses.json`) that were never the actual official
  filenames; it reports them missing regardless of this work and was not touched.
- Paraphrases are author-written English, not collected from real Samsung customers. They
  are correctly aligned to real Samsung troubleshooting content (unlike an external intent
  dataset, which was not used anywhere in this task), but "aligned and grounded" is not the
  same claim as "collected from the field."

## Examples

### 5 corrected bad queries (before -> after)

1. **row_1**: "My Samsung A115G tablet screen flashes and then goes completely blank
   whenever I tap to open an email in Gmail..." -> "My email keeps saying the server isn't
   responding and my messages won't load on my Samsung tablet."
2. **row_8**: "My new Samsung phone's main screen stays small and doesn't fill the whole
   display..." -> "When I mirror my phone to my Samsung TV with Smart View, the image looks
   small and doesn't fill the whole TV screen."
3. **row_12**: "My Galaxy S25 has a floating circle that constantly hovers on my screen and
   gives me quick shortcuts..." -> "I want to remove an app pair shortcut from the Edge
   panel on my Galaxy phone."
4. **row_20**: "My Galaxy A17 screen looks distorted right after I received the phone, and I
   need a diagnostic test." -> "My Galaxy A17's screen won't rotate to landscape when I turn
   the phone sideways."
5. **row_22**: "...even though the phone powers on, rings, and otherwise works; there is no
   physical damage." -> "My Galaxy S24 Ultra's screen is completely black and won't turn on,
   and there's no physical damage to the phone." (drops the self-contradicting "powers on,
   rings, otherwise works" clause; keeps the "no physical damage" detail, which the article
   does address.)

### 5 high-quality paraphrase groups

**row_10** (canonical: "My Galaxy phone's camera video has a flickering line or band,
especially when I record indoors under fluorescent or LED lighting."):
- "There's a flickering band that shows up in my videos when I film inside under the lights."
- "My camera footage keeps flickering like a black bar moving across the screen when I record indoors."
- "Video flickers under indoor lighting."
- "Why does my camera video flicker when I record under LED or fluorescent lighting?"
- "Every video I take indoors has this annoying flicker running through it, I can't figure out why."
- "My camera app produces a strobing artifact in footage captured under artificial indoor lighting."

**row_19** (canonical, ALIGNED/multi-symptom: "My Galaxy Z Flip 7 screen is cracked again
right at the fold, touch doesn't work on certain parts of the screen, and I can hardly see
anything on the display."):
- "My fold screen cracked again, touch is dead in some spots, and I can barely see anything."
- "This is the second time it's cracked right at the fold, and now touch barely works and I can hardly see anything!"
- "The panel has fractured again at the hinge, with unresponsive touch zones and degraded visibility."

**row_21** (canonical: "My Galaxy S22 screen inputs are delayed and the touch
responsiveness is laggy..."):
- "My touchscreen feels laggy, there's a delay every time I tap something."
- "Every tap takes forever to register, this touch delay is driving me crazy."
- "So my screen just feels really sluggish, like there's always a delay before it reacts to my taps."

**row_14** (canonical, ALIGNED: "My Galaxy phone's screen is completely cracked..."):
- "My screen's totally busted, cracked all over, can't do anything with the phone now."
- "What are my options for repair since my screen is completely cracked?"
- "So I dropped my phone and now the screen's a total crack, can't really use it like this."

**row_1** (canonical, corrected: "My email keeps saying the server isn't responding..."):
- "This is so annoying, my email has been stuck saying 'server not responding' for hours."
- "My mail client can't reach the email server, so my inbox won't refresh."
- "So my email just stopped working, it keeps telling me the server won't respond."

### 5 rejected paraphrases and why

See section 7 above.

## Files created

- `docs/siis_alignment_audit.md`
- `docs/siis_hard_negatives.md`
- `docs/siis_paraphrase_baseline_benchmark.md` (generated by `scripts/benchmark_paraphrase_dataset.py`)
- `docs/siis_dataset_quality_report.md` (this file)
- `scripts/build_paraphrase_dataset.py`
- `scripts/benchmark_paraphrase_dataset.py`
- `data/processed/siis_paraphrase_dataset.json` (generated, git-ignored)
- `tests/test_paraphrase_dataset_quality.py`

## Files modified

- `app/services/plan_cache.py` -- added `top_matches()` (Recall@k/MRR ranking) and
  `add_lookup_keys()` (extra evaluation keys separate from the official `query_variations`
  schema field), each added via a failing test first.
- `tests/test_plan_cache.py` -- tests for the two additions above.

## Files never touched

- `data/original/siis_responses.json` (source of truth, read-only throughout)
- `data/original/deeplinks.json`, `schema.py`, `sample_output.json`, `input.txt`
