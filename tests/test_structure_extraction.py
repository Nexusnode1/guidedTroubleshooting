"""Tests for deterministic structure extraction using TEST DATA queries."""

import pytest

from app.models.schemas import QueryEnrichmentResult
from app.models.structure import TroubleshootingStructure
from app.services.query_enrichment import enrich_query
from app.services.structure_extraction import extract_goal, extract_structure


def extract(query: str) -> TroubleshootingStructure:
    """Run the real enrichment implementation before extraction."""
    return extract_structure(enrich_query(query))


@pytest.mark.parametrize(
    "query",
    [
        "My battery drains very quickly",
        "bro my phone is getting crazy hot",
        "my phone is slow",
        "camera is not working",
        "my battry is draining fst",
        "my phone is hot and battery is dying",
    ],
)
def test_required_queries_produce_structured_output(query: str) -> None:
    """All requested query styles produce a Pydantic structure."""
    result = extract(query)
    assert isinstance(result, TroubleshootingStructure)
    assert result.original_query == query
    assert result.normalized_query
    assert result.core_intent
    assert result.possible_intents


def test_battery_query_extracts_entity_symptom_and_moderate_severity() -> None:
    """Explicit battery wording is retained as entity and symptom text."""
    result = extract("My battery drains very quickly")
    assert "battery" in result.entities
    assert result.symptoms == ["my battery drains very quickly"]
    assert result.severity == "moderate"
    assert result.is_ambiguous is False


def test_multi_symptom_query_keeps_both_clauses() -> None:
    """Conjoined symptoms are represented independently."""
    result = extract("my phone is hot and battery is dying")
    assert len(result.symptoms) == 2
    assert "my phone is hot" in result.symptoms
    assert "battery is dying" in result.symptoms
    assert set(("phone", "battery")).issubset(result.entities)


def test_typo_and_casual_input_uses_enriched_text() -> None:
    """Upstream typo/casual normalization feeds extraction."""
    result = extract("bro my battry is draining fst")
    assert result.normalized_query == "bro my battry is draining fst"
    assert result.symptoms == ["bro my battry is draining fst"]
    assert "battery" in result.entities
    assert result.original_query.startswith("bro")


def test_ambiguous_query_does_not_force_intent() -> None:
    """Generic one-word input is flagged and retained as a candidate."""
    result = extract("help")
    assert result.is_ambiguous is True
    assert result.ambiguity_reason
    assert result.possible_intents == ["help"]


def test_mapping_input_remains_supported() -> None:
    """The extractor accepts the serialized enrichment boundary too."""
    source = QueryEnrichmentResult(
        original_query="camera issue",
        normalized_query="camera issue",
        core_intent="camera issue",
        variations=["camera issue"],
    )
    payload = source.model_dump() if hasattr(source, "model_dump") else source.dict()
    result = extract_goal(payload)
    assert result.entities == ["camera"]
