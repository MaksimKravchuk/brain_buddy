"""Python facade that delegates task and organization rules to the Rust core.

Spec 026 T018. While the ``rust_core_sync`` flag is on for an owner,
``TaskService`` asks this facade for the decision of ``task.create``,
``task.update`` (including the legacy whole ``tag_ids`` replacement, sent as one
``tag_changes`` edit), ``task.transition`` and the project and tag commands.
The facade is the Python half of the boundary (runtime-ffi.md "Pure core"):

* it loads the protected read set from the existing repositories, scoped to the
  records the command needs, under the owner lock the service already holds;
* it hands the shared core owned JSON values plus explicit execution inputs
  (instant, allocated IDs, origin), never a clock or a Python object;
* it maps a typed refusal back to the exception and message the REST adapter
  has always produced, and maps the returned change set back to the existing
  stored documents.

Authorization, idempotency, repository I/O and every response DTO stay in
``TaskService`` and the routes. Nothing here commits a second transaction: the
service writes the returned documents inside its own.

Native IDs for created records (``task_<uuid>``) are minted here, because the
core's ``parse_new`` refuses the legacy 12-hex shape for a new record.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from app.exceptions import (
    BrainBuddyError,
    ConflictError,
    NotFoundError,
    ValidationFailure,
)
from app.schemas.tasks import (
    ExpectedRevisionRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    TagCreateRequest,
    TagUpdateRequest,
    TaskCreateRequest,
    TaskTransitionRequest,
    TaskUpdateRequest,
)
from app.utils.identifiers import generate_id

from .domain import ProjectDocument, TagDocument, TaskDocument, TaskParkDocument
from .repository import (
    TaskRepository,
    display_project_name,
    display_tag_name,
    normalize_task_name,
)
from .review_domain import ReviewParkAckDocument, ReviewSettingsDocument
from .rust_adapter import Decision, DomainRefusal, RustCore

review_logger = logging.getLogger("app.modules.tasks.review")

_WAITING_REQUIRED: Final = "Waiting tasks require waiting_for."
_REOPEN: Final = "Reopen requires a terminal task and an open destination."
_MOVE: Final = "Move requires an open task and destination."
_DUPLICATE_TAGS: Final = "Task contexts/tags cannot contain duplicates."

# Reasons that map to one fixed message, the wording TaskService has always used.
_VALIDATION_MESSAGES: Final[dict[str, str]] = {
    "waiting_for_required": _WAITING_REQUIRED,
    "waiting_for_only_on_waiting_tasks": (
        "waiting_for can only be edited on Waiting tasks."
    ),
    "project_not_active": "Task project must be active.",
    "tag_not_active": "Task contexts must be active; task tags must be active.",
    "duplicate_tag": _DUPLICATE_TAGS,
    "reopen_requires_destination": _REOPEN,
    "task_not_closed": _REOPEN,
    "move_requires_destination": _MOVE,
    "move_requires_different_list": "Move requires a different open destination.",
}
_NOT_OPEN_BY_ACTION: Final[dict[str, str]] = {
    "complete": "Only open tasks can be completed.",
    "cancel": "Only open tasks can be cancelled.",
    "move": _MOVE,
}
_RESOURCES: Final[dict[str, str]] = {
    "task": "Task",
    "project": "Project",
    "tag": "Tag",
}
# Refusals about tag membership: a replacement list holding a duplicate is
# reported as that duplicate before any of its tags is looked at.
_TAG_REASONS: Final = frozenset({"tag_not_active", "duplicate_tag"})

Stored = TaskDocument | ProjectDocument | TagDocument


def instant(value: datetime) -> str:
    """An RFC 3339 UTC instant, with sub-second digits only when present."""

    utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc.isoformat().replace("+00:00", "Z")


def _optional_instant(value: datetime | None) -> str | None:
    return None if value is None else instant(value)


def _parse_instant(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


# ---------------------------------------------------------------- read-set encoding


def encode_task(task: TaskDocument) -> dict[str, Any]:
    """A stored task as the core's ``Task`` (the owner is the scope, not a field)."""

    formulation = None
    if task.formulation_id is not None and task.formulation_started_at is not None:
        formulation = {
            "id": task.formulation_id,
            "started_at": instant(task.formulation_started_at),
            "extended_at": _optional_instant(task.formulation_extended_at),
            "extension_reason": task.formulation_extension_reason,
            "park_floor_at": _optional_instant(task.formulation_park_floor_at),
        }
    return {
        "id": task.id,
        "title": task.title,
        "details": task.details,
        "state": task.state,
        "project_id": task.project_id,
        "tag_ids": list(task.tag_ids),
        "due_date": None if task.due_date is None else task.due_date.isoformat(),
        "priority": task.priority,
        "waiting_for": task.waiting_for,
        "waiting_since": _optional_instant(task.waiting_since),
        "order_key": str(task.order_key),
        "source_capture_ids": list(task.source_capture_ids),
        "created_at": instant(task.created_at),
        "updated_at": instant(task.updated_at),
        "completed_at": _optional_instant(task.completed_at),
        "cancelled_at": _optional_instant(task.cancelled_at),
        "revision": str(task.revision),
        "consecutive_stalled_formulations": task.consecutive_stalled_formulations,
        "formulation": formulation,
        "parked": None if task.parked is None else _encode_park(task.parked),
    }


def _encode_park(park: TaskParkDocument) -> dict[str, Any]:
    before = park.clock_before
    return {
        "at": instant(park.at),
        "formulation_id": park.formulation_id,
        "private": {
            "from_revision": str(park.from_revision),
            "clock_before": {
                "formulation_id": None,
                "started_at": instant(before.started_at),
                "extended_at": _optional_instant(before.extended_at),
                "extension_reason": before.extension_reason,
                "park_floor_at": _optional_instant(before.park_floor_at),
                "stalled_before": before.stalled_before,
            },
        },
    }


def encode_project(project: ProjectDocument) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "color": project.color,
        "state": project.state,
        "revision": str(project.revision),
        "desired_outcome": project.desired_outcome or None,
        "archived_at": _optional_instant(project.archived_at),
        "archived_before_lossless": project.archived_before_lossless,
        "created_at": instant(project.created_at),
    }


def encode_tag(tag: TagDocument) -> dict[str, Any]:
    # "archived" is a legacy-only stored value that the store rewrites to deleted.
    state = "deleted" if tag.state == "archived" else tag.state
    return {
        "id": tag.id,
        "name": tag.name,
        "state": state,
        "revision": str(tag.revision),
        "created_at": instant(tag.created_at),
    }


def encode_settings(settings: ReviewSettingsDocument) -> dict[str, Any]:
    return {
        "threshold_days": settings.threshold_days,
        "review_weekday": settings.review_weekday,
        "review_time": settings.review_time,
        "time_zone": settings.time_zone,
        "onboarded_at": _optional_instant(settings.onboarded_at),
        "activated_at": _optional_instant(settings.activated_at),
        "owner_park_floor_at": _optional_instant(settings.owner_park_floor_at),
        "revision": str(settings.revision),
    }


def _encode_park_ack(ack: ReviewParkAckDocument) -> dict[str, Any]:
    return {
        "task_id": ack.task_id,
        "formulation_id": ack.formulation_id,
        "parked_at": instant(ack.parked_at),
        "seen_at": _optional_instant(ack.seen_at),
        "returned_at": _optional_instant(ack.returned_at),
        "private": {"from_revision": str(ack.from_revision), "source": ack.source},
    }


# ---------------------------------------------------------------- change decoding


def decode_task(
    value: dict[str, Any], *, before: TaskDocument | None, owner_id: str
) -> TaskDocument:
    """The core's ``Task`` as a stored document, keeping its schema version."""

    clock = value["formulation"] or {}
    parked = value["parked"]
    return TaskDocument.model_validate(
        {
            "id": value["id"],
            "owner_id": owner_id,
            "title": value["title"],
            "details": value["details"],
            "state": value["state"],
            "project_id": value["project_id"],
            "tag_ids": value["tag_ids"],
            "due_date": value["due_date"],
            "priority": value["priority"],
            "waiting_for": value["waiting_for"],
            "waiting_since": value["waiting_since"],
            "order_key": int(value["order_key"]),
            "source_capture_ids": value["source_capture_ids"],
            "created_at": value["created_at"],
            "updated_at": value["updated_at"],
            "completed_at": value["completed_at"],
            "cancelled_at": value["cancelled_at"],
            "schema_version": 1 if before is None else before.schema_version,
            "revision": int(value["revision"]),
            "formulation_id": clock.get("id"),
            "formulation_started_at": clock.get("started_at"),
            "formulation_extended_at": clock.get("extended_at"),
            "formulation_extension_reason": clock.get("extension_reason"),
            "formulation_park_floor_at": clock.get("park_floor_at"),
            "consecutive_stalled_formulations": value[
                "consecutive_stalled_formulations"
            ],
            "parked": None if parked is None else _decode_park(parked),
        }
    )


def _decode_park(value: dict[str, Any]) -> dict[str, Any]:
    private = value["private"]
    before = private["clock_before"]
    return {
        "at": value["at"],
        "formulation_id": value["formulation_id"],
        "from_revision": int(private["from_revision"]),
        "clock_before": {
            "started_at": before["started_at"],
            "extended_at": before["extended_at"],
            "extension_reason": before["extension_reason"],
            "park_floor_at": before["park_floor_at"],
            "stalled_before": before["stalled_before"],
        },
    }


def decode_project(
    value: dict[str, Any],
    *,
    before: ProjectDocument | None,
    owner_id: str,
    now: datetime,
) -> ProjectDocument:
    return ProjectDocument.model_validate(
        {
            "id": value["id"],
            "owner_id": owner_id,
            "name": value["name"],
            "normalized_name": normalize_task_name(value["name"]),
            "color": value["color"],
            "state": value["state"],
            "created_at": now if before is None else before.created_at,
            "updated_at": now,
            "schema_version": 1 if before is None else before.schema_version,
            "revision": int(value["revision"]),
            "desired_outcome": value["desired_outcome"],
            "archived_at": value["archived_at"],
            "archived_before_lossless": value["archived_before_lossless"],
        }
    )


def decode_tag(
    value: dict[str, Any],
    *,
    before: TagDocument | None,
    owner_id: str,
    now: datetime,
) -> TagDocument:
    return TagDocument.model_validate(
        {
            "id": value["id"],
            "owner_id": owner_id,
            "name": value["name"],
            "normalized_name": normalize_task_name(
                value["name"], strip_tag_prefix=True
            ),
            "state": value["state"],
            "created_at": now if before is None else before.created_at,
            "updated_at": now,
            "schema_version": 1 if before is None else before.schema_version,
            "revision": int(value["revision"]),
        }
    )


# ---------------------------------------------------------------------- the facade


@dataclass(frozen=True, slots=True)
class Changes:
    """The records of one decided command, decoded; empty for an accepted no-op."""

    tasks: list[TaskDocument]
    projects: list[ProjectDocument]
    tags: list[TagDocument]
    park_acks: list[ReviewParkAckDocument]
    no_op: bool


@dataclass(frozen=True, slots=True)
class TransitionResult:
    task: TaskDocument
    park_ack: ReviewParkAckDocument | None


@dataclass(frozen=True, slots=True)
class TagDeleteResult:
    tag: TagDocument
    affected: list[TaskDocument]


class RustTaskFacade:
    """Decides task and organization commands with the shared Rust rules."""

    def __init__(self, core: RustCore, task_repo: TaskRepository) -> None:
        self._core = core
        self._repo = task_repo

    # ------------------------------------------------------------------ tasks

    def create_task(
        self, payload: TaskCreateRequest, *, owner_id: str, now: datetime
    ) -> TaskDocument:
        # The order key is one past the highest of the list, so that list is read.
        same_list = [
            task
            for task in self._repo.list_for_owner(owner_id=owner_id)
            if task.state == payload.state
        ]
        change = self._decide(
            "task.create",
            _native_id("task"),
            payload.model_dump(mode="json"),
            owner_id=owner_id,
            now=now,
            read_set=self._task_read_set(
                owner_id,
                tasks=same_list,
                project_ids=[payload.project_id],
                tag_ids=payload.tag_ids,
            ),
        )
        return change.tasks[0]

    def update_task(
        self,
        task: TaskDocument,
        payload: TaskUpdateRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> TaskDocument:
        """``PATCH /tasks/{id}``; the caller has loaded ``task`` (owner-scoped)."""

        fields = payload.model_fields_set
        body: dict[str, Any] = {}
        # A null title or priority is a request error that Python reports after
        # the revision check, so it is withheld from the core and raised once
        # the core has settled the revision.
        request_error: ValidationFailure | None = None
        if "title" in fields:
            if payload.title is None:
                request_error = ValidationFailure("Task title cannot be null.")
            else:
                body["title"] = payload.title
        if "priority" in fields:
            if payload.priority is not None:
                body["priority"] = payload.priority
            elif request_error is None:
                request_error = ValidationFailure("Task priority cannot be null.")
        for name in ("details", "project_id", "waiting_for"):
            if name in fields:
                body[name] = getattr(payload, name)
        if "due_date" in fields:
            body["due_date"] = (
                None if payload.due_date is None else payload.due_date.isoformat()
            )
        if payload.new_formulation_id is not None:
            body["new_formulation_id"] = payload.new_formulation_id
        requested_tags: list[str] | None = None
        duplicate_tags = False
        if "tag_ids" in fields:
            requested = list(payload.tag_ids or [])
            requested_tags = list(dict.fromkeys(requested))
            duplicate_tags = len(requested_tags) != len(requested)
            body["tag_changes"] = {
                "add_tag_ids": [t for t in requested_tags if t not in task.tag_ids],
                "remove_tag_ids": [t for t in task.tag_ids if t not in requested_tags],
            }
        decision = self._call(
            "task.update",
            task.id,
            body,
            owner_id=owner_id,
            now=now,
            read_set=self._task_read_set(
                owner_id,
                tasks=[task],
                project_ids=[
                    payload.project_id if "project_id" in fields else task.project_id
                ],
                tag_ids=[*(requested_tags or []), *task.tag_ids],
                settings=True,
            ),
            expected=("task", task.id, payload.expected_revision),
        )
        if decision.refusal is not None:
            raise _ordered_refusal(decision.refusal, request_error, duplicate_tags)
        if request_error is not None:
            raise request_error
        if duplicate_tags:
            raise ValidationFailure(_DUPLICATE_TAGS)
        updated = self._decode(decision, owner_id, now, {task.id: task}).tasks[0]
        if requested_tags is not None:
            # The legacy request names the stored order; the core settles the
            # membership and the adapter keeps the request's order.
            updated = updated.model_copy(update={"tag_ids": requested_tags})
        return updated

    def transition_task(
        self,
        task: TaskDocument,
        payload: TaskTransitionRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> TransitionResult:
        body: dict[str, Any] = {"action": payload.action}
        for name in ("to_state", "waiting_for", "new_formulation_id"):
            value = getattr(payload, name)
            if value is not None:
                body[name] = value
        read_set = self._task_read_set(
            owner_id, tasks=[task], project_ids=[], tag_ids=[], settings=True
        )
        stored_ack = self._park_ack_of(task, owner_id)
        if stored_ack is not None:
            read_set["park_acks"] = [_encode_park_ack(stored_ack)]
        change = self._decide(
            "task.transition",
            task.id,
            body,
            owner_id=owner_id,
            now=now,
            read_set=read_set,
            expected=("task", task.id, payload.expected_revision),
            action=payload.action,
            before={task.id: task},
            park_ack=stored_ack,
        )
        updated = change.tasks[0]
        if (
            not change.park_acks
            and task.parked is not None
            and task.state == "someday"
            and updated.state == "next"
        ):
            review_logger.warning(
                "review_park_return_unrecorded owner_id=%s task_id=%s "
                "formulation_id=%s",
                owner_id,
                task.id,
                task.parked.formulation_id,
            )
        return TransitionResult(
            updated, change.park_acks[0] if change.park_acks else None
        )

    # --------------------------------------------------------------- projects

    def create_project(
        self, payload: ProjectCreateRequest, *, owner_id: str, now: datetime
    ) -> ProjectDocument:
        change = self._decide(
            "project.create",
            _native_id("project"),
            payload.model_dump(mode="json"),
            owner_id=owner_id,
            now=now,
            read_set=self._organization_read_set(
                projects=self._repo.list_projects_for_owner(owner_id=owner_id)
            ),
            attempted_name=display_project_name(payload.name),
        )
        return change.projects[0]

    def update_project(
        self,
        project: ProjectDocument,
        payload: ProjectUpdateRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> ProjectDocument:
        fields = payload.model_fields_set
        body: dict[str, Any] = {}
        if payload.name is not None:
            body["name"] = payload.name
        for name in ("color", "desired_outcome"):
            if name in fields:
                body[name] = getattr(payload, name)
        change = self._decide(
            "project.update",
            project.id,
            body,
            owner_id=owner_id,
            now=now,
            read_set=self._organization_read_set(
                projects=self._repo.list_projects_for_owner(owner_id=owner_id)
            ),
            expected=("project", project.id, payload.expected_revision),
            attempted_name=display_project_name(payload.name or project.name),
            before={project.id: project},
        )
        return change.projects[0]

    def archive_project(
        self,
        project: ProjectDocument,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> ProjectDocument:
        change = self._decide(
            "project.archive",
            project.id,
            {},
            owner_id=owner_id,
            now=now,
            read_set=self._organization_read_set(projects=[project]),
            expected=("project", project.id, payload.expected_revision),
            before={project.id: project},
        )
        return change.projects[0]

    def unarchive_project(
        self,
        project: ProjectDocument,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> ProjectDocument | None:
        """The unarchived project, or ``None`` when it was already active."""

        change = self._decide(
            "project.unarchive",
            project.id,
            {},
            owner_id=owner_id,
            now=now,
            read_set=self._organization_read_set(
                projects=self._repo.list_projects_for_owner(owner_id=owner_id)
            ),
            expected=("project", project.id, payload.expected_revision),
            attempted_name=project.name,
            before={project.id: project},
        )
        return None if change.no_op else change.projects[0]

    # ------------------------------------------------------------------- tags

    def create_tag(
        self, payload: TagCreateRequest, *, owner_id: str, now: datetime
    ) -> TagDocument:
        change = self._decide(
            "tag.create",
            _native_id("tag"),
            payload.model_dump(mode="json"),
            owner_id=owner_id,
            now=now,
            read_set=self._organization_read_set(
                tags=self._repo.list_tags_for_owner(owner_id=owner_id)
            ),
            attempted_name=display_tag_name(payload.name),
        )
        return change.tags[0]

    def update_tag(
        self,
        tag: TagDocument,
        payload: TagUpdateRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> TagDocument:
        change = self._decide(
            "tag.update",
            tag.id,
            {} if payload.name is None else {"name": payload.name},
            owner_id=owner_id,
            now=now,
            read_set=self._organization_read_set(
                tags=self._repo.list_tags_for_owner(owner_id=owner_id)
            ),
            expected=("tag", tag.id, payload.expected_revision),
            attempted_name=display_tag_name(payload.name or tag.name),
            before={tag.id: tag},
        )
        return change.tags[0]

    def delete_tag(
        self,
        tag: TagDocument,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> TagDeleteResult:
        holders = [
            task
            for task in self._repo.list_for_owner(owner_id=owner_id)
            if tag.id in task.tag_ids
        ]
        read_set = self._organization_read_set(tags=[tag])
        read_set["tasks"] = {task.id: encode_task(task) for task in holders}
        change = self._decide(
            "tag.delete",
            tag.id,
            {},
            owner_id=owner_id,
            now=now,
            read_set=read_set,
            expected=("tag", tag.id, payload.expected_revision),
            before={tag.id: tag, **{task.id: task for task in holders}},
        )
        return TagDeleteResult(change.tags[0], change.tasks)

    # --------------------------------------------------------------- internals

    def _call(
        self,
        command_type: str,
        entity_id: str,
        body: dict[str, Any],
        *,
        owner_id: str,
        now: datetime,
        read_set: dict[str, Any],
        expected: tuple[str, str, int] | None = None,
    ) -> Decision:
        return self._core.decide(
            read_set,
            _envelope(command_type, entity_id, body, now, expected),
            _inputs(now, owner_id),
        )

    def _decide(
        self,
        command_type: str,
        entity_id: str,
        body: dict[str, Any],
        *,
        owner_id: str,
        now: datetime,
        read_set: dict[str, Any],
        expected: tuple[str, str, int] | None = None,
        action: str | None = None,
        attempted_name: str | None = None,
        before: dict[str, Stored] | None = None,
        park_ack: ReviewParkAckDocument | None = None,
    ) -> Changes:
        decision = self._call(
            command_type,
            entity_id,
            body,
            owner_id=owner_id,
            now=now,
            read_set=read_set,
            expected=expected,
        )
        if decision.refusal is not None:
            raise _refused(decision.refusal, action, attempted_name)
        return self._decode(decision, owner_id, now, before or {}, park_ack)

    @staticmethod
    def _decode(
        decision: Decision,
        owner_id: str,
        now: datetime,
        before: dict[str, Stored],
        park_ack: ReviewParkAckDocument | None = None,
    ) -> Changes:
        change_set = decision.change_set
        assert change_set is not None
        tasks: list[TaskDocument] = []
        projects: list[ProjectDocument] = []
        tags: list[TagDocument] = []
        acks: list[ReviewParkAckDocument] = []
        for change in change_set["changes"]:
            if change["operation"] != "upsert":
                raise ValidationFailure(
                    "Command failed validation.", {"reason": "unexpected_tombstone"}
                )
            kind, value = change["entity_type"], change["value"]
            prior = before.get(value.get("id", ""))
            if kind == "task":
                assert prior is None or isinstance(prior, TaskDocument)
                tasks.append(decode_task(value, before=prior, owner_id=owner_id))
            elif kind == "project":
                assert prior is None or isinstance(prior, ProjectDocument)
                projects.append(
                    decode_project(value, before=prior, owner_id=owner_id, now=now)
                )
            elif kind == "tag":
                assert prior is None or isinstance(prior, TagDocument)
                tags.append(decode_tag(value, before=prior, owner_id=owner_id, now=now))
            elif kind == "review_park_ack" and park_ack is not None:
                acks.append(
                    park_ack.model_copy(
                        update={"returned_at": _parse_instant(value["returned_at"])}
                    )
                )
        return Changes(tasks, projects, tags, acks, change_set["outcome"] == "no_op")

    def _park_ack_of(
        self, task: TaskDocument, owner_id: str
    ) -> ReviewParkAckDocument | None:
        if task.parked is None:
            return None
        return self._repo.get_park_ack(owner_id, task.id, task.parked.formulation_id)

    def _task_read_set(
        self,
        owner_id: str,
        *,
        tasks: list[TaskDocument],
        project_ids: list[str | None],
        tag_ids: list[str],
        settings: bool = False,
    ) -> dict[str, Any]:
        """Tasks, the projects and tags they reference, and the clock settings.

        A reference that does not exist is simply absent; the core reports it
        as ``not_found``, which maps to the same 404 the repository raises.
        """

        read_set: dict[str, Any] = {
            "tasks": {task.id: encode_task(task) for task in tasks},
            "projects": {},
            "tags": {},
        }
        for project_id in project_ids:
            if project_id is not None:
                try:
                    project = self._repo.get_project_for_owner(
                        project_id, owner_id=owner_id
                    )
                except NotFoundError:
                    continue
                read_set["projects"][project_id] = encode_project(project)
        for tag_id in tag_ids:
            try:
                tag = self._repo.get_tag_for_owner(tag_id, owner_id=owner_id)
            except NotFoundError:
                continue
            read_set["tags"][tag_id] = encode_tag(tag)
        if settings:
            stored = self._repo.get_review_settings(owner_id)
            if stored is not None:
                read_set["settings"] = encode_settings(stored)
        return read_set

    @staticmethod
    def _organization_read_set(
        *,
        projects: list[ProjectDocument] | None = None,
        tags: list[TagDocument] | None = None,
    ) -> dict[str, Any]:
        return {
            "projects": {p.id: encode_project(p) for p in projects or []},
            "tags": {t.id: encode_tag(t) for t in tags or []},
        }


# ------------------------------------------------------------------- envelope/inputs


def _native_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4()}"


def _envelope(
    command_type: str,
    entity_id: str,
    payload: dict[str, Any],
    now: datetime,
    expected: tuple[str, str, int] | None,
) -> dict[str, Any]:
    """A sync v1 envelope for one in-process REST command (origin ``legacy``)."""

    preconditions = []
    if expected is not None:
        entity_type, target, revision = expected
        preconditions.append(
            {
                "entity_type": entity_type,
                "entity_id": target,
                "edit_revision": str(revision),
            }
        )
    return {
        "protocol_version": 1,
        "command_id": str(uuid.uuid4()),
        "scope_id": "rest",
        "device_id": "rest",
        "device_epoch": "rest",
        "local_sequence": "0",
        "type": command_type,
        "command_version": 1,
        "entity_id": entity_id,
        "preconditions": preconditions,
        "depends_on": [],
        "issued_at": instant(now),
        "payload": payload,
    }


def _inputs(now: datetime, owner_id: str) -> dict[str, Any]:
    """Explicit execution facts; the formulation ID is minted here, not in Rust."""

    return {
        "rule_version": 1,
        "now": instant(now),
        "time_zone": "UTC",
        "origin": "legacy",
        "actor_id": owner_id,
        "authoritative": True,
        "allocated_ids": [generate_id("form")],
        "policy": {
            "weekly_review": False,
            "navigator_provider": None,
            "navigator_available": False,
            "consent_text_version": 1,
        },
    }


# ------------------------------------------------------------------- refusal mapping


def _ordered_refusal(
    refusal: DomainRefusal,
    request_error: ValidationFailure | None,
    duplicate_tags: bool,
) -> BrainBuddyError:
    """A ``PATCH`` refusal in the order Python reports its errors.

    Revision first, then a null title or priority, then waiting-for and the
    project, then a duplicate in the replacement list, then each tag.
    """

    if refusal.reason == "revision_conflict":
        return _refused(refusal)
    if request_error is not None:
        return request_error
    about_tag = refusal.reason in _TAG_REASONS or (
        refusal.reason == "not_found"
        and refusal.entity is not None
        and refusal.entity[0] == "tag"
    )
    if duplicate_tags and about_tag:
        return ValidationFailure(_DUPLICATE_TAGS)
    return _refused(refusal)


def _refused(
    refusal: DomainRefusal,
    action: str | None = None,
    attempted_name: str | None = None,
) -> BrainBuddyError:
    """The exception the REST adapter has always raised for this refusal."""

    reason = refusal.reason
    stored = _stored_record_refusal(refusal, attempted_name)
    if stored is not None:
        return stored
    if reason == "task_not_open":
        return ValidationFailure(_NOT_OPEN_BY_ACTION.get(action or "", _MOVE))
    if reason == "invalid_value" and refusal.field == "source_capture_ids":
        return ValidationFailure(
            "source_capture_ids require owner-scoped Capture validation."
        )
    message = _VALIDATION_MESSAGES.get(reason)
    if message is not None:
        return ValidationFailure(message)
    return ValidationFailure(
        "Command failed validation.", {"reason": reason, "field": refusal.field}
    )


def _stored_record_refusal(
    refusal: DomainRefusal, attempted_name: str | None
) -> BrainBuddyError | None:
    """Refusals about a stored record: stale, missing, duplicate or name clash."""

    reason = refusal.reason
    entity_type, key = refusal.entity or ("", [])
    resource = _RESOURCES.get(entity_type, "Record")
    identifier = key[0] if key else ""
    if reason == "revision_conflict":
        return ConflictError(
            resource,
            identifier,
            f"{resource} '{identifier}' has newer changes; reload before saving.",
        )
    if reason == "not_found":
        return NotFoundError(resource, identifier)
    if reason == "id_already_exists":
        return ConflictError(resource, identifier)
    if reason in {"duplicate_project_name", "unarchive_name_in_use"}:
        return ConflictError("Project", attempted_name or identifier)
    if reason == "duplicate_tag_name":
        return ConflictError("Tag", attempted_name or identifier)
    return None


__all__ = ["RustTaskFacade", "TagDeleteResult", "TransitionResult"]
