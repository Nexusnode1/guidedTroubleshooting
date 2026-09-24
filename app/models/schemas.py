"""Pydantic models for API boundaries and provisional query enrichment.

The official Theme 2 schema is not present in this workspace. Query
enrichment models below are therefore implementation contracts, not claims
about the official response format.
"""

from pydantic import BaseModel, Field


class TroubleshootRequest(BaseModel):
    """Body of POST /v1/troubleshoot (PDF section 5)."""

    query: str = Field(min_length=1, description="User-provided troubleshooting query.")
    siis_response: str | None = Field(default=None, description="Optional raw SIIS knowledge text.")


class QueryEnrichmentResult(BaseModel):
    """Intent-preserving query forms passed to later retrieval stages."""

    original_query: str = Field(description="The exact user input, unchanged.")
    normalized_query: str = Field(description="Normalized form of the input.")
    core_intent: str = Field(description="Concise lexical representation of the request.")
    variations: list[str] = Field(
        default_factory=list,
        description="Deterministic, intent-preserving retrieval variations.",
    )


class StructuredTroubleshootingGoal(BaseModel):
    """Provisional structured goal passed to later pipeline stages.

    The official Theme 2 output schema is unavailable, so this deliberately
    contains only information already present in query enrichment. It has no
    action, deeplink, sequencing, or solution fields.
    """

    original_query: str = Field(description="The exact user input, unchanged.")
    normalized_query: str = Field(description="Normalized query text.")
    core_intent: str = Field(description="Intent represented as normalized content text.")
    keywords: list[str] = Field(default_factory=list, description="Ordered intent keywords.")
    variations: list[str] = Field(default_factory=list, description="Retrieval query variations.")
    is_ambiguous: bool = Field(description="Whether the lexical intent is underspecified.")
