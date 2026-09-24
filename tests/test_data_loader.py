"""Tests for safe JSON loading using clearly labelled temporary test data."""

import json
from pathlib import Path

import pytest

from app.utils.data_loader import DataLoadError, load_json


def test_load_json_reads_test_data(tmp_path: Path) -> None:
    """Load a valid temporary TEST DATA JSON document."""
    source = tmp_path / "test-data.json"
    source.write_text(json.dumps({"kind": "TEST DATA"}), encoding="utf-8")
    assert load_json(source) == {"kind": "TEST DATA"}


def test_load_json_rejects_missing_file(tmp_path: Path) -> None:
    """Missing official input files produce a useful loader error."""
    with pytest.raises(DataLoadError, match="does not exist"):
        load_json(tmp_path / "missing.json")


def test_load_json_rejects_invalid_json(tmp_path: Path) -> None:
    """Malformed JSON is reported without mutation or recovery."""
    source = tmp_path / "invalid-test-data.json"
    source.write_text("{not json", encoding="utf-8")
    with pytest.raises(DataLoadError, match="Invalid JSON"):
        load_json(source)
