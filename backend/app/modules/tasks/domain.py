"""Canonical records owned by the native task module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import StorageBaseModel

from . import formulation

TaskState = Literal["inbox", "next", "waiting", "someday", "completed", "cancelled"]
TaskPriority = Literal["none", "low", "medium", "high"]
# "archived" is a legacy-only stored value; the SQLite migration rewrites it to
# "deleted" on load and no code path writes it. Kept for deserialization only.
TagState = Literal["active", "archived", "deleted"]
ProjectState = Literal["active", "archived"]


class IdempotencyRecord(StorageBaseModel):
    """Persisted result pointer for one owner-scoped mutating command."""

    key: str
    command: str
    request_hash: str
    resource_id: str
    response_body: dict[str, object]
    created_at: datetime


class ProjectDocument(StorageBaseModel):
    """An owner-scoped project; it is deliberately not linked to CRT trees."""

    id: str
    owner_id: str
    name: str = Field(min_length=1, max_length=500)
    normalized_name: str = Field(default="", max_length=500)
    color: str | None = Field(default=None, max_length=64)
    state: ProjectState = "active"
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


class TagDocument(StorageBaseModel):
    """An owner-scoped first-class task tag."""

    id: str
    owner_id: str
    name: str = Field(min_length=1, max_length=500)
    normalized_name: str = Field(default="", max_length=500)
    state: TagState = "active"
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


class TaskSubtaskDocument(StorageBaseModel):
    id: str
    owner_id: str
    task_id: str
    title: str = Field(min_length=1, max_length=500)
    order_key: int = Field(ge=0)
    state: Literal["open", "completed", "cancelled"] = "open"
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


class TaskCommentDocument(StorageBaseModel):
    id: str
    owner_id: str
    task_id: str
    actor_id: str
    body: str = Field(min_length=1, max_length=20_000)
    created_at: datetime
    edited_at: datetime | None = None
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


class ClockBeforeDocument(StorageBaseModel):
    """The formulation clock immediately before an auto-park closed it.

    Spec 020 (data-model E1): kept so the yield rule restores it exactly; it is
    server-side only and not part of ``TaskResponse``.
    """

    started_at: datetime
    extended_at: datetime | None = None
    extension_reason: str | None = Field(default=None, min_length=1, max_length=500)
    park_floor_at: datetime | None = None
    stalled_before: int = Field(default=0, ge=0)


class TaskParkDocument(StorageBaseModel):
    """``TaskDocument.parked``: written only by auto-park (data-model E1)."""

    at: datetime
    formulation_id: str
    from_revision: int = Field(ge=1)
    clock_before: ClockBeforeDocument


class TaskDocument(StorageBaseModel):
    """A mutable, owner-scoped task; it is never a CRT node."""

    id: str
    owner_id: str
    title: str = Field(min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=20_000)
    state: TaskState
    project_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)
    due_date: date | None = None
    priority: TaskPriority = "none"
    waiting_for: str | None = Field(default=None, max_length=500)
    waiting_since: datetime | None = None
    order_key: int = Field(ge=0)
    source_capture_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)
    # Spec 020 formulation clock (data-model E1, contracts/formulation-clock.md
    # §2). Optional with defaults, so payloads written before it load unchanged.
    formulation_id: str | None = None
    formulation_started_at: datetime | None = None
    formulation_extended_at: datetime | None = None
    formulation_extension_reason: str | None = Field(
        default=None, min_length=1, max_length=500
    )
    formulation_park_floor_at: datetime | None = None
    consecutive_stalled_formulations: int = Field(default=0, ge=0)
    parked: TaskParkDocument | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_context_ids(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tag_ids" not in data and "context_ids" in data:
            data = {**data, "tag_ids": data.get("context_ids") or []}
        return data


class FormulationSettingsDocument(StorageBaseModel):
    """The owner clock settings one stored response was projected with.

    Spec 020 (contracts/http.md §2, "Mutations"): the derived instants of
    ``TaskResponse.formulation`` depend on these values, and a same-key replay
    returns the original response. An idempotency record therefore keeps them
    and a replay projects with them, not with the live settings. A record
    written before this snapshot existed has none and projects live.
    """

    threshold_days: int
    time_zone: str
    owner_park_floor_at: datetime | None = None
    activated_at: datetime | None = None

    @classmethod
    def of(
        cls, settings: formulation.OwnerClockSettings
    ) -> FormulationSettingsDocument:
        return cls(
            threshold_days=settings.threshold_days,
            time_zone=settings.time_zone,
            owner_park_floor_at=settings.owner_park_floor_at,
            activated_at=settings.activated_at,
        )

    def clock_settings(self) -> formulation.OwnerClockSettings:
        return formulation.OwnerClockSettings(
            threshold_days=self.threshold_days,
            time_zone=self.time_zone,
            owner_park_floor_at=self.owner_park_floor_at,
            activated_at=self.activated_at,
        )


class SmartAddCreatedDocument(StorageBaseModel):
    """Classification records created by one Smart Add command."""

    project_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)


class SmartAddTaskResultDocument(StorageBaseModel):
    """Composite idempotency payload for a Smart Add task command."""

    task: TaskDocument
    project: ProjectDocument | None = None
    tags: list[TagDocument] = Field(default_factory=list)
    created: SmartAddCreatedDocument = Field(default_factory=SmartAddCreatedDocument)
    formulation_settings: FormulationSettingsDocument | None = None
