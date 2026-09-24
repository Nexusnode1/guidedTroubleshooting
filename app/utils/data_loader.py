"""Safe loading helpers for immutable, official JSON input files."""

import json
from pathlib import Path
from typing import Any


class DataLoadError(ValueError):
    """Raised when a data path cannot be safely loaded as JSON."""


def load_json(path: Path) -> Any:
    """Load and decode a JSON file without modifying it.

    Schema validation is deferred until the official Theme 2 schema is
    supplied. The returned value may therefore be any JSON value.
    """
    source = Path(path)
    if not source.exists():
        raise DataLoadError(f"Data file does not exist: {source}")
    if not source.is_file():
        raise DataLoadError(f"Data path is not a file: {source}")
    try:
        with source.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeError) as exc:
        raise DataLoadError(f"Could not read JSON file {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DataLoadError(f"Invalid JSON in {source}: {exc}") from exc
