"""Domain models for the Capture module.

Implements CaptureSession, AtomicCaptureSource, and Transcript types
from ADR-0001. These are the immutable source records owned by Capture.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StorageBaseModel

# --- Enums ---

CaptureSessionStatus = Literal[
    "received",
    "transcribing",
    "transcribed",
    "splitting",
    "ready",
    "failed",
    "cancelled",
]

InputKind = Literal["voice", "text"]

AtomicCaptureKind = Literal["task", "note", "question", "problem_candidate"]

ConfidenceBand = Literal["high", "medium", "low"]

# --- Sub-models ---


class MediaInfo(StorageBaseModel):
    """Metadata about uploaded media."""

    mime_type: str = Field(description="MIME type of the uploaded media.")
    byte_size: int = Field(ge=0, description="Size of the media in bytes.")
    duration_ms: int | None = Field(
        default=None, ge=0, description="Duration in milliseconds, if known."
    )
    sha256: str | None = Field(
        default=None, description="SHA-256 hash of the media content."
    )


class ConsentRecord(StorageBaseModel):
    """User consent for external processing."""

    external_processing_allowed: bool = Field(
        description="Whether external processing (e.g. transcription API) is allowed."
    )
    recorded_at: datetime = Field(description="When consent was recorded.")
    provider: str | None = Field(
        default=None, description="Provider category consent was given for."
    )


class TranscriptResult(StorageBaseModel):
    """Result of a transcription attempt."""

    text: str = Field(description="Transcribed text.")
    language: str | None = Field(
        default=None, description="Detected or configured language code."
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Transcription confidence score (0.0-1.0).",
    )
    provider: str = Field(description="Transcription provider identifier.")
    model: str | None = Field(
        default=None, description="Model identifier used by the provider."
    )
    completed_at: datetime = Field(description="When transcription completed.")


class ErrorRecord(StorageBaseModel):
    """Error details for a failed stage."""

    code: str = Field(description="Machine-readable error code.")
    retryable: bool = Field(description="Whether the operation can be retried.")
    stage: str = Field(description="Pipeline stage where the error occurred.")


class AtomicCaptureClassification(StorageBaseModel):
    """Classification metadata for an atomic capture."""

    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Classification confidence (0.0-1.0).",
    )
    model: str | None = Field(
        default=None, description="Model used for classification."
    )
    reasons: list[str] = Field(
        default_factory=list, description="Reasons supporting the classification."
    )


class SourceSpan(StorageBaseModel):
    """Character span in the source transcript."""

    start_char: int = Field(ge=0, description="Start character offset.")
    end_char: int = Field(ge=0, description="End character offset (exclusive).")


# --- Primary records ---


class CaptureSession(StorageBaseModel):
    """Immutable capture session record (Capture-owned).

    Tracks the lifecycle from received through ready/failed/cancelled.
    """

    id: str = Field(description="Unique session identifier.")
    owner_id: str = Field(description="Owning user identifier.")
    input_kind: InputKind = Field(description="Input modality (voice or text).")
    status: CaptureSessionStatus = Field(
        default="received", description="Current pipeline status."
    )
    media_ref: str | None = Field(
        default=None,
        description="Opaque media reference (never a filesystem path).",
    )
    media: MediaInfo | None = Field(
        default=None, description="Media metadata."
    )
    consent: ConsentRecord | None = Field(
        default=None, description="Processing consent record."
    )
    transcript: TranscriptResult | None = Field(
        default=None, description="Transcription result, if available."
    )
    attempt_count: int = Field(
        default=0, ge=0, description="Number of transcription attempts."
    )
    last_error: ErrorRecord | None = Field(
        default=None, description="Last error details, if failed."
    )
    atomic_capture_ids: list[str] = Field(
        default_factory=list,
        description="IDs of atomic captures derived from this session.",
    )
    created_at: datetime = Field(description="UTC creation timestamp.")
    updated_at: datetime = Field(description="UTC last-update timestamp.")
    schema_version: str = Field(default="1", description="Schema version.")
    revision: int = Field(default=1, ge=1, description="Optimistic concurrency revision.")


class AtomicCaptureSource(StorageBaseModel):
    """Immutable atomic capture source (Capture-owned).

    One atomic unit extracted from a transcript. Never edited after creation.
    The corresponding mutable CaptureItem (Organize-owned) shares the same ID.
    """

    id: str = Field(description="Unique identifier (shared with CaptureItem).")
    owner_id: str = Field(description="Owning user identifier.")
    capture_session_id: str = Field(description="Parent capture session ID.")
    ordinal: int = Field(
        ge=0, description="Position in the session's capture list."
    )
    kind: AtomicCaptureKind = Field(description="Inferred capture kind.")
    source_span: SourceSpan | None = Field(
        default=None, description="Character span in the source transcript."
    )
    source_text: str = Field(description="Immutable original text from the transcript.")
    classification: AtomicCaptureClassification = Field(
        default_factory=AtomicCaptureClassification,
        description="Classification metadata.",
    )
    created_at: datetime = Field(description="UTC creation timestamp.")
    schema_version: str = Field(default="1", description="Schema version.")


__all__ = [
    "AtomicCaptureClassification",
    "AtomicCaptureKind",
    "AtomicCaptureSource",
    "CaptureSession",
    "CaptureSessionStatus",
    "ConfidenceBand",
    "ConsentRecord",
    "ErrorRecord",
    "InputKind",
    "MediaInfo",
    "SourceSpan",
    "TranscriptResult",
]
