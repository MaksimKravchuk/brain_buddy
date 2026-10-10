"""The explicit SQLite unit of work for Tasks, Review and job intents (spec 026 PR-25).

026-FR-006: a command's aggregate writes and the job intents it generates are
one durable fact. They share the Tasks SQLite file, so they share one
transaction on one connection and commit once.

``TaskUnitOfWork.begin(owner_id)`` takes the owner's writer lock (the job fence
and scope are re-checked inside it, 026-FR-014/-SC-007), opens the single
``BEGIN IMMEDIATE`` transaction, and binds it to the thread. From then on:

* every finite write entry point of ``TaskRepository`` and the Review mixin
  joins that connection, is checked to be for the unit's owner, and is recorded
  in :attr:`OwnerUnitOfWork.writes`;
* :meth:`OwnerUnitOfWork.schedule` inserts a job intent on the same connection;
* JSON mirrors are written only after the commit, so a rollback leaves none;
* the transaction commits once when the block ends, and rolls everything back
  when it raises.

What it is not: it opens no second database and it does not make independently
committed writes atomic. Writes made outside a unit keep their own commits, and
other modules' stores (voice, agents, CRT) are separate files with their own
locks. The unit is not re-entrant: one per thread.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.exceptions import ConflictError, NotFoundError, RepositoryError
from app.modules.tasks.domain import ProjectDocument, TagDocument, TaskDocument
from app.modules.tasks.jobs import JobRepository
from app.modules.tasks.jobs.domain import MAX_ATTEMPTS, SYSTEM_SCOPE
from app.modules.tasks.jobs.execution import owner_write_lock
from app.modules.tasks.repository import TaskRepository


class UnitOfWorkError(RepositoryError):
    """A write or read was attempted outside the boundary of the open unit."""


SchedulerConnectionT_contra = TypeVar("SchedulerConnectionT_contra", contravariant=True)


class OwnerRepository(Protocol):
    """The aggregate read port; transaction ownership stays in its adapter."""

    def get_for_owner(self, task_id: str, *, owner_id: str) -> TaskDocument: ...
    def get_project_for_owner(
        self, project_id: str, *, owner_id: str
    ) -> ProjectDocument: ...
    def get_tag_for_owner(self, tag_id: str, *, owner_id: str) -> TagDocument: ...


class JobScheduler(Protocol[SchedulerConnectionT_contra]):
    def schedule_in(
        self,
        conn: SchedulerConnectionT_contra,
        *,
        job_type: str,
        dedup_key: str,
        run_at: datetime,
        scope: str = SYSTEM_SCOPE,
        payload_ref: str | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        correlation_id: str | None = None,
        pull_forward: bool = False,
    ) -> bool: ...


class ReadSetChangedError(ConflictError):
    """A row a command decided on is no longer what it read."""

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            resource,
            identifier,
            f"{resource} '{identifier}' changed after it was read.",
        )


@dataclass(frozen=True, slots=True)
class JobIntent:
    """A job a command asks for; created in the command's own commit."""

    job_type: str
    dedup_key: str
    run_at: datetime
    scope: str = SYSTEM_SCOPE
    payload_ref: str | None = None
    max_attempts: int = MAX_ATTEMPTS
    correlation_id: str | None = None
    pull_forward: bool = False


@dataclass(frozen=True, slots=True)
class WriteRecord:
    """One repository write made inside a unit."""

    resource: str
    owner_id: str
    record_id: str


def fingerprint(model: BaseModel | None) -> str | None:
    """Stable digest of a stored row; ``None`` for a row that is absent."""

    if model is None:
        return None
    body = json.dumps(model.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ReadSet:
    """The complete set of rows one command decided on, as it read them.

    Loaded under the owner lock, it is consistent by construction. A later unit
    can :meth:`OwnerUnitOfWork.verify` it, which is how a command that had to
    release the lock (a provider call, say) proves nothing moved meanwhile.
    ``None`` records a row that was absent, so a concurrent create is a change.
    """

    owner_id: str
    tasks: Mapping[str, TaskDocument | None]
    projects: Mapping[str, ProjectDocument | None]
    tags: Mapping[str, TagDocument | None]
    fingerprints: Mapping[tuple[str, str], str | None]


class OwnerUnitOfWork[ConnectionT]:
    """The open transaction of one owner; created only by ``TaskUnitOfWork``."""

    def __init__(
        self,
        owner_id: str,
        repo: OwnerRepository,
        jobs: JobScheduler[ConnectionT],
        conn: ConnectionT,
    ) -> None:
        self.owner_id = owner_id
        self._repo = repo
        self._jobs = jobs
        self._conn = conn
        self._open = True
        self._writes: list[WriteRecord] = []
        self._intents: list[JobIntent] = []
        self._activity = 0
        self._after_commit: list[Callable[[], None]] = []

    @property
    def connection(self) -> ConnectionT:
        """Only the open unit exposes its adapter's transaction connection."""
        self._require_open()
        return self._conn

    @property
    def activity(self) -> int:
        """Write/schedule activity, including an existing job's pull-forward.

        ``intents`` remains created-only. Receipt no-op/rejection/replay guards
        also need to detect schedule_in's updates that return False.
        """
        return self._activity

    @property
    def writes(self) -> tuple[WriteRecord, ...]:
        return tuple(self._writes)

    @property
    def intents(self) -> tuple[JobIntent, ...]:
        """The intents that created a job (a deduplicated one adds none)."""

        return tuple(self._intents)

    def _require_open(self) -> None:
        if not self._open:
            raise UnitOfWorkError("The unit of work has ended.")

    # --- what the repositories call ---------------------------------------------

    def record_write(self, owner_id: str, resource: str, record_id: str) -> None:
        self._require_open()
        if owner_id != self.owner_id:
            raise UnitOfWorkError(
                f"{resource} '{record_id}' belongs to another owner than the "
                "unit's owner lock."
            )
        self._writes.append(WriteRecord(resource, owner_id, record_id))
        self._activity += 1

    def after_commit(self, action: Callable[[], None]) -> None:
        self._require_open()
        self._after_commit.append(action)

    # --- job intents ------------------------------------------------------------

    def schedule(self, intent: JobIntent) -> bool:
        """Insert ``intent`` on this unit's connection; ``False`` if one is active."""

        self._require_open()
        if intent.scope not in (self.owner_id, SYSTEM_SCOPE):
            raise UnitOfWorkError(
                f"A job scope of another owner cannot be scheduled by '{self.owner_id}'."
            )
        self._activity += 1
        created = self._jobs.schedule_in(
            self._conn,
            job_type=intent.job_type,
            dedup_key=intent.dedup_key,
            run_at=intent.run_at,
            scope=intent.scope,
            payload_ref=intent.payload_ref,
            max_attempts=intent.max_attempts,
            correlation_id=intent.correlation_id,
            pull_forward=intent.pull_forward,
        )
        if created:
            self._intents.append(intent)
        return created

    # --- read sets --------------------------------------------------------------

    def load(
        self,
        *,
        tasks: Sequence[str] = (),
        projects: Sequence[str] = (),
        tags: Sequence[str] = (),
    ) -> ReadSet:
        """Read the named rows of this owner under the write lock.

        Another owner's id, or an unknown one, reads as absent.
        """

        self._require_open()
        task_rows = {i: self._task(i) for i in dict.fromkeys(tasks)}
        project_rows = {i: self._project(i) for i in dict.fromkeys(projects)}
        tag_rows = {i: self._tag(i) for i in dict.fromkeys(tags)}
        return ReadSet(
            owner_id=self.owner_id,
            tasks=task_rows,
            projects=project_rows,
            tags=tag_rows,
            fingerprints={
                **{("Task", i): fingerprint(row) for i, row in task_rows.items()},
                **{("Project", i): fingerprint(row) for i, row in project_rows.items()},
                **{("Tag", i): fingerprint(row) for i, row in tag_rows.items()},
            },
        )

    def verify(self, read_set: ReadSet) -> None:
        """Raise unless every row of ``read_set`` is still exactly as it was read."""

        self._require_open()
        if read_set.owner_id != self.owner_id:
            raise UnitOfWorkError("The read set belongs to another owner.")
        current = {"Task": self._task, "Project": self._project, "Tag": self._tag}
        for (resource, row_id), expected in read_set.fingerprints.items():
            if fingerprint(current[resource](row_id)) != expected:
                raise ReadSetChangedError(resource, row_id)

    def _task(self, task_id: str) -> TaskDocument | None:
        try:
            return self._repo.get_for_owner(task_id, owner_id=self.owner_id)
        except NotFoundError:
            return None

    def _project(self, project_id: str) -> ProjectDocument | None:
        try:
            return self._repo.get_project_for_owner(project_id, owner_id=self.owner_id)
        except NotFoundError:
            return None

    def _tag(self, tag_id: str) -> TagDocument | None:
        try:
            return self._repo.get_tag_for_owner(tag_id, owner_id=self.owner_id)
        except NotFoundError:
            return None

    # --- lifecycle --------------------------------------------------------------

    def _end(self) -> None:
        self._open = False

    def _run_after_commit(self) -> None:
        pending, self._after_commit = self._after_commit, []
        for action in pending:
            action()


class TaskUnitOfWork:
    """Opens one owner-scoped transaction over Tasks, Review and the job ledger."""

    def __init__(self, repo: TaskRepository, jobs: JobRepository) -> None:
        if repo.db_path != jobs.db_path:
            raise ValueError(
                "A unit of work needs the tasks and the jobs in the same SQLite file."
            )
        self._repo = repo
        self._jobs = jobs

    @contextmanager
    def begin(
        self, owner_id: str, *, cleanup: bool = False
    ) -> Iterator[OwnerUnitOfWork[Connection]]:
        """Hold ``owner_id``'s writer lock; commit once on exit, roll back on error.

        A bound job execution is re-checked under the lock before the body
        runs (``cleanup`` is the narrower owner check for retention only).
        """

        if self._repo.active_unit() is not None or self._repo.holds_owner_lock():
            raise UnitOfWorkError(
                "A unit of work is already open on this thread; "
                "the owner lock is not re-entrant."
            )
        with self._repo.writer_guard():
            with owner_write_lock(self._repo, owner_id, cleanup=cleanup):
                unit = OwnerUnitOfWork(
                    owner_id, self._repo, self._jobs, self._repo.active_connection()
                )
                self._repo.bind_unit(unit)
                try:
                    yield unit
                finally:
                    self._repo.bind_unit(None)
                    unit._end()
            # The SQLite transaction has committed; keep the writer guard until
            # every mirror is published so newer writes and purges follow it.
            unit._run_after_commit()


__all__ = [
    "JobIntent",
    "OwnerUnitOfWork",
    "ReadSet",
    "ReadSetChangedError",
    "TaskUnitOfWork",
    "UnitOfWorkError",
    "WriteRecord",
    "fingerprint",
]
