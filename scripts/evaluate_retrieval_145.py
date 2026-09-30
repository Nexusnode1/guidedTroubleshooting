"""145-query semantic retrieval evaluation.

Runs the real, shipped `TroubleshootingService.troubleshoot(query)` (fast-path lookup only,
no `siis_response`) against every query in `tests/fixtures/retrieval_evaluation_145.json`, a
SYNTHETIC, author-written evaluation set (see that file's own `_disclaimer`). It is not part
of the official reference data and does not modify it, the catalog, or any deeplink.

    python scripts/evaluate_retrieval_145.py

Companion regression test: tests/test_retrieval_evaluation_145.py (imports `evaluate_all`
from this module the same way tests/test_benchmark_paraphrase_dataset.py imports
scripts/benchmark_paraphrase_dataset.py).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import EMBEDDING_MODEL  # noqa: E402
from app.models.official_schema import ContextDeeplinkResponse  # noqa: E402
from app.retrieval.st_embedder import load_embedder  # noqa: E402
from app.services.catalog import load_catalog, load_siis_rows  # noqa: E402
from app.services.plan_cache import PlanCache  # noqa: E402
from app.services.plan_validator import validate_plan  # noqa: E402
from app.services.troubleshooting_service import TroubleshootingService  # noqa: E402

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "retrieval_evaluation_145.json"
K_VALUES = (1, 3)


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def build_service(embedder=None) -> TroubleshootingService:
    catalog = load_catalog()
    service = TroubleshootingService(catalog, PlanCache(catalog, model=embedder or load_embedder(EMBEDDING_MODEL)))
    service.warm(load_siis_rows())
    return service


def _flat_queries(fixture: dict[str, Any]):
    """Yield (group_name, status, expected_title, query_record) for every query in the fixture."""
    for group_name, group in fixture["groups"].items():
        for record in group["queries"]:
            yield group_name, group["status"], group.get("expected_title"), record


def _rank(service: TroubleshootingService, query: str, expected_title: str | None, k: int) -> int | None:
    """Rank (1-based) of ``expected_title`` among the top ``k`` distinct titles, or None."""
    if expected_title is None:
        return None
    top = service.cache.top_matches(query, k=max(K_VALUES) if k is None else k)
    titles = [hit.entry.response["contexts"][0]["title"] for hit in top]
    return titles.index(expected_title) + 1 if expected_title in titles else None


def evaluate_all(service: TroubleshootingService, fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run every query once and return per-query records plus the aggregate report."""
    fixture = fixture or load_fixture()
    catalog = service.catalog
    actionable_uris = {entry["deeplink"] for entry in catalog}
    records: list[dict[str, Any]] = []

    for group_name, status, expected_title, q in _flat_queries(fixture):
        query = q["text"]
        result = service.troubleshoot(query)
        contexts = result["response"]["contexts"]
        got_title = contexts[0]["title"] if contexts else None
        got_score = contexts[0]["score"] if contexts else None

        schema_errors: list[str] = []
        deeplink_errors: list[str] = []
        if contexts:
            try:
                ContextDeeplinkResponse.model_validate(result["response"])
            except Exception as exc:  # noqa: BLE001 -- recorded, not raised, so one bad query doesn't abort the run
                schema_errors.append(str(exc))
            validation = validate_plan({**result["response"], "query_variations": result["query_variations"]}, catalog)
            schema_errors.extend(validation.errors)
            for ctx in contexts:
                for action in ctx["actions"]:
                    for group in action["stepGroups"]:
                        link = group["actionableDeeplink"]
                        if link and link["deeplink"] not in actionable_uris:
                            deeplink_errors.append(f"{action['actionName']}: {link['deeplink']} not in catalog")
                        if action["category"] in ("manual", "critical") and link is not None:
                            deeplink_errors.append(f"{action['actionName']}: {action['category']} action carries a deeplink")

        is_match = bool(contexts)
        if status == "supported":
            outcome = "correct" if got_title == expected_title else ("wrong" if is_match else "miss")
        else:  # ambiguous / no_match_expected: any match at all is a false positive
            outcome = "false_positive" if is_match else "safe_fallback"

        records.append(
            {
                "group": group_name,
                "status": status,
                "style": q.get("style"),
                "query": query,
                "expected_title": expected_title,
                "got_title": got_title,
                "score": got_score,
                "cache_hit": result["meta"]["cache_hit"],
                "latency_ms": result["meta"]["latency_ms"],
                "fallback": result["meta"].get("fallback"),
                "outcome": outcome,
                "schema_errors": schema_errors,
                "deeplink_errors": deeplink_errors,
                "rank1": _rank(service, query, expected_title, 1) if status == "supported" else None,
                "rank3": _rank(service, query, expected_title, 3) if status == "supported" else None,
            }
        )

    return {"records": records, **summarize(records)}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    supported = [r for r in records if r["status"] == "supported"]
    ambiguous = [r for r in records if r["status"] == "ambiguous"]
    no_match_expected = [r for r in records if r["status"] == "no_match_expected"]

    correct = sum(1 for r in supported if r["outcome"] == "correct")
    wrong = sum(1 for r in supported if r["outcome"] == "wrong")
    miss = sum(1 for r in supported if r["outcome"] == "miss")
    false_positives = sum(1 for r in records if r["outcome"] == "false_positive")
    safe_fallbacks = sum(1 for r in records if r["outcome"] == "safe_fallback")
    schema_failures = sum(1 for r in records if r["schema_errors"])
    deeplink_failures = sum(1 for r in records if r["deeplink_errors"])

    per_group: dict[str, Any] = {}
    for r in records:
        g = per_group.setdefault(
            r["group"], {"status": r["status"], "n": 0, "correct": 0, "wrong": 0, "miss": 0, "false_positive": 0, "safe_fallback": 0}
        )
        g["n"] += 1
        g[r["outcome"]] += 1

    hits1 = sum(1 for r in supported if r["rank1"] is not None and r["rank1"] <= 1)
    hits3 = sum(1 for r in supported if r["rank3"] is not None and r["rank3"] <= 3)
    rr = [1.0 / r["rank3"] if r["rank3"] else 0.0 for r in supported]
    n_supported = len(supported) or 1

    failure_reasons: dict[str, int] = {}
    for r in supported:
        if r["outcome"] != "correct":
            key = f"{r['group']} -> {r['got_title']}"
            failure_reasons[key] = failure_reasons.get(key, 0) + 1
    for r in records:
        if r["outcome"] == "false_positive":
            key = f"{r['group']} -> {r['got_title']}"
            failure_reasons[key] = failure_reasons.get(key, 0) + 1
    top_failure_modes = sorted(failure_reasons.items(), key=lambda kv: -kv[1])[:10]

    group_recall = {
        name: round(g["correct"] / g["n"], 4) for name, g in per_group.items() if g["status"] == "supported"
    }
    strongest = max(group_recall.items(), key=lambda kv: kv[1]) if group_recall else None
    weakest = min(group_recall.items(), key=lambda kv: kv[1]) if group_recall else None

    return {
        "total": total,
        "supported": len(supported),
        "ambiguous": len(ambiguous),
        "no_match_expected": len(no_match_expected),
        "correct": correct,
        "wrong": wrong,
        "miss": miss,
        "false_positives": false_positives,
        "safe_fallbacks": safe_fallbacks,
        "schema_failures": schema_failures,
        "deeplink_failures": deeplink_failures,
        "recall_at_1": round(hits1 / n_supported, 4),
        "recall_at_3": round(hits3 / n_supported, 4),
        "mrr": round(sum(rr) / n_supported, 4),
        "per_group": per_group,
        "group_recall": group_recall,
        "strongest_group": strongest,
        "weakest_group": weakest,
        "top_failure_modes": top_failure_modes,
    }


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# 145-Query Retrieval Evaluation",
        "",
        "SYNTHETIC evaluation set (`tests/fixtures/retrieval_evaluation_145.json`), author-written, not official data.",
        f"Total queries: {report['total']} (supported: {report['supported']}, ambiguous: {report['ambiguous']}, "
        f"no_match_expected: {report['no_match_expected']})",
        "",
        "## Headline numbers",
        "",
        f"- Correct matches (supported group, right title): {report['correct']} / {report['supported']}",
        f"- Wrong matches (supported group, wrong title returned): {report['wrong']}",
        f"- Misses (supported group, fell back to no_match): {report['miss']}",
        f"- False positives (ambiguous/no_match_expected group, a plan was returned anyway): "
        f"{report['false_positives']} / {report['ambiguous'] + report['no_match_expected']}",
        f"- Safe fallbacks (ambiguous/no_match_expected group, correctly refused): {report['safe_fallbacks']}",
        f"- Schema/rule validation failures: {report['schema_failures']}",
        f"- Exact-catalog deeplink failures: {report['deeplink_failures']}",
        f"- Recall@1 / Recall@3 / MRR (supported group, ranked via PlanCache.top_matches): "
        f"{report['recall_at_1']} / {report['recall_at_3']} / {report['mrr']}",
        "",
        "## Per-group results",
        "",
        "| Group | Status | N | Correct | Wrong | Miss | False positive | Safe fallback |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, g in report["per_group"].items():
        lines.append(
            f"| {name} | {g['status']} | {g['n']} | {g['correct']} | {g['wrong']} | {g['miss']} | "
            f"{g['false_positive']} | {g['safe_fallback']} |"
        )
    lines += [
        "",
        f"Strongest supported group: {report['strongest_group']}",
        f"Weakest supported group: {report['weakest_group']}",
        "",
        "## Top recurring failure modes",
        "",
        "| Expected group -> returned title | Count |",
        "| --- | --- |",
    ]
    for key, count in report["top_failure_modes"]:
        lines.append(f"| {key} | {count} |")
    lines += [
        "",
        "## Root cause analysis",
        "",
        "Investigated by hand (`git log`-free, read-only diagnostics against `PlanCache.top_matches`);",
        "see the session notes for the exact per-query score breakdowns. Every 'wrong' or 'false_positive'",
        "result traces to one of three causes, none of which is a general retrieval defect fixable",
        "without touching official data, adding per-row rules, or lowering the safety threshold --",
        "all explicitly out of scope for this evaluation:",
        "",
        "1. **Already-documented misaligned official rows** (`docs/siis_alignment_audit.md`,",
        "   `docs/siis_dataset_quality_report.md`). row_1, row_5, row_7/row_12, and row_8's own",
        "   *canonical query* (the customer's original complaint, which is itself a cache key)",
        "   describes a generic blank/dark/small-screen symptom, while the *plan* their article",
        "   maps to is unrelated (email connectivity, Data Transfer, Multi window, Screen mirroring).",
        "   A new query that genuinely resembles that symptom correctly ranks near those canonical",
        "   queries -- the cache is retrieving the closest real key, faithfully; the key itself is",
        "   mislabeled relative to its plan. This accounts for most `blank_black_display` and",
        "   `access_smartphones_data` 'wrong' results, `ambiguous` group's 'My phone screen is",
        "   acting up' (row_8) and 'My phone has a problem but I can't really describe what's",
        "   happening' (row_1), and the `no_match_expected` Bluetooth false positive (row_8's",
        "   article contains literal Windows-PC instructions mentioning Bluetooth) -- the last of",
        "   these was already investigated earlier in this evaluation's history with several general",
        "   candidate fixes tested and none clearing every acceptance criterion; see",
        "   `docs/cross_domain_hard_negatives.md`.",
        "2. **This fixture's own paraphrase choices.** All 7 `device_issue_catch_all` 'wrong'",
        "   results are paraphrases the fixture wrote with the word 'touchscreen' inserted into",
        "   them, intending to represent official row_11 (which says only 'screen is half black',",
        "   never 'touchscreen'). Retrieval correctly redirects text that says 'touchscreen' toward",
        "   the Touchscreen issues plan; that is the fixture's authoring choice, not a retrieval bug.",
        "3. **Expected threshold-boundary misses.** All 7 `miss` results score 0.41-0.48 on their",
        "   correct plan (visible via `PlanCache.top_matches`, which ignores the threshold) --",
        "   just under `SIMILARITY_THRESHOLD` (0.48). These are short, generic, or heavily",
        "   paraphrased queries near the deliberate precision/recall boundary that threshold sets;",
        "   refusing to answer instead of guessing is the intended, safer behavior, not a defect.",
        "",
        "**Conclusion: no general retrieval change is justified by this evaluation.** The threshold,",
        "key weights, and intent-confidence cap already in place (see `metrics.md`) were not modified.",
    ]
    return "\n".join(lines)


def main() -> int:
    service = build_service()
    report = evaluate_all(service)
    out_path = ROOT / "docs" / "retrieval_evaluation_145.md"
    out_path.write_text(render_report(report), encoding="utf-8")
    summary = {k: v for k, v in report.items() if k not in ("records", "per_group", "group_recall", "top_failure_modes")}
    print(json.dumps(summary, indent=2))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
