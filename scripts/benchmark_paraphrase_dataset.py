"""Baseline retrieval benchmark for the corrected SIIS paraphrase dataset.

Deliberately does NOT fine-tune anything: it measures how the CURRENT embedding model
(EMBEDDING_MODEL in app/config.py, or --embedding-model) does on data/processed/
siis_paraphrase_dataset.json before any training decision is made. Only train-role rows'
canonical query and train-split paraphrases go into the cache; val/test texts (including
whole held-out rows) are never added, so recall/MRR here cannot be inflated by having
already seen the exact text being queried.

    python scripts/benchmark_paraphrase_dataset.py
    python scripts/benchmark_paraphrase_dataset.py --embedding-model models/my-embedder
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import EMBEDDING_MODEL  # noqa: E402
from app.retrieval.st_embedder import load_embedder  # noqa: E402
from app.services.catalog import load_catalog, load_siis_rows  # noqa: E402
from app.services.plan_builder import PlanBuilder  # noqa: E402
from app.services.plan_cache import PlanCache  # noqa: E402

DATASET_PATH = ROOT / "data" / "processed" / "siis_paraphrase_dataset.json"
DEFAULT_THRESHOLD = 0.45
K_VALUES = (1, 3, 5)


def _load_dataset() -> dict[str, Any]:
    if not DATASET_PATH.exists():
        raise SystemExit(f"{DATASET_PATH} does not exist; run scripts/build_paraphrase_dataset.py first")
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def _build_cache(dataset: dict[str, Any], catalog: list[dict[str, Any]], embedder) -> PlanCache:
    """Seed the cache from train-role rows only: canonical query + train-split paraphrases."""
    official_by_id = {r["id"]: r for r in load_siis_rows()}
    builder = PlanBuilder(catalog)
    cache = PlanCache(catalog, model=embedder, threshold=DEFAULT_THRESHOLD)
    for row in dataset["rows"]:
        if row["role"] != "train" or not row["plan_valid"]:
            continue
        siis = official_by_id[row["id"]]["siis_response"]
        build = builder.build(row["canonical_query"], siis["content"], siis["title"])
        assert build is not None and build.errors == (), row["id"]
        cache.add(row["id"], row["canonical_query"], build.query_variations, build.response)
        train_paraphrases = [t["text"] for t in row["texts"] if t["kind"] == "paraphrase" and t["split"] == "train"]
        cache.add_lookup_keys(row["id"], train_paraphrases)
    return cache


def split_size(dataset: dict[str, Any], split: str) -> int:
    """Every text tagged with ``split``, regardless of whether its row builds a valid plan.

    This is the number reported by scripts/build_paraphrase_dataset.py's split_counts. It is
    the *dataset's* size, not the number of texts the benchmark can actually score (see
    excluded_examples): a text from a row with no valid plan has no target title to check
    retrieval against at all.
    """
    return sum(1 for row in dataset["rows"] for item in row["texts"] if item["split"] == split)


def excluded_examples(dataset: dict[str, Any], split: str) -> list[dict[str, str]]:
    """Texts of ``split`` whose row has no valid plan, with why each one is excluded."""
    excluded = []
    for row in dataset["rows"]:
        if row["plan_valid"]:
            continue
        reason = f"row {row['id']} has no valid plan ({'; '.join(row['plan_errors'])}); there is no target title to score retrieval against"
        for item in row["texts"]:
            if item["split"] == split:
                excluded.append({"row_id": row["id"], "text": item["text"], "reason": reason})
    return excluded


def _eval_split(cache: PlanCache, dataset: dict[str, Any], split: str) -> dict[str, Any]:
    hits = {k: 0 for k in K_VALUES}
    reciprocal_ranks: list[float] = []
    total = 0
    misses: list[dict[str, str]] = []
    for row in dataset["rows"]:
        if not row["plan_valid"]:
            continue
        expected = row["plan_title"]
        for item in row["texts"]:
            if item["split"] != split:
                continue
            total += 1
            top = cache.top_matches(item["text"], k=max(K_VALUES))
            titles = [hit.entry.response["contexts"][0]["title"] for hit in top]
            rank = titles.index(expected) + 1 if expected in titles else None
            for k in K_VALUES:
                if rank is not None and rank <= k:
                    hits[k] += 1
            reciprocal_ranks.append(1.0 / rank if rank is not None else 0.0)
            if rank != 1:
                misses.append({"row_id": row["id"], "query": item["text"], "expected": expected, "got": titles[:1]})
    excluded = excluded_examples(dataset, split)
    dataset_size = split_size(dataset, split)
    assert total + len(excluded) == dataset_size, (
        f"{split}: {total} scored + {len(excluded)} excluded != {dataset_size} in the dataset"
    )
    return {
        "dataset_size": dataset_size,
        "excluded": excluded,
        "total": total,
        "recall": {f"recall@{k}": round(hits[k] / total, 4) if total else 0.0 for k in K_VALUES},
        "mrr": round(sum(reciprocal_ranks) / total, 4) if total else 0.0,
        "misses": misses,
    }


def _dataset_quality_metrics(dataset: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    actionable = {entry["deeplink"] for entry in catalog}
    valid_rows = [r for r in dataset["rows"] if r["plan_valid"]]
    official_by_id = {r["id"]: r for r in load_siis_rows()}
    builder = PlanBuilder(catalog)
    total_links = links_in_catalog = auto_actions = auto_linked = 0
    for row in valid_rows:
        siis = official_by_id[row["id"]]["siis_response"]
        build = builder.build(row["canonical_query"], siis["content"], siis["title"])
        for action in build.response["contexts"][0]["actions"]:
            for group in action["stepGroups"]:
                if group["actionableDeeplink"]:
                    total_links += 1
                    links_in_catalog += group["actionableDeeplink"]["deeplink"] in actionable
            if action["category"] == "auto":
                auto_actions += 1
                auto_linked += any(g["actionableDeeplink"] for g in action["stepGroups"])
    return {
        "schema_validation_pass_rate": round(len(valid_rows) / len(dataset["rows"]), 4),
        "exact_deeplink_accuracy": round(links_in_catalog / total_links, 4) if total_links else None,
        "auto_action_screen_resolution_rate": round(auto_linked / auto_actions, 4) if auto_actions else None,
        "note": (
            "exact_deeplink_accuracy and auto_action_screen_resolution_rate measure catalog "
            "membership and presence of a resolved screen, not per-query semantic correctness. "
            "Per-screen correctness is regression-tested with specific catalog IDs in "
            "tests/test_plan_builder.py, tests/test_key_matcher.py, and "
            "tests/test_domain_generalization.py."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--embedding-model", default=EMBEDDING_MODEL)
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "siis_paraphrase_baseline_benchmark.md")
    args = parser.parse_args()

    dataset = _load_dataset()
    catalog = load_catalog()
    embedder = load_embedder(args.embedding_model)
    cache = _build_cache(dataset, catalog, embedder)

    results = {split: _eval_split(cache, dataset, split) for split in ("val", "test")}
    quality = _dataset_quality_metrics(dataset, catalog)

    report = [
        "# SIIS Paraphrase Dataset: Baseline Retrieval Benchmark",
        "",
        "No fine-tuning has happened. This measures the current, off-the-shelf embedding model",
        f"(`{cache.embedder_name}`, similarity threshold used for cache hits: {DEFAULT_THRESHOLD};",
        "Recall@k/MRR below rank all cached plans and ignore that threshold, per",
        "`PlanCache.top_matches`) against `data/processed/siis_paraphrase_dataset.json`.",
        "",
        f"Cache built from {sum(1 for r in dataset['rows'] if r['role'] == 'train')} train-role rows",
        "(canonical query + 5 train-split paraphrases each). Val and test texts, including whole",
        "held-out rows, were never added to the cache before evaluation.",
        "",
        "## Retrieval metrics",
        "",
        "`N` is the number of texts actually scored, not the split size in the dataset file:",
        "a row with no valid plan (see Excluded examples below) has no target title to check",
        "retrieval against, so it cannot be scored either way -- it is excluded, not counted",
        "as a miss and not silently dropped from the total without explanation.",
        "",
        "| Split | Dataset size | Excluded | N (scored) | Recall@1 | Recall@3 | Recall@5 | MRR |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for split in ("val", "test"):
        r = results[split]
        report.append(
            f"| {split} | {r['dataset_size']} | {len(r['excluded'])} | {r['total']} | {r['recall']['recall@1']} "
            f"| {r['recall']['recall@3']} | {r['recall']['recall@5']} | {r['mrr']} |"
        )
    report += ["", "## Excluded examples", ""]
    any_excluded = False
    for split in ("val", "test"):
        for item in results[split]["excluded"]:
            any_excluded = True
            report.append(f"- [{split}] `{item['row_id']}`: {item['reason']}. Text: {item['text']!r}")
    if not any_excluded:
        report.append("- none")
    report += [
        "",
        "## Dataset/schema quality metrics",
        "",
        f"- Schema/rule validation pass rate: {quality['schema_validation_pass_rate']:.0%} "
        f"({sum(1 for r in dataset['rows'] if r['plan_valid'])}/{len(dataset['rows'])} rows)",
        f"- Exact deeplink accuracy (catalog membership): "
        f"{quality['exact_deeplink_accuracy']:.0%}" if quality["exact_deeplink_accuracy"] is not None else "- Exact deeplink accuracy: n/a",
        f"- Auto-action screen resolution rate (has a resolved deeplink): "
        f"{quality['auto_action_screen_resolution_rate']:.0%}" if quality["auto_action_screen_resolution_rate"] is not None else "",
        f"- {quality['note']}",
        "",
        "## Misses (test split)",
        "",
    ]
    for miss in results["test"]["misses"][:15]:
        report.append(f"- `{miss['row_id']}` expected {miss['expected']!r}, top-1 was {miss['got']!r}: {miss['query']!r}")
    if not results["test"]["misses"]:
        report.append("- none")

    args.out.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"val": {k: v for k, v in results["val"].items() if k != "misses"},
                       "test": {k: v for k, v in results["test"].items() if k != "misses"},
                       "quality": quality}, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
