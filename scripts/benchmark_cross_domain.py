"""Cross-domain generalization benchmark: SYNTHETIC DOMAIN GENERALIZATION FIXTURE.

Runs the real, shipped pipeline end to end -- TroubleshootingService.troubleshoot(query,
siis_response=...) -- against tests/fixtures/cross_domain_articles.json (16 author-written
Battery/Camera/Performance articles; see that file's own _disclaimer). Does not fine-tune
anything and does not create a second, parallel matching implementation: retrieval metrics
reuse PlanCache.top_matches on the exact cache the service itself populates as a side effect
of the cold-path call, the same technique scripts/benchmark_paraphrase_dataset.py uses.

Pipeline stages exercised by the cold call (see docs/cross_domain_generalization.md for what
each corresponds to): query enrichment/normalisation, structure extraction, the relevance
gate, exact-label deeplink matching, action ordering, and the validation firewall. There is
no separate BM25+dense retrieval stage in the shipped architecture for deeplink mapping (see
the design spec's documented deviation); this script does not pretend otherwise.

    python scripts/benchmark_cross_domain.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import EMBEDDING_MODEL  # noqa: E402
from app.retrieval.st_embedder import load_embedder  # noqa: E402
from app.services.catalog import load_catalog  # noqa: E402
from app.services.plan_cache import PlanCache  # noqa: E402
from app.services.troubleshooting_service import TroubleshootingService  # noqa: E402

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "cross_domain_articles.json"
K_VALUES = (1, 3, 5)
DUMMY = "bixby://dummy_positive"


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def run_cold_pipeline(service: TroubleshootingService, catalog_ids: dict[str, str], article: dict[str, Any]) -> dict[str, Any]:
    """Call the real troubleshoot(query, siis_response=...) once and record full diagnostics."""
    result = service.troubleshoot(article["canonical_query"], siis_response=article["content"])
    contexts = result["response"]["contexts"]
    record: dict[str, Any] = {
        "fixture_id": article["fixture_id"],
        "domain": article["domain"],
        "query": article["canonical_query"],
        "expected_deeplink_ids": article["expected_deeplink_ids"],
        "schema_valid": bool(contexts),
        "failure_reason": result["meta"].get("fallback"),
        "resolved_title": None,
        "resolved_deeplink_ids": [],
        "categories": [],
    }
    if contexts:
        goal = contexts[0]
        record["resolved_title"] = goal["title"]
        for action in goal["actions"]:
            record["categories"].append(action["category"])
            for group in action["stepGroups"]:
                link = group["actionableDeeplink"]
                if not link:
                    continue
                record["resolved_deeplink_ids"].append(
                    "PLACEHOLDER" if link["deeplink"] == DUMMY else catalog_ids.get(link["deeplink"], "UNKNOWN")
                )
    real_hits = {d for d in record["resolved_deeplink_ids"] if d not in ("PLACEHOLDER", "UNKNOWN")}
    expected = set(article["expected_deeplink_ids"])
    record["deeplink_match"] = bool(real_hits & expected) if expected else not real_hits
    record["ordering_ok"] = record["categories"] == sorted(record["categories"], key={"auto": 0, "manual": 1, "critical": 2}.get)
    return record


def eval_retrieval(cache: PlanCache, fixture: dict[str, Any], per_domain: dict[str, list]) -> None:
    """Query every paraphrase against the cache the cold calls already populated."""
    for article in fixture["articles"]:
        for paraphrase in article["paraphrases"]:
            top = cache.top_matches(paraphrase, k=max(K_VALUES))
            titles = [hit.entry.response["contexts"][0]["title"] for hit in top]
            expected_title = None
            for entry in cache.entries():
                if entry.query == article["canonical_query"]:
                    expected_title = entry.response["contexts"][0]["title"]
                    break
            rank = titles.index(expected_title) + 1 if expected_title in titles else None
            row = {"rank": rank, "domain": article["domain"], "fixture_id": article["fixture_id"], "query": paraphrase, "top1": titles[:1]}
            per_domain.setdefault(article["domain"], []).append(row)
            per_domain.setdefault("combined", []).append(row)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    hits = {k: sum(1 for r in rows if r["rank"] is not None and r["rank"] <= k) for k in K_VALUES}
    rr = [1.0 / r["rank"] if r["rank"] is not None else 0.0 for r in rows]
    return {
        "n": total,
        **{f"recall@{k}": round(hits[k] / total, 4) if total else 0.0 for k in K_VALUES},
        "mrr": round(sum(rr) / total, 4) if total else 0.0,
    }


def main() -> int:
    fixture = load_fixture()
    catalog = load_catalog()
    catalog_ids = {e["deeplink"]: e["id"] for e in catalog if e["id"] != "DL-DUMMY"}
    service = TroubleshootingService(catalog, PlanCache(catalog, model=load_embedder(EMBEDDING_MODEL)))

    pipeline_records = [run_cold_pipeline(service, catalog_ids, article) for article in fixture["articles"]]

    per_domain: dict[str, list] = {}
    eval_retrieval(service.cache, fixture, per_domain)

    domains = ["Battery", "Camera", "Performance"]
    metrics = {domain: summarize(per_domain.get(domain, [])) for domain in domains}
    metrics["combined"] = summarize(per_domain.get("combined", []))

    schema_pass = sum(1 for r in pipeline_records if r["schema_valid"])
    deeplink_ok = sum(1 for r in pipeline_records if r["deeplink_match"])
    failures = [r for r in pipeline_records if not r["schema_valid"] or not r["deeplink_match"]]

    lines = [
        "# Cross-Domain Generalization Benchmark",
        "",
        "**SYNTHETIC DOMAIN GENERALIZATION FIXTURE.** Author-written Battery/Camera/Performance",
        "articles (see tests/fixtures/cross_domain_articles.json), run through the real",
        "TroubleshootingService.troubleshoot(query, siis_response=...) pipeline. This is a",
        f"small (N={len(fixture['articles'])} articles, {sum(len(a['paraphrases']) for a in fixture['articles'])} paraphrases) fixture meant to",
        "expose domain-specific failure modes, not to make a statistically representative claim.",
        "No fine-tuning was performed; embedding model, threshold, and retrieval weights are",
        f"unchanged (`{service.cache.embedder_name}`).",
        "",
        "## Retrieval metrics (paraphrases matched against the cache the cold calls populated)",
        "",
        "| Domain | N | Recall@1 | Recall@3 | Recall@5 | MRR |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for domain in [*domains, "combined"]:
        m = metrics[domain]
        lines.append(f"| {domain} | {m['n']} | {m['recall@1']} | {m['recall@3']} | {m['recall@5']} | {m['mrr']} |")

    lines += [
        "",
        "## Pipeline diagnostics (cold path, one call per article)",
        "",
        f"- Schema/rule validation pass rate: {schema_pass}/{len(pipeline_records)} "
        f"({schema_pass / len(pipeline_records):.0%})",
        f"- Deeplink accuracy (resolved id in the article's own verified expected set, or "
        f"correctly no real deeplink where none should exist): {deeplink_ok}/{len(pipeline_records)} "
        f"({deeplink_ok / len(pipeline_records):.0%})",
        f"- Genuine pipeline failures/limitations found: {len(failures)}",
        "",
        "| fixture_id | domain | resolved title | resolved deeplinks | expected | match | ordering ok |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in pipeline_records:
        lines.append(
            f"| {r['fixture_id']} | {r['domain']} | {r['resolved_title']} | "
            f"{', '.join(r['resolved_deeplink_ids']) or '(none)'} | {', '.join(r['expected_deeplink_ids']) or '(none)'} | "
            f"{'yes' if r['deeplink_match'] else 'NO'} | {'yes' if r['ordering_ok'] else 'NO'} |"
        )

    lines += [
        "",
        "## Pipeline stage coverage",
        "",
        "| PDF-named stage | What actually runs | Exercised here |",
        "| --- | --- | --- |",
        "| Query Enrichment | `QueryEnricher`/`normalize_query` (via `generate_variations`/`PlanCache`) | yes |",
        "| Structure Extraction | `siis_parser.parse_sections`/`extract_steps` | yes |",
        "| Intent/Context | `relevance()` gate, `is_imperative` | yes |",
        "| BM25 + Dense Retrieval | **not present** -- deeplink mapping uses exact-label `KeyIndex` matching instead (documented architectural deviation, see the design spec) | n/a |",
        "| Screen Resolution / Deeplink Mapping | `KeyIndex.find()` | yes |",
        "| Action Ordering | `order_actions`/`ordered_values` | yes |",
        "| Validation Firewall | `validate_plan()` | yes |",
        "",
        "## Genuine findings from this run",
        "",
        "See `docs/cross_domain_hard_negatives.md` for observed retrieval confusions, and",
        "`app/services/key_matcher.py`'s `find()` docstring for the two known, deliberately-",
        "unfixed screen-resolution limitations this fixture surfaced: `performance_optimize_one_tap`",
        "resolving to the parent \"Battery\" screen instead of correctly giving up (a fix regressed",
        "official row_21 and was reverted), and the narrower, related case where a real key of the",
        "shape \"Restart on schedule\" is trimmed down to the excluded word \"Restart\" before an",
        "extended match is even attempted, falling back to the same \"Battery\" ancestor.",
        "",
        "Two other findings from this fixture *were* fixed, with regression tests and no",
        "official-row regression: \"turn it on\"/\"turn it off\" phrasing (an interposed word broke the",
        "old adjacency-strict regex, silently flipping toggle direction to the opposite of the",
        "instruction), and the critical-action classifier matching the word \"restart\" inside a",
        "catalog setting's own *name* (`performance_want_scheduled_restart`, \"Restart the device",
        "when needed\" -- a toggle, not an instruction to restart immediately) rather than the",
        "instruction text -- fixed by resolving the catalog match first, since the catalog only",
        "ever models View/Toggle/Update actions and never an immediate destructive one.",
        "",
        "## Limitations of this fixture",
        "",
        "- 16 articles, 5 paraphrases each: enough to expose failure modes, not enough for a",
        "  statistical claim about accuracy in any domain.",
        "- Author-written, not real Samsung customer language or real SIIS content.",
        "- The catalog has very limited true \"Camera app\" coverage (permission, feedback,",
        "  flash-as-notification, share-as-webcam only -- no photo quality/focus/HDR settings",
        "  exist at all), which this fixture surfaces rather than works around.",
    ]

    (ROOT / "docs" / "cross_domain_generalization.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"metrics": metrics, "schema_pass": f"{schema_pass}/{len(pipeline_records)}",
                       "deeplink_ok": f"{deeplink_ok}/{len(pipeline_records)}",
                       "failures": [f["fixture_id"] for f in failures]}, indent=2))
    print(f"wrote {ROOT / 'docs' / 'cross_domain_generalization.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
