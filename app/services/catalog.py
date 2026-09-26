"""Loaders for the official, immutable input files."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from app.config import ORIGINAL_DIR
from app.utils.data_loader import load_json

# The catalog marks its one generic Settings-screen fallback by originalType, not by a
# fixed URI, so the placeholder is recognized whatever namespace the catalog uses.
PLACEHOLDER_TYPE = "placeholder"


def is_placeholder(entry: Mapping[str, Any]) -> bool:
    """Return whether ``entry`` is the catalog's generic Settings-screen placeholder."""
    return entry.get("originalType") == PLACEHOLDER_TYPE


def placeholder_uris(catalog: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """Return the exact URIs of every placeholder entry in ``catalog``."""
    return frozenset(
        entry["deeplink"] for entry in catalog if is_placeholder(entry) and isinstance(entry.get("deeplink"), str)
    )


def load_catalog(path: Path | None = None) -> list[dict[str, Any]]:
    """Return every entry of the official deeplink catalog, unmodified."""
    return list(load_json(path or ORIGINAL_DIR / "deeplinks.json")["deeplinks"])


def load_siis_rows(path: Path | None = None) -> list[dict[str, Any]]:
    """Return the official SIIS response rows (id, original_query, siis_response)."""
    return list(load_json(path or ORIGINAL_DIR / "siis_responses.json")["responses"])
