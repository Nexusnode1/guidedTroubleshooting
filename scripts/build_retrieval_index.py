"""Build a generated retrieval metadata artifact from the official catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.bm25_retriever import DEFAULT_METADATA_FIELDS, metadata_text
from app.utils.data_loader import DataLoadError, load_json


def build_index(source: Path, destination: Path) -> int:
    """Write generated metadata only; never alter the source catalog."""
    try:
        loaded = load_json(source)
    except DataLoadError as exc:
        print(f"Unable to load catalog: {exc}", file=sys.stderr)
        return 1
    if not isinstance(loaded, list):
        print("Catalog must be a JSON list of entries.", file=sys.stderr)
        return 1
    records = []
    try:
        for entry in loaded:
            if not isinstance(entry, dict):
                raise ValueError("catalog entries must be JSON objects")
            records.append({"entry": entry, "metadata": metadata_text(entry, DEFAULT_METADATA_FIELDS)})
    except ValueError as exc:
        print(f"Invalid catalog: {exc}", file=sys.stderr)
        return 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote generated retrieval index: {destination} ({len(records)} entries)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Build the index from ``data/original/deeplinks.json`` by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / "data/original/deeplinks.json")
    parser.add_argument("--destination", type=Path, default=PROJECT_ROOT / "data/processed/retrieval_index.json")
    args = parser.parse_args(argv)
    return build_index(args.source, args.destination)


if __name__ == "__main__":
    raise SystemExit(main())
