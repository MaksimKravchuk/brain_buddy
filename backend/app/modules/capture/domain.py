"""Domain models for the Capture module.

Implements ADR-0001 contracts: AtomicCaptureSource (immutable),
CaptureItem (mutable, one-to-one with source), and CaptureSession
for text-based input. Voice/async pipeline deferred to ADR-0002.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StorageBaseModel
from app.utils.time import utcnow

CaptureKind = Literal["task", "note", "question", "problem_candidate"]
CaptureItemState = Literal[
    "proposed",
    "needs_clarification",
    "approved",
    "deferred",
    "completed",
    "deleted",
]
CaptureSessionStatus = Literal[
    "received",
    "transcribing",
    "transcribed",
    "splitting",
    "ready",
    "failed",
    "cancelled",
]


class AtomicCaptureSource(StorageBaseModel):
    """Immutable source of an atomic capture (ADR-0001).

    Created by the Capture module during splitting. Never edited after
    creation — `source_text` is permanent provenance.
    """

    id: str = Field(description="Unique identifier (shared with CaptureItem).")
    owner_id: str = Field(description="Owning user ID.")
    capture_session_id: str = Field(description="Parent session ID.")
    ordinal: int = Field(description="Position in the split sequence.")
    kind: CaptureKind = Field(description="Inferred capture kind.")
    source_text: str = Field(description="Immutable original text.")
    classification: dict[str, object] = Field(
        default_factory=dict,
        description="Confidence, model, reasons from classification.",
    )
    created_at: datetime = Field(default_factory=utcnow)
    schema_version: str = Field(default="1")


class CaptureItem(StorageBaseModel):
    """Mutable capture item (ADR-0001 Organize module).

    One-to-one with AtomicCaptureSource (shares ID). Users edit
    `current_text`; `source_text` stays immutable. Transitions through
    the review_state lifecycle.
    """

    id: str = Field(description="Unique ID (= AtomicCaptureSource.id).")
    owner_id: str = Field(description="Owning user ID.")
    source_capture_id: str = Field(description="Parent CaptureSession ID.")
    current_text: str = Field(description="Editable user text.")
    review_state: CaptureItemState = Field(
        default="proposed", description="Current lifecycle state."
    )
    destination_intent: Literal["none", "external_task_tracker", "brainbuddy_problem"] = (
        Field(default="none")
    )
    route_id: str | None = Field(default=None, description="RouteRecord.id if routed.")
    crt_candidate_id: str | None = Field(
        default=None, description="ProblemCandidate.id if promoted."
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    revision: int = Field(default=1, description="Optimistic concurrency revision.")
    schema_version: str = Field(default="1")


class CaptureSession(StorageBaseModel):
    """Capture session aggregating one input's atomic captures.

    For the MVP text-only implementation, a session transitions directly
    from received -> ready. Voice/transcription pipeline is deferred.
    """

    id: str = Field(description="Unique session identifier.")
    owner_id: str = Field(description="Owning user ID.")
    input_kind: Literal["voice", "text"] = Field(description="Input modality.")
    status: CaptureSessionStatus = Field(
        default="received", description="Session lifecycle state."
    )
    atomic_capture_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    schema_version: str = Field(default="1")
