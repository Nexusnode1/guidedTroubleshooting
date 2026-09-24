# SIIS Query/Article Alignment Audit

Date: 2026-09-22. Read-only audit of `data/original/siis_responses.json` (byte-identical to
`../student_kit/siis_responses.json`) against `schema.py`, `sample_output.json`,
`deeplinks.json`, and every consumer of the file (`app/services/catalog.py`,
`scripts/benchmark.py`, `tests/test_official_data.py`, `tests/test_domain_generalization.py`).
No files were modified to produce this audit.

## Method

For every row: read the SIIS `title` and `content` as the authoritative troubleshooting
knowledge, determine the actual intent/symptom/context/supported actions the article
addresses, then judge whether `original_query` describes that same problem.

- **ALIGNED** — the query's symptom, entity, and context match what the article actually
  troubleshoots.
- **PARTIALLY_ALIGNED** — the domain/action matches, but the query claims a specific
  symptom or failure mode the article does not actually address.
- **MISALIGNED** — the article does not address the query's problem at all, or directly
  contradicts it.

## Findings

| row_id | current_query_summary | SIIS_title | alignment | reason |
| --- | --- | --- | --- | --- |
| row_1 | Screen flashes/blanks when opening Gmail | Email server not responding | MISALIGNED | Article is pure email-connectivity troubleshooting (Wi-Fi, cache, safe mode, contact provider); never addresses a display symptom. |
| row_2 | Screen blank/white, no text, while searching a stock price or using an app | Blank or black display | MISALIGNED | Query describes a device that is on and interactive with a rendering/app problem; article's flow (check damage, force restart, charge) is for a device that will not power on at all. |
| row_3 | Z Flip 7 fully black, unresponsive, need Smart Switch | Some things to check first | ALIGNED | Matches the article's own "access data via USB mouse when screen is blank" + force-restart content. |
| row_4 | A15/A16 went black on its own, no display even trying to turn on | Blank or black display | ALIGNED | Squarely the "device not turning on" scenario. |
| row_5 | Screen blank during Smart Switch QR scan, transfer can't proceed | Transfer Secure folder with Smart Switch | PARTIALLY_ALIGNED | Action/domain matches; "screen stays blank" is not a failure mode the article discusses — it explains the normal working flow only. |
| row_7 | Screen mostly dark, only 3 icons lit, apps won't open | Use Multi window and App pairs | MISALIGNED | A feature how-to for split screen/app pairs/Edge panel, unrelated to a mostly-dark screen. |
| row_8 | Phone's own screen stays small, doesn't fill display | Screen mirroring to your Samsung TV | MISALIGNED | Article is about mirroring/casting to a TV, not the phone's native display (it does have an "image looks small" remedy, but only in the TV-mirroring context). |
| row_9 | Flip 7 inner screen dead (no image, no touch), outer screen fine | Access your Galaxy phone's data if the screen does not respond | ALIGNED | Matches "touchscreen doesn't work" / "nothing visible on screen" directly; foldable detail is device context, not a new symptom. |
| row_10 | Flip 6 screen flickers/blanks when opening (unfolding) it | Screen flickers when using the Camera | MISALIGNED | Article is specifically camera-video flicker from lighting frequency, not a general system display flicker. |
| row_11 | Flip 6 half the screen black, other half fine | Some things to check first | PARTIALLY_ALIGNED | General "screen not working" domain matches; "half black" is a more specific defect the article's generic remedies don't target. |
| row_12 | Persistent floating circle with shortcuts | Use Multi window and App pairs | MISALIGNED | Described feature is an Assistant-Menu-style floating shortcut, not Multi Window/App pairs. |
| row_13 | Blank screen, no activation message, after carrier deactivated old phone | Blank or black display | ALIGNED | "No display at power-up" matches the article; carrier-swap detail is device context. |
| row_14 | Screen totally cracked | Cracked or bleeding screen | ALIGNED | Direct match. |
| row_15 | Blue/black screen with tiny text, won't start, power button doesn't help | Blank or black display | ALIGNED | "Won't start up" boot failure matches the article's domain. |
| row_16 | Momentary flash when plugging in a charger | Blank or black display | MISALIGNED | A brief flash on an apparently functioning device is a different failure class from "won't power on at all." |
| row_17 | Dark screen, occasional scrolling, no content, can't use Smart Switch | Some things to check first | ALIGNED | Matches the article's blank-screen/data-access/force-restart content. |
| row_19 | Cracked at fold again; touch dead in spots; can barely see | Cracked or bleeding screen | ALIGNED | All three symptoms consistent with physical screen damage. |
| row_20 | Screen looks distorted, wants a diagnostic | Screen does not rotate | MISALIGNED | Article is about auto-rotate/orientation failing, a different symptom from visual distortion. |
| row_21 | Touch input delayed/laggy | Touchscreen issues | ALIGNED | Direct match. |
| row_22 | Screen black/won't turn on, but phone powers on, rings, otherwise works, no damage | Blank or black display | MISALIGNED | Query explicitly states the device is on and functioning, directly contradicting the article's "won't power on at all" premise — a keyword-overlap trap ("black," "won't turn on"). |

## Totals

9 ALIGNED, 2 PARTIALLY_ALIGNED, 9 MISALIGNED (of 20 audited).

## What this explains

Rows 7, 8, 12, 16, and 20 are exactly the rows that behaved oddly in earlier pipeline
smoke-testing (thin or low-relevance plans, or refused by the lexical relevance gate) — the
issue traced back to the source data pairing, not the pipeline code, for most of them.

## A second, separate finding: the live app's lexical relevance gate

Building the corrected dataset surfaced a distinct issue in `app/services/relevance.py`
(the gate the *live app* uses to refuse an article that doesn't fit a query, unrelated to
this dataset's own correctness): it is pure bag-of-words overlap, so a genuinely correct
query can still be refused if its wording doesn't happen to share the article's specific
vocabulary. Two corrected rows (`row_11`, `row_16`) initially failed this gate even though
their canonical query was already an honest, grounded description of what the article
covers -- fixed by choosing wording that uses words the article itself actually contains
("black," "touchscreen," "restart") rather than paraphrasing them away. `row_17`, an
**unmodified, already-ALIGNED** original query, still fails this same gate: it did so with
its original wording before this audit too (see the `scripts/build_plans.py` warm-up log
from prior work), so it is left untouched here rather than reworded just to satisfy an
unrelated heuristic. This is documented as a known limitation, not fixed in this task: see
`docs/siis_dataset_quality_report.md` and the existing note in `docs/domain-coverage.md`.

## What corrections do

See `scripts/build_paraphrase_dataset.py` and `data/processed/siis_paraphrase_dataset.json`
for the corrected canonical queries and generated paraphrases. Corrections reframe the query
to describe what the paired article actually addresses; they never touch `siis_response`
content itself, and `data/original/siis_responses.json` is never modified.
