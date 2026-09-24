"""Provisional Pydantic models for extracted troubleshooting structure.

The official Theme 2 output schema is not present in this workspace. These
models therefore extend the existing query-goal contract without claiming to
be the official schema.
"""

from pydantic import Field

from app.models.schemas import StructuredTroubleshootingGoal


class TroubleshootingStructure(StructuredTroubleshootingGoal):
    """Structured, intent-preserving information extracted from a query."""

    symptoms: list[str] = Field(default_factory=list, description="Explicitly stated symptom phrases.")
    entities: list[str] = Field(default_factory=list, description="Explicitly stated device/problem entities.")
    device_context: list[str] = Field(
        default_factory=list,
        description="Device or context terms explicitly present in the query.",
    )
    severity: str = Field(
        default="unknown",
        description="Lexically indicated severity: low, moderate, high, or unknown.",
    )
    ambiguity_reason: str | None = Field(
        default=None,
        description="Reason the goal may require clarification.",
    )
    possible_intents: list[str] = Field(
        default_factory=list,
        description="Candidate intent phrases; no single intent is forced when ambiguous.",
    )
