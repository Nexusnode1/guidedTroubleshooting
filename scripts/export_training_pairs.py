"""Export (anchor, positive) training pairs for fine-tuning your own embedding model.

Each anchor is a way a user might phrase the complaint (the original query and its
generated paraphrases); each positive is a piece of the plan that answers it (an action
name plus its first step). Pairs come only from the warm-up data, never from the
held-out fixtures in tests/fixtures/, so evaluation stays honest.

    python scripts/export_training_pairs.py --out data/processed/training_pairs.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.catalog import load_catalog, load_siis_rows  # noqa: E402
from app.services.plan_cache import PlanCache, _plan_keys  # noqa: E402
from app.services.troubleshooting_service import TroubleshootingService  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures"


def held_out_queries() -> set[str]:
    """Every phrasing used for evaluation; these must never appear in training data."""
    held: set[str] = set()
    for path in FIXTURE_DIR.glob("paraphrases*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        held.update(item["query"].strip().lower() for item in data["positives"])
        held.update(query.strip().lower() for query in data["negatives"])
    return held


def build_pairs(service: TroubleshootingService) -> list[dict[str, str]]:
    """Return one pair per (anchor, plan key), skipping duplicates and held-out queries."""
    held = held_out_queries()
    seen: set[tuple[str, str]] = set()
    pairs: list[dict[str, str]] = []
    for entry in service.cache.entries():
        title = entry.response["contexts"][0]["title"]
        for anchor in (entry.query, *entry.variations):
            if anchor.strip().lower() in held:
                continue
            for positive in _plan_keys(entry.response):
                if (anchor, positive) not in seen:
                    seen.add((anchor, positive))
                    pairs.append({"anchor": anchor, "positive": positive, "plan": title})
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "processed" / "training_pairs.jsonl")
    args = parser.parse_args()
    catalog = load_catalog()
    service = TroubleshootingService(catalog, PlanCache(catalog))  # hashed embedder: pairs need no model
    service.warm(load_siis_rows())
    pairs = build_pairs(service)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(json.dumps(pair, ensure_ascii=False) for pair in pairs) + "\n", encoding="utf-8")
    print(f"wrote {len(pairs)} pairs from {len(service.cache)} plans to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
