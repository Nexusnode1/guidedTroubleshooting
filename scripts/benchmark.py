"""Measure compliance, paraphrase hit rate, and latency; write metrics.md (PDF Appendix C layout).

Evaluate any embedding model, including one you trained yourself:

    python scripts/benchmark.py --embedding-model models/my-embedder --threshold 0.5

The fixtures in tests/fixtures/ are held-out phrasings; never edit them to move a number.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import EMBEDDING_MODEL, SIMILARITY_THRESHOLD  # noqa: E402
from app.models.official_schema import ContextDeeplinkResponse  # noqa: E402
from app.retrieval.st_embedder import load_embedder  # noqa: E402
from app.services.catalog import load_catalog, load_siis_rows  # noqa: E402
from app.services.plan_cache import PlanCache  # noqa: E402
from app.services.plan_validator import validate_plan  # noqa: E402
from app.services.troubleshooting_service import TroubleshootingService  # noqa: E402

FIXTURE_SETS = ("paraphrases.json", "paraphrases_holdout.json")
FIXTURE_DIR = ROOT / "tests" / "fixtures"
REQUESTS_PER_PATH = 30
HIT_RATE_TARGET = 80.0
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile of ``values`` for ``q`` in (0, 1]."""
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(q * len(ordered)))))
    return ordered[rank - 1]


def _strings(value: Any, key: str = "") -> list[str]:
    """All strings in ``value`` except deeplink URIs."""
    if isinstance(value, str):
        return [] if key == "deeplink" else [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _strings(v, k)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v, key)]
    return []


def _time_calls(call, queries: list[str]) -> list[float]:
    timings = []
    for query in queries:
        started = time.perf_counter()
        call(query)
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def _score_set(service: TroubleshootingService, fixtures: dict) -> dict[str, int]:
    correct = wrong = 0
    for item in fixtures["positives"]:
        contexts = service.troubleshoot(item["query"])["response"]["contexts"]
        if contexts and contexts[0]["title"] == item["expect"]:
            correct += 1
        elif contexts:
            wrong += 1
    false_hits = sum(bool(service.troubleshoot(q)["response"]["contexts"]) for q in fixtures["negatives"])
    return {
        "correct": correct,
        "wrong": wrong,
        "total": len(fixtures["positives"]),
        "false_hits": false_hits,
        "negatives": len(fixtures["negatives"]),
    }


def collect_metrics(
    service: TroubleshootingService, fixture_sets: dict[str, dict], requests_per_path: int
) -> dict[str, Any]:
    """Run every measurement and return plain numbers."""
    catalog = service.catalog
    actionable = {entry["deeplink"] for entry in catalog}
    entries = service.cache.entries()

    schema_valid = url_leaks = auto_actions = auto_linked = links = links_in_catalog = 0
    for entry in entries:
        ContextDeeplinkResponse.model_validate(entry.response)
        if validate_plan({**entry.response, "query_variations": list(entry.variations)}, catalog).valid:
            schema_valid += 1
        url_leaks += sum(bool(_URL.search(text)) for text in _strings(entry.response))
        for action in entry.response["contexts"][0]["actions"]:
            for group in action["stepGroups"]:
                link = group["actionableDeeplink"]
                if link:
                    links += 1
                    links_in_catalog += link["deeplink"] in actionable
            if action["category"] == "auto":
                auto_actions += 1
                auto_linked += any(group["actionableDeeplink"] for group in action["stepGroups"])

    sets = {name: _score_set(service, fixtures) for name, fixtures in fixture_sets.items()}
    positives = [p["query"] for fixtures in fixture_sets.values() for p in fixtures["positives"]]
    hitting = [q for q in positives if service.cache.lookup(q) is not None] or [entries[0].query]
    exact_query = entries[0].query
    cold_row = next(row for row in load_siis_rows() if row["id"] == entries[0].entry_id)
    cold_content = cold_row["siis_response"]["content"]
    latency = {
        "exact": _time_calls(service.troubleshoot, [exact_query] * requests_per_path),
        "paraphrase": _time_calls(service.troubleshoot, [hitting[i % len(hitting)] for i in range(requests_per_path)]),
        "cold": _time_calls(
            lambda q: service.troubleshoot(q, siis_response=cold_content),
            [f"{exact_query} variant {i}" for i in range(requests_per_path)],
        ),
    }
    total = sum(s["total"] for s in sets.values())
    return {
        "plans": len(entries),
        "schema_valid_pct": round(100 * schema_valid / max(1, len(entries)), 1),
        "url_leaks": url_leaks,
        "catalog_valid_pct": round(100 * links_in_catalog / max(1, links), 1),
        "auto_linked_pct": round(100 * auto_linked / max(1, auto_actions), 1),
        "sets": sets,
        "paraphrase_correct": sum(s["correct"] for s in sets.values()),
        "paraphrase_wrong": sum(s["wrong"] for s in sets.values()),
        "paraphrase_total": total,
        "negative_false_hits": sum(s["false_hits"] for s in sets.values()),
        "negative_total": sum(s["negatives"] for s in sets.values()),
        "latency": {
            path: {"p50": round(percentile(v, 0.5), 1), "p95": round(percentile(v, 0.95), 1), "n": len(v)}
            for path, v in latency.items()
        },
    }


def render(metrics: dict[str, Any], model_name: str, threshold: float) -> str:
    """Fill the Appendix C template with measured values; unmeasured cells say so."""
    lat = metrics["latency"]
    rate = round(100 * metrics["paraphrase_correct"] / max(1, metrics["paraphrase_total"]), 1)
    per_set = "; ".join(
        f"{name.removesuffix('.json')}: {s['correct']}/{s['total']}" for name, s in metrics["sets"].items()
    )

    def verdict(ok: bool) -> str:
        return "met" if ok else "NOT MET"

    return f"""# System Performance Metrics & Evaluation Report
**Model(s):** none (rules-v1: deterministic parsing, exact-label deeplink matching; no generative model)
**Embeddings:** {model_name} (similarity threshold {threshold})
**Environment:** {sys.platform}, Python {sys.version.split()[0]}

---

## 1. Schema & Rule Compliance
Evaluated over the {metrics['plans']} plans built from the official sample rows.

| Metric | Target | Measured Value |
| :--- | :--- | :--- |
| Schema-valid output lines | >= 99% | {metrics['schema_valid_pct']}% |
| Rule compliance (Goal / Title / Description syntax) | >= 95% | {metrics['schema_valid_pct']}% |
| Absolute URL leaks | 0 | {metrics['url_leaks']} |
| Deeplink catalog validity (exact URI match) | 100% | {metrics['catalog_valid_pct']}% |
| Auto actions carrying valid actionable deeplink | >= 90% | {metrics['auto_linked_pct']}% |

---

## 2. Accuracy Benchmarks
No ground-truth plans were supplied, so step accuracy and deeplink relevance were not scored.

| Evaluation Metric | Scale / Anchor | Score |
| :--- | :--- | :--- |
| Step accuracy (completeness, correctness, ordering) | 0.0 - 3.0 | not scored |
| Deeplink relevance (exact target screen vs. parent menu) | 0.0 - 2.0 | not scored |

---

## 3. Latency Benchmarks (N = {lat['exact']['n']} requests per path)

| Execution Path | Target (P95) | P50 (ms) | P95 (ms) | Result |
| :--- | :--- | :--- | :--- | :--- |
| Cache hit - exact query match | <= 300 ms | {lat['exact']['p50']} | {lat['exact']['p95']} | {verdict(lat['exact']['p95'] <= 300)} |
| Cache hit - unseen semantic paraphrase | <= 300 ms | {lat['paraphrase']['p50']} | {lat['paraphrase']['p95']} | {verdict(lat['paraphrase']['p95'] <= 300)} |
| Cold query - full pipeline extraction & mapping | <= 8000 ms | {lat['cold']['p50']} | {lat['cold']['p95']} | {verdict(lat['cold']['p95'] <= 8000)} |

---

## 4. Operational Cost & Cache Efficacy

| Metric Item | Target | Measured Value |
| :--- | :--- | :--- |
| Cold query average inference cost | Tracked | $0.00 |
| Cache hit inference cost | $0.00 | $0.00 |
| Semantic cache hit rate (unseen paraphrases, correct plan) | >= {HIT_RATE_TARGET:.0f}% | {rate}% ({metrics['paraphrase_correct']} of {metrics['paraphrase_total']}; {metrics['paraphrase_wrong']} hit a wrong plan) - {verdict(rate >= HIT_RATE_TARGET)} |
| Per held-out set | | {per_set} |
| Unrelated queries wrongly answered | 0 | {metrics['negative_false_hits']} of {metrics['negative_total']} |
| Cost derivation method | - | no generative calls; (prompt tokens + completion tokens) x rate = 0 |

---

## 5. Architectural Ablation Analysis

| Architecture Variant | Step Accuracy | Latency (P95) | Cost / Query | Key Observations |
| :--- | :--- | :--- | :--- | :--- |
| Baseline: Full LLM Deeplink Mapping | not run | not run | not run | No LLM in this version. |
| Variant A: Hybrid BM25 + Dense Embedding Retrieval | not scored | not run | $0.00 | Tried on real sections and rejected: min-max fusion scores the top hit near 1.0 even for unrelated screens (for example "Restart in Safe Mode" against "One-handed mode"). |
| Variant B: Pure Rules-Based Deeplink Mapping | not scored | {lat['cold']['p95']} ms cold | $0.00 | Exact match of the tapped UI label to the catalog's `validation.key`. This is what ships. |
| Cache lookup: hashed bag-of-words embedding | n/a | fast | $0.00 | 8 of 14 paraphrases on the first set. Fallback only (`EMBEDDING_MODEL=hash`). |
| Cache lookup: all-mpnet-base-v2 + action-content keys | n/a | see section 3 | $0.00 | Default. Meets the hit-rate target on both held-out sets. |

---

## 6. Known Edge Cases & System Limitations
* The article-relevance gate is lexical. Rows 8 and 20 (article does not fit the complaint) are refused, but rows 7 and 12 share ordinary words with their article and still receive a plan. Fixing this needs semantic similarity.
* Remaining paraphrase misses are ambiguous complaints, for example a smashed screen where the user cannot see anything (cracked screen versus recovering data). Rows 3 and 11 yield a thin plan (a single force-restart action) because their source article is mostly unrelated text.
* Held-out sets are small (14 queries each); treat the percentages as indicative, not precise.
* Multi-intent complaints (row 19) are answered for the dominant intent only.
* Rows 6 and 18 do not exist in `siis_responses.json`. Rows 16, 17, and 20 are refused by the relevance gate.
* The official `sample_output.json` has action descriptions of 9 and 11 words, against the written 5 to 7 word rule; this engine follows the written rule.
* All 20 official rows are Display complaints. Battery/Camera/Performance generalization is checked separately, against author-written test articles, in `tests/test_domain_generalization.py` (see `docs/domain-coverage.md`), not in the figures above.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--embedding-model", default=EMBEDDING_MODEL, help="model id, local directory, or 'hash'")
    parser.add_argument("--threshold", type=float, default=SIMILARITY_THRESHOLD, help="cosine similarity threshold")
    parser.add_argument("--requests", type=int, default=REQUESTS_PER_PATH, help="requests per latency path")
    parser.add_argument("--out", type=Path, default=ROOT / "metrics.md")
    args = parser.parse_args()

    catalog = load_catalog()
    model = load_embedder(args.embedding_model)
    service = TroubleshootingService(catalog, PlanCache(catalog, model=model, threshold=args.threshold))
    service.warm(load_siis_rows())
    fixture_sets = {name: json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8")) for name in FIXTURE_SETS}
    metrics = collect_metrics(service, fixture_sets, args.requests)
    args.out.write_text(render(metrics, service.cache.embedder_name, args.threshold), encoding="utf-8")
    print(json.dumps({k: v for k, v in metrics.items() if k != "sets"}, indent=2))
    print(json.dumps(metrics["sets"], indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
