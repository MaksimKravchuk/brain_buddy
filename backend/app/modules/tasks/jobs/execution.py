"""Execution authority for background writers (spec 026 PR-21).

A durable job writes through the same compatible ports as the REST, CLI and MCP
adapters (026-FR-014). What differs is its authority: the claim that lets it
run, and the scope it runs for. Both can be withdrawn while the job is already
in flight -- the lease lapses and another worker takes over, an operator cancels
it, an account is removed -- so neither is trusted from the moment of the claim.

The adapter binds a :class:`JobExecution` around its body. Every task writer
lock taken through ``serialized_write`` or a Review sweep then re-checks, *under
that lock*, the job's current fence and the owner's current scope authority
before anything is persisted. The ledger shares the Tasks database, and the
writer lock holds its write transaction, so no heartbeat, cancel or claim can
change the fence between the check and the commit.

The writer origin is never an input. It is ``job`` exactly when an execution is
bound by the server and ``legacy`` otherwise; a caller that supplies one is
rejected before the lock is taken.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.exceptions import BrainBuddyError, ValidationFailure
from app.utils.time import utcnow

from .domain import SYSTEM_SCOPE, JobLease

#: Keyword a caller could try to smuggle in to pick its own writer origin.
WRITER_ORIGIN_FIELD = "writer_origin"

_EFFECT_NAMESPACE = "bb.job-effect.v1"


class WriterOrigin(StrEnum):
    """Who the server says is writing. Derived here, never read from a caller."""

    LEGACY = "legacy"
    JOB = "job"


class ExecutionRefused(BrainBuddyError):
    """A background writer no longer has authority for this write."""


class StaleExecutorError(ExecutionRefused):
    """The job's lease was lost, expired or cancelled: another claimant owns it."""

    def __init__(self, job_id: str, fence: int) -> None:
        super().__init__(f"Job '{job_id}' no longer holds fence {fence}.")
        self.job_id = job_id
        self.fence = fence


class ScopeRevokedError(ExecutionRefused):
    """The job's scope no longer covers the owner it tried to write for."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job '{job_id}' has no current authority for this write.")
        self.job_id = job_id


class ForgedWriterOriginError(ValidationFailure):
    """A caller supplied ``writer_origin``; only the server derives it."""

    def __init__(self) -> None:
        super().__init__(f"'{WRITER_ORIGIN_FIELD}' is derived by the server.")


class FenceLedger(Protocol):
    """The slice of the job ledger the recheck needs."""

    def should_abandon(self, job_id: str, *, fence: int, now: datetime) -> bool: ...


class TaskWriterLock(Protocol):
    """A task repository: the one owner-serialized writer lock."""

    def command_lock(self, owner_id: str) -> AbstractContextManager[None]: ...


@dataclass(frozen=True, slots=True)
class JobExecution:
    """The typed, server-derived context of one claimed run.

    ``effect_identity`` is derived once from the job's durable effect id. It
    deliberately excludes the fence, attempt and lease owner, so a retry or a
    renewed lease keeps the same identity while a different job never shares it.
    """

    job_id: str
    job_type: str
    scope: str
    fence: int
    effect_identity: str

    @property
    def writer_origin(self) -> WriterOrigin:
        return WriterOrigin.JOB

    def covers(self, owner_id: str) -> bool:
        """Whether the job's scope reaches ``owner_id``'s data."""

        return self.scope == SYSTEM_SCOPE or self.scope == owner_id


def derive_effect_identity(lease: JobLease) -> str:
    """Domain-separated identity for the internal effect of ``lease``'s job."""

    material = "\0".join(
        (_EFFECT_NAMESPACE, lease.effect_id, lease.job_type, lease.scope)
    )
    return "job-effect:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class JobExecutionGate:
    """Derives execution contexts and checks them at the write ports."""

    def __init__(
        self,
        ledger: FenceLedger,
        *,
        owner_current: Callable[[str], bool],
        owner_exists: Callable[[str], bool] | None = None,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._ledger = ledger
        # Identity is the authority for owners: True while the owner is live.
        self._owner_current = owner_current
        # The narrower check for cleanup: the owner only has to still exist, so
        # retention can finish what an owner with a pending deletion is owed.
        # Absent, cleanup is as strict as any other write.
        self._owner_exists = owner_exists or owner_current
        self._now = now

    def begin(self, lease: JobLease) -> JobExecution:
        """Derive the context for a freshly claimed lease. Checks nothing yet:
        authority is asserted at each write, under the writer lock."""

        return JobExecution(
            job_id=lease.job_id,
            job_type=lease.job_type,
            scope=lease.scope,
            fence=lease.fence,
            effect_identity=derive_effect_identity(lease),
        )

    @contextmanager
    def executing(self, lease: JobLease) -> Iterator[JobExecution]:
        """Bind the context of ``lease`` for every write made in the block."""

        execution = self.begin(lease)
        token = _BOUND.set(_Binding(execution, self))
        try:
            yield execution
        finally:
            _BOUND.reset(token)

    def authorize(
        self, execution: JobExecution, owner_id: str, *, cleanup: bool = False
    ) -> None:
        """Raise unless ``execution`` may write ``owner_id``'s data right now.

        ``cleanup`` is for destructive retention only: the fence and the job's
        scope are checked as always, but the owner need only still exist.
        """

        if self._ledger.should_abandon(
            execution.job_id, fence=execution.fence, now=self._now()
        ):
            raise StaleExecutorError(execution.job_id, execution.fence)
        allowed = self._owner_exists if cleanup else self._owner_current
        if not execution.covers(owner_id) or not allowed(owner_id):
            raise ScopeRevokedError(execution.job_id)


@dataclass(frozen=True, slots=True)
class _Binding:
    execution: JobExecution
    gate: JobExecutionGate


_BOUND: ContextVar[_Binding | None] = ContextVar("task_job_execution", default=None)


def current_execution() -> JobExecution | None:
    """The job execution bound to this thread of control, if any."""

    binding = _BOUND.get()
    return None if binding is None else binding.execution


def current_writer_origin() -> WriterOrigin:
    """The server-derived origin of a write made right now."""

    return WriterOrigin.LEGACY if _BOUND.get() is None else WriterOrigin.JOB


def reject_caller_origin(kwargs: Mapping[str, object]) -> None:
    """Refuse a command call that names its own writer origin."""

    if WRITER_ORIGIN_FIELD in kwargs:
        raise ForgedWriterOriginError()


def authorize_bound_write(owner_id: str, *, cleanup: bool = False) -> None:
    """Re-check a bound job's authority; a no-op for every other writer.

    Call with the owner's task writer lock held.
    """

    binding = _BOUND.get()
    if binding is not None:
        binding.gate.authorize(binding.execution, owner_id, cleanup=cleanup)


@contextmanager
def owner_write_lock(
    repo: TaskWriterLock, owner_id: str, *, cleanup: bool = False
) -> Iterator[None]:
    """The owner's task writer lock, with job authority re-checked inside it.

    Pass ``cleanup=True`` only for retention that deletes or nulls expired
    data, which must stay authorized while an owner's deletion is pending.
    """

    with repo.command_lock(owner_id):
        authorize_bound_write(owner_id, cleanup=cleanup)
        yield


__all__ = [
    "WRITER_ORIGIN_FIELD",
    "ExecutionRefused",
    "FenceLedger",
    "ForgedWriterOriginError",
    "JobExecution",
    "JobExecutionGate",
    "ScopeRevokedError",
    "StaleExecutorError",
    "WriterOrigin",
    "authorize_bound_write",
    "current_execution",
    "current_writer_origin",
    "derive_effect_identity",
    "owner_write_lock",
    "reject_caller_origin",
]
