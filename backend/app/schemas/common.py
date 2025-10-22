"""Common schema primitives used across Brain Buddy models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt


class StrictBaseModel(BaseModel):
    """Base model that forbids unexpected fields for safer validation."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=False)


class TimestampMetadata(StrictBaseModel):
    """Common metadata block used for created/updated timestamps."""

    created_at: datetime = Field(description="UTC timestamp when the entity was created.")
    updated_at: datetime = Field(description="UTC timestamp for the most recent update.")
    author: str | None = Field(default=None, description="Optional user identifier responsible for change.")


class Position(StrictBaseModel):
    """Canvas coordinates stored as floats."""

    x: float = Field(description="X coordinate on the canvas.")
    y: float = Field(description="Y coordinate on the canvas.")


class VisualState(StrictBaseModel):
    """Visual hints used by the frontend when rendering a node."""

    color: str | None = Field(default=None, description="Hex color assigned to the node background.")
    highlight: bool = Field(default=False, description="Whether the node should be visually highlighted.")


class ValidationState(StrictBaseModel):
    """Latest validation snapshot stored inline on a node."""

    confidence: PositiveInt = Field(le=100, description="Validation confidence percentage (0-100).")
    provider: str = Field(description="Identifier of the provider that produced the validation result.")
    last_checked: datetime = Field(description="UTC timestamp when validation occurred.")


class SortDirection(StrictBaseModel):
    """Sorting direction helper used by list endpoints."""

    direction: Literal["asc", "desc"] = Field(default="desc")


__all__ = [
    "Position",
    "StrictBaseModel",
    "TimestampMetadata",
    "ValidationState",
    "VisualState",
    "SortDirection",
]
