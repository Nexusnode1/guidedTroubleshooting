"""The official inputs are present, immutable, and match the official schema."""

import json

import pytest

from app.config import ORIGINAL_DIR
from app.models.official_schema import ContextDeeplinkResponse

OFFICIAL_FILES = ("deeplinks.json", "siis_responses.json", "input.txt", "sample_output.json")


def test_catalog_has_official_entry_count_and_one_placeholder(catalog):
    assert len(catalog) == 578
    assert sum(entry["deeplink"] == "bixby://dummy_positive" for entry in catalog) == 1


def test_siis_rows_are_the_twenty_official_rows(siis_rows):
    assert len(siis_rows) == 20
    assert {"id", "original_query", "siis_response"} <= set(siis_rows[0])
    assert {"title", "content"} <= set(siis_rows[0]["siis_response"])


@pytest.mark.parametrize("name", OFFICIAL_FILES)
def test_original_files_are_byte_identical_to_the_kit(name):
    kit = ORIGINAL_DIR.parents[2] / "student_kit"
    if not kit.exists():
        pytest.skip("student_kit is not next to this repository")
    assert (ORIGINAL_DIR / name).read_bytes() == (kit / name).read_bytes()


def test_official_sample_output_matches_the_official_schema():
    sample = json.loads((ORIGINAL_DIR / "sample_output.json").read_text(encoding="utf-8"))
    ContextDeeplinkResponse.model_validate(sample["response"])
