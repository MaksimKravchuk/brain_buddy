"""Schemas for the Brain Dump voice-to-RTM-Inbox vertical slice.

This module implements the founder-approved voice-only brain dump flow:
voice recording -> transcription -> flat ordered task drafts -> edit/delete
in review -> Save session exports each remaining draft as a plain RTM Inbox
task (name-only, no tags/notes/priority/dates/list moves).

No text-capture, CRT, recommendations, planner, subtasks, destinations, or
Weekly Review concepts appear here.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import ConfigDict, Field

from .common import StrictBaseModel


class SessionStatus(str, Enum):
    """Brain dump session lifecycle states."""

    RECORDING = "recording"
    REVIEWING = "reviewing"
    COMPLETED = "completed"


class Draft(StrictBaseModel):
    """A provisional task draft extracted from voice input."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(description="Unique draft identifier within the session.")
    text: str = Field(description="Task name extracted from voice.")
    created_at: datetime = Field(description="When this draft was created.")
    updated_at: datetime = Field(description="When this draft was last edited.")
    revision: int = Field(
        default=1, ge=1, description="Optimistic-concurrency revision."
    )


class ExportResult(StrictBaseModel):
    """Result of exporting a single draft to RTM Inbox."""

    draft_id: str = Field(description="The draft that was exported.")
    external_ref: str | None = Field(
        default=None, description="Opaque ID returned by the task tracker."
    )
    success: bool = Field(default=False, description="Whether the export succeeded.")
    error: str | None = Field(default=None, description="Error message if failed.")


class BrainDumpSession(StrictBaseModel):
    """Owner-scoped brain dump session with flat ordered drafts."""

    id: str = Field(description="Unique session identifier.")
    owner_id: str = Field(description="Owner user ID.")
    status: SessionStatus = Field(description="Current session lifecycle state.")
    drafts: list[Draft] = Field(
        default_factory=list,
        description="Flat ordered list of provisional task drafts.",
    )
    export_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Results of exporting drafts to RTM Inbox on save.",
    )
    created_at: datetime = Field(description="When the session was created.")
    updated_at: datetime = Field(description="When the session was last updated.")
    revision: int = Field(
        default=1, ge=1, description="Optimistic-concurrency revision."
    )


# --- API request / response schemas ---


class CreateSessionResponse(StrictBaseModel):
    """Response for POST /brain-dump/sessions."""

    id: str = Field(description="Session identifier.")
    status: SessionStatus = Field(description="Current session status.")
    drafts: list[Draft] = Field(default_factory=list, description="Current drafts.")
    revision: int = Field(description="Session revision for optimistic concurrency.")


class SessionDetailResponse(StrictBaseModel):
    """Response for GET /brain-dump/sessions/{id}."""

    id: str = Field(description="Session identifier.")
    status: SessionStatus = Field(description="Current session status.")
    drafts: list[Draft] = Field(default_factory=list, description="Current drafts.")
    export_results: list[dict[str, Any]] = Field(
        default_factory=list, description="Export results if saved."
    )
    revision: int = Field(description="Session revision.")


class UploadAudioResponse(StrictBaseModel):
    """Response for POST /brain-dump/sessions/{id}/audio."""

    id: str = Field(description="Session identifier.")
    status: SessionStatus = Field(description="Updated session status.")
    drafts: list[Draft] = Field(
        default_factory=list, description="All drafts including newly extracted ones."
    )
    revision: int = Field(description="Updated session revision.")


class DraftUpdateRequest(StrictBaseModel):
    """Payload for PATCH /brain-dump/sessions/{id}/drafts/{draft_id}.

    Only the text of an existing draft may be edited.
    """

    text: str = Field(description="Updated draft text.")


class SaveSessionResponse(StrictBaseModel):
    """Response for POST /brain-dump/sessions/{id}/save."""

    id: str = Field(description="Session identifier.")
    status: SessionStatus = Field(description="Final session status.")
    export_results: list[ExportResult] = Field(
        default_factory=list,
        description="Per-draft export results to RTM Inbox.",
    )
    revision: int = Field(description="Final session revision.")


__all__ = [
    "BrainDumpSession",
    "CreateSessionResponse",
    "Draft",
    "DraftUpdateRequest",
    "ExportResult",
    "SaveSessionResponse",
    "SessionDetailResponse",
    "SessionStatus",
    "UploadAudioResponse",
]
