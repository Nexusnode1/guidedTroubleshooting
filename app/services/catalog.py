"""Loaders for the official, immutable input files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import ORIGINAL_DIR
from app.utils.data_loader import load_json


def load_catalog(path: Path | None = None) -> list[dict[str, Any]]:
    """Return every entry of the official deeplink catalog, unmodified."""
    return list(load_json(path or ORIGINAL_DIR / "deeplinks.json")["deeplinks"])


def load_siis_rows(path: Path | None = None) -> list[dict[str, Any]]:
    """Return the official SIIS response rows (id, original_query, siis_response)."""
    return list(load_json(path or ORIGINAL_DIR / "siis_responses.json")["responses"])
