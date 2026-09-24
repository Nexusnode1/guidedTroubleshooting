"""Interactively exercise the query-enrichment module."""

from __future__ import annotations

import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.query_enrichment import enrich_query


def main() -> int:
    """Read one query and print its complete structured enrichment result."""
    query = input("Enter your query: ")
    result = enrich_query(query)
    if hasattr(result, "model_dump"):
        payload = result.model_dump()
    else:
        payload = result.dict()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
