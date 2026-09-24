"""Warm the plan cache from the official SIIS rows and print what happened to each row."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.catalog import load_catalog, load_siis_rows  # noqa: E402
from app.services.troubleshooting_service import DEFAULT_CACHE_PATH, TroubleshootingService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_CACHE_PATH, help="where to write the cache")
    args = parser.parse_args()
    service = TroubleshootingService(load_catalog())
    for result in service.warm(load_siis_rows()):
        detail = ""
        if result.build is not None:
            context = result.build.response["contexts"][0]
            categories = [action["category"] for action in context["actions"]]
            detail = f"{context['title']!r} relevance={result.build.relevance:.2f} actions={categories}"
            detail += "".join(f"\n            ! {error}" for error in result.build.errors)
        print(f"{result.row_id:8}{result.status:9}{detail}")
    service.cache.save(args.out)
    print(f"saved {len(service.cache)} plans to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
