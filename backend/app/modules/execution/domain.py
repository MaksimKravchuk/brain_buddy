"""Domain models for the Execution module (ADR-0001)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StorageBaseModel
from app.utils.time import utcnow

EvidenceResultSource = Literal["external_task_tracker", "crt", "manual"]
EvidenceResultKind = Literal["evidence", "result"]
EvidenceResultStatus = Literal["recorded", "superseded"]


class EvidenceResult(StorageBaseModel):
    """Evidence or result linked back to originating captures.

    Per ADR-0001: append-only except `recorded -> superseded`. At least
    one originating `atomic_capture_id` is required. Every linked route,
    review, tree, and node must have the same owner.
    """

    id: str = Field(description="Unique result ID.")
    owner_id: str = Field(description="Owning user ID.")
    source: EvidenceResultSource = Field(description="Origin of the result.")
    kind: EvidenceResultKind = Field(description="Evidence or result.")
    status: EvidenceResultStatus = Field(default="recorded")
    title: str = Field(description="Short title.")
    summary: str | None = Field(default=None, description="Optional longer summary.")
    uri: str | None = Field(default=None, description="Optional link to source.")
    atomic_capture_ids: list[str] = Field(
        default_factory=list, description="Originating capture IDs."
    )
    route_id: str | None = Field(default=None, description="Linked route, if any.")
    weekly_review_id: str | None = Field(
        default=None, description="Linked review, if any."
    )
    tree_id: str | None = Field(default=None, description="Linked CRT tree, if any.")
    node_ids: list[str] = Field(default_factory=list)
    observed_at: datetime = Field(default_factory=utcnow)
    recorded_at: datetime = Field(default_factory=utcnow)
    actor_id: str | None = Field(default=None, description="Recording actor.")
    schema_version: str = Field(default="1")
