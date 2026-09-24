# Domain coverage: Battery, Display, Camera, Performance

The PDF describes the dataset as spanning four device domains — Battery, Display, Camera,
and Performance — but every row in the official `data/original/siis_responses.json` (the
only official article data we were given) is a Display/screen complaint. Nothing in the
original test suite exercised the other three domains, which is exactly the kind of gap a
hidden evaluation set is likely to expose.

## What was added

`tests/fixtures/domain_articles.json` holds three short, **author-written** support
articles — one each for Battery, Camera, and Performance — clearly marked as such in the
fixture's own `_disclaimer` field. They are not presented as official Samsung content
anywhere, and they are never loaded into the app's live cache; the app still only ever
serves plans built from the official 20 rows. Their only job is to drive the same
`PlanBuilder`/`KeyIndex` code the official rows use, so a domain-specific bug shows up in
CI instead of during a demo. Every deeplink they resolve to is looked up in the real,
official `deeplinks.json` catalog by the same exact-label matching the official data uses
— nothing is fabricated.

`tests/test_domain_generalization.py` checks, for each article: the plan builds and
validates, actions are ordered auto → manual → critical, no URLs leak, and (as a locked-in
regression check) specific deeplinks resolve to the specific catalog entries they should.
A `@pytest.mark.acceptance` test also warms a small cache from these three articles and
confirms the paraphrase hit-rate target still holds outside Display, using a held-out set
(`tests/fixtures/paraphrases_domains.json`) written before the model or threshold was
touched.

## What this found

Building the Battery and Performance articles surfaced a real bug: the catalog key "Put
unused apps to sleep" contains the connector word "to", which the label-trimming regex
mistook for the start of a trailing clause ("...to disable it"), truncating the label to
"Put unused apps". The truncated label had no exact match, and the matcher silently fell
back to an earlier, shorter, unrelated label ("Battery") that did — returning a real but
wrong catalog entry rather than failing loudly. Fixed in `app/services/key_matcher.py` by
grounding the recovery in the untrimmed tap text itself (does it exactly equal or extend a
real catalog key?) rather than in catalog vocabulary alone, which was tried first and
rejected because it produced a different false positive ("Storage" matching the unrelated,
longer key "Storage Share"). See the two tests in `tests/test_key_matcher.py` added
alongside the fix, and `tests/test_domain_generalization.py::test_battery_plain_toggle_uses_the_view_variant_with_no_enable_wording`
/ `test_performance_explicit_enable_wording_uses_the_onurl_variant`, which lock in the
correct behavior so this cannot regress silently.

## What is still open

- Only one article and six held-out paraphrases per non-Display domain. This is enough to
  catch a class of bug, not enough to claim the same statistical confidence the Display
  numbers in `metrics.md` have.
- The article-relevance gate (`relevance.py`) and the paraphrase generator
  (`variations.py`) were exercised on these domains but not specifically hardened for
  them; if a hidden evaluation article uses very different phrasing, re-run
  `pytest tests/test_domain_generalization.py -m acceptance` first.
- If real Samsung SIIS articles for Battery/Camera/Performance become available, they
  belong in `data/original/` (immutable, official) and this synthetic fixture should
  shrink to cover only whatever gap remains.
