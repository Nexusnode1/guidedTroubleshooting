"""Pydantic models for catalog-backed screen resolution."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScreenResolution(BaseModel):
    """Resolution result containing only catalog-derived screen information."""

    action: str = Field(description="The extracted UI action/query being resolved.")
    target_screen: str | None = Field(default=None, description="Catalog target screen, if resolved.")
    deeplink: str | None = Field(default=None, description="Exact catalog URI, if resolved.")
    confidence: float = Field(ge=0.0, le=1.0, description="Deterministic resolution confidence.")
    resolved: bool = Field(description="Whether the match is sufficiently specific to accept.")
    parent_level_only: bool = Field(description="Whether the best available match is only a parent menu.")
    ambiguous: bool = Field(description="Whether multiple screen candidates are too close to choose safely.")
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata and score components used for the resolution.",
    )
