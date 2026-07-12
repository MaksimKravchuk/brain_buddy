"""Domain models for the Thinking/CRT module (ADR-0001)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StorageBaseModel
from app.utils.time import utcnow

ProblemCandidateSignal = Literal["manual", "repeated", "complex"]
ProblemCandidateStatus = Literal["open", "promotion_requested", "promoted", "dismissed"]
PromotionStatus = Literal["pending", "promoting", "succeeded", "failed"]


class ProblemCandidate(StorageBaseModel):
    """A candidate problem that may be promoted into a CRT tree.

    Created from repeated/complex capture signals or manual user action.
    Promotion is user-confirmed per ADR-0001.
    """

    id: str = Field(description="Unique candidate ID.")
    owner_id: str = Field(description="Owning user ID.")
    source_capture_ids: list[str] = Field(
        default_factory=list, description="Originating capture IDs."
    )
    title: str = Field(description="Problem title.")
    context: str = Field(default="", description="Additional context.")
    signal: ProblemCandidateSignal = Field(
        default="manual", description="How the candidate was identified."
    )
    signal_reasons: list[str] = Field(default_factory=list)
    status: ProblemCandidateStatus = Field(default="open")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    revision: int = Field(default=1)
    schema_version: str = Field(default="1")


class CrtPromotion(StorageBaseModel):
    """A promotion attempt linking a candidate to a CRT tree.

    Status becomes 'succeeded' only after the CRT tree/node and source
    links are persisted (ADR-0001). Failed promotion leaves the candidate
    'promotion_requested', making retry visible.
    """

    id: str = Field(description="Unique promotion ID.")
    owner_id: str = Field(description="Owning user ID.")
    problem_candidate_id: str = Field(description="Candidate being promoted.")
    status: PromotionStatus = Field(default="pending")
    tree_id: str | None = Field(default=None, description="Created CRT tree ID.")
    root_node_id: str | None = Field(default=None, description="Initial node ID.")
    source_capture_ids: list[str] = Field(default_factory=list)
    attempt_count: int = Field(default=0)
    last_error: dict[str, object] | None = Field(default=None)
    requested_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = Field(default=None)
    revision: int = Field(default=1)
    schema_version: str = Field(default="1")
