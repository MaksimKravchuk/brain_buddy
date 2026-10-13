"""Public Review projection and the legacy Review command boundary (spec 026 PR-28).

026-FR-005/006/014/016/022: a Review writer is a legacy command. It runs inside
the one owner unit of work, its writes are projected here into complete public
upserts and tombstones, and ``receipts.command`` commits the receipt and the
feed transaction with them.

The projection reads what the command wrote (``OwnerUnitOfWork.writes``), never
the command's own idea of what changed, so a Python rule, the Rust core and a
repair all publish the same stable keys. ``review_state``, queue counts and
advisory instants are *derived* queries over this base plus an explicit time and
are never a record kind. Private Undo and park snapshots, ``applied_progress``
fingerprints, sweep bookkeeping, consent history and usage reservations have no
public member and never leave this module.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Iterable, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from sqlite3 import Connection, connect
from typing import Any, Final, cast

from pydantic import BaseModel

from app.exceptions import (
    ConflictError,
    IdempotencyConflictError,
    IdempotencyReceiptUnavailableError,
    NotFoundError,
    ValidationFailure,
)
from app.modules.tasks.domain import TaskDocument
from app.modules.tasks.repository import IDEMPOTENCY_RETENTION, TaskRepository
from app.modules.tasks.review_domain import (
    NavigatorConsentDocument,
    ReviewDecisionDocument,
    ReviewRequestError,
    ReviewSessionDocument,
)
from app.modules.tasks.rust_adapter import RustCore
from app.modules.tasks.rust_review_facade import (
    encode_decision,
    encode_receipt,
    encode_release,
    encode_session,
)
from app.modules.tasks.rust_task_facade import (
    _encode_park_ack,
    encode_settings,
    encode_task,
    instant,
)
from app.modules.tasks.sync.receipts import (
    Authority,
    CommandReceipts,
    CommandRequest,
    ReceiptCommand,
    SyncCommandError,
)
from app.modules.tasks.sync.unit_of_work import (
    OwnerUnitOfWork,
    TaskUnitOfWork,
    WriteRecord,
)
from app.utils.idempotency import idempotency_key_digest

Json = dict[str, Any]

UNDO_AVAILABLE_FOR: Final = timedelta(days=7)
"""How long a decision's server-only Undo snapshot lives (the advisory deadline)."""

PUBLIC_REVIEW_ENTITY_TYPES: Final = (
    "review_settings",
    "review_session",
    "review_decision_queue",
    "review_decision",
    "review_receipt",
    "review_park_ack",
    "review_bulk_release",
    "review_navigator_consent",
)

_ACTIVE: ContextVar[bool] = ContextVar("review_command_boundary_active", default=False)


def boundary_active() -> bool:
    """Whether a Review command is running inside the receipt boundary.

    The receipt is then the idempotency record, so the legacy
    ``idempotency_records`` row is not written a second time.
    """

    return _ACTIVE.get()


def public_value(value: Any) -> Any:
    """``value`` without any ``private`` member, at any depth."""

    if isinstance(value, dict):
        return {k: public_value(v) for k, v in value.items() if k != "private"}
    if isinstance(value, list):
        return [public_value(v) for v in value]
    return value


def _upsert(entity_type: str, value: Json) -> Json:
    return {
        "operation": "upsert",
        "entity_type": entity_type,
        "value": public_value(value),
    }


def _tombstone(entity_type: str, key: Sequence[str]) -> Json:
    return {
        "operation": "tombstone",
        "entity_type": entity_type,
        "record_key": list(key),
    }


def _optional(value: datetime | None) -> str | None:
    return None if value is None else instant(value)


def consent_value(consent: NavigatorConsentDocument) -> Json:
    """The public consent record: provider, status and times, no history."""

    return {
        "provider": consent.provider,
        "consent": {
            "granted_at": instant(consent.granted_at),
            "revoked_at": _optional(consent.revoked_at),
            "consent_text_version": consent.consent_text_version,
        },
    }


def decision_value(decision: ReviewDecisionDocument) -> Json:
    value = encode_decision(decision, private=False)
    if decision.undo is not None:
        value["undo_available_until"] = instant(
            decision.decided_at + UNDO_AVAILABLE_FOR
        )
    return value


def queue_value(
    session: ReviewSessionDocument,
    decisions: Iterable[ReviewDecisionDocument],
    existing: Collection[str] | None = None,
) -> Json:
    """The decision-step queue of a run.

    ``task_ids`` stays ``None`` until the run captured its queue, so a captured
    empty queue and an uncaptured one differ. Decided and set-aside ids follow
    the queue API (``ReviewFlowService._handled_decisions``): in captured queue
    order, only for cards the queue still lists (``existing``), and a decided
    card is never also set aside. An uncaptured queue is live, so its decided
    ids fall back to decision order.
    """

    stored = list(decisions)
    decided = {d.task_id for d in stored}
    if session.decision_queue is None:
        ordered = sorted(stored, key=lambda d: (d.decided_at, d.id))
        return {
            "session_id": session.id,
            "task_ids": None,
            "decided_task_ids": list(dict.fromkeys(d.task_id for d in ordered)),
            "set_aside_task_ids": [
                t for t in session.set_aside_task_ids if t not in decided
            ],
        }
    listed = [t for t in session.decision_queue if existing is None or t in existing]
    aside = set(session.set_aside_task_ids) - decided
    return {
        "session_id": session.id,
        "task_ids": list(session.decision_queue),
        "decided_task_ids": [t for t in listed if t in decided],
        "set_aside_task_ids": [t for t in listed if t in aside],
    }


class ReviewProjection:
    """Documents of one owner as complete public Review changes."""

    def __init__(self, repo: TaskRepository, core: RustCore | None = None) -> None:
        self._repo = repo
        self._core = core

    # ----------------------------------------------------------- one record
    def session_changes(
        self, owner_id: str, session: ReviewSessionDocument
    ) -> list[Json]:
        return [
            _upsert("review_session", encode_session(session)),
            self._queue(owner_id, session),
        ]

    def _queue(self, owner_id: str, session: ReviewSessionDocument) -> Json:
        decisions = self._repo.list_review_decisions_for_session(owner_id, session.id)
        existing = (
            None
            if session.decision_queue is None
            else {t.id for t in self._repo.list_for_owner(owner_id=owner_id)}
        )
        return _upsert(
            "review_decision_queue", queue_value(session, decisions, existing)
        )

    # ------------------------------------------------------------ snapshots
    def snapshot(self, owner_id: str) -> list[Json]:
        """Every public Review record of the owner, as of one read."""

        repo = self._repo
        changes: list[Json] = []
        settings = repo.get_review_settings(owner_id)
        if settings is not None:
            changes.append(_upsert("review_settings", encode_settings(settings)))
        for session in repo.list_review_sessions(owner_id):
            changes.extend(self.session_changes(owner_id, session))
        changes.extend(
            _upsert("review_decision", decision_value(d))
            for d in repo.list_review_decisions(owner_id)
        )
        changes.extend(
            _upsert("review_receipt", encode_receipt(r))
            for r in repo.list_review_receipts(owner_id)
        )
        changes.extend(
            _upsert("review_park_ack", _encode_park_ack(a))
            for a in repo.list_park_acks(owner_id)
        )
        changes.extend(
            _upsert("review_bulk_release", encode_release(r))
            for r in repo.list_bulk_releases(owner_id)
        )
        changes.extend(
            _upsert("review_navigator_consent", consent_value(c))
            for c in repo.list_navigator_consents(owner_id)
        )
        return changes

    def public(self, changes: Sequence[Json]) -> list[Json]:
        """``changes`` as the feed would publish them (through the core codec)."""

        if self._core is None:
            raise RuntimeError("A core is needed to apply the feed's public codec.")
        encoded = json.dumps(list(changes), separators=(",", ":")).encode()
        return cast(list[Json], json.loads(self._core.persistence("changes", encoded)))

    # --------------------------------------------------------------- writes
    def changes_for_writes(
        self, owner_id: str, writes: Iterable[WriteRecord]
    ) -> list[Json]:
        """Upserts and tombstones for the rows one unit wrote, in write order.

        A row that exists is an upsert of its current public state; one that
        does not is a tombstone. A run is published with its queue, and a
        decision's run republishes its queue because the decided ids derive
        from the decisions.
        """

        seen: set[tuple[str, str]] = set()
        changes: list[Json] = []
        queues: dict[str, None] = {}
        for write in writes:
            marker = (write.resource, write.record_id)
            if write.owner_id != owner_id or marker in seen:
                continue
            seen.add(marker)
            changes.extend(self._project(owner_id, write, queues))
        for session_id in queues:
            session = self._repo.get_review_session(owner_id, session_id)
            if session is not None and ("Review session", session_id) not in seen:
                changes.append(self._queue(owner_id, session))
        return changes

    def _project(
        self, owner_id: str, write: WriteRecord, queues: dict[str, None]
    ) -> list[Json]:
        project = {
            "Review settings": self._settings,
            "Review session": self._session,
            "Review receipt": self._receipt,
            "Park acknowledgement": self._park_ack,
            "Bulk release": self._bulk_release,
            "Navigator consent": self._consent,
            "Task": self._task,
        }.get(write.resource)
        if write.resource == "Review decision":
            return self._decision(owner_id, write.record_id, queues)
        # Idempotency rows and navigator usage have no public projection.
        return [] if project is None else project(owner_id, write.record_id)

    def _settings(self, owner_id: str, _record_id: str) -> list[Json]:
        settings = self._repo.get_review_settings(owner_id)
        if settings is None:
            return []
        return [_upsert("review_settings", encode_settings(settings))]

    def _session(self, owner_id: str, record_id: str) -> list[Json]:
        session = self._repo.get_review_session(owner_id, record_id)
        return [] if session is None else self.session_changes(owner_id, session)

    def _decision(
        self, owner_id: str, record_id: str, queues: dict[str, None]
    ) -> list[Json]:
        decision = self._repo.get_review_decision(owner_id, record_id)
        if decision is None:
            return [_tombstone("review_decision", [record_id])]
        if decision.session_id is not None:
            queues[decision.session_id] = None
        return [_upsert("review_decision", decision_value(decision))]

    def _receipt(self, owner_id: str, record_id: str) -> list[Json]:
        task_id, _, kind = record_id.rpartition(":")
        receipt = self._repo.get_review_receipt(owner_id, task_id, kind)
        if receipt is None:
            return [_tombstone("review_receipt", [task_id, kind])]
        return [_upsert("review_receipt", encode_receipt(receipt))]

    def _park_ack(self, owner_id: str, record_id: str) -> list[Json]:
        task_id, _, formulation_id = record_id.partition(":")
        ack = self._repo.get_park_ack(owner_id, task_id, formulation_id)
        return (
            [] if ack is None else [_upsert("review_park_ack", _encode_park_ack(ack))]
        )

    def _bulk_release(self, owner_id: str, record_id: str) -> list[Json]:
        release = self._repo.get_bulk_release(owner_id, record_id)
        if release is None:
            return []
        return [_upsert("review_bulk_release", encode_release(release))]

    def _consent(self, owner_id: str, record_id: str) -> list[Json]:
        consent = next(
            (
                c
                for c in self._repo.list_navigator_consents(owner_id)
                if c.provider == record_id
            ),
            None,
        )
        if consent is None:
            return []
        return [_upsert("review_navigator_consent", consent_value(consent))]

    def _task(self, owner_id: str, record_id: str) -> list[Json]:
        try:
            task: TaskDocument = self._repo.get_for_owner(record_id, owner_id=owner_id)
        except NotFoundError:
            return [_tombstone("task", [record_id])]
        return [_upsert("task", encode_task(task))]


class ReviewCommandBoundary:
    """Runs a legacy Review command as one receipt, one unit and one feed commit."""

    def __init__(
        self,
        receipts: CommandReceipts[Connection],
        units: TaskUnitOfWork,
        authority: Authority[Connection],
        repo: TaskRepository,
        core: RustCore,
    ) -> None:
        self._receipts = receipts
        self._units = units
        self._authority = authority
        self._repo = repo
        self.projection = ReviewProjection(repo, core)

    def has_key(self, owner_id: str, key: str) -> bool:
        """Whether a receipt already owns this legacy key (replay under flag OFF)."""

        with connect(self._repo.db_path) as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM sync_legacy_keys WHERE owner_id=? AND key_digest=?",
                    (owner_id, idempotency_key_digest(key)),
                ).fetchone()
                is not None
            )

    @contextmanager
    def _executing(self) -> Any:
        token = _ACTIVE.set(True)
        try:
            yield
        finally:
            _ACTIVE.reset(token)

    def run[Result](  # noqa: PLR0913 - the command's whole context
        self,
        request: CommandRequest,
        *,
        owner_id: str,
        key: str,
        now: datetime,
        execute: Callable[[], Result],
        dump: Callable[[Result], Json | None],
        load: Callable[[Json | None], Result],
        recoverable: bool = False,
    ) -> Result:
        """Replay a known key; otherwise execute once and publish what it wrote.

        A replay is answered from the receipt. When its content was redacted
        (24 hours, or a deletion) only a ``recoverable`` command may answer from
        a matching stored record, and only if that answers without writing.
        """

        try:
            with self._receipts.command(
                self._units, request, self._authority, now=now
            ) as receipt:
                if receipt.replay is not None:
                    return self._replay(
                        receipt, execute=execute, load=load, recoverable=recoverable
                    )
                old = self._repo.get_idempotency(owner_id=owner_id, key=key)
                with self._executing():
                    result = execute()
                changes = self.projection.changes_for_writes(
                    owner_id, receipt.unit.writes
                )
                receipt.accept(
                    changes,
                    result=dump(result),
                    source_expires_at=(
                        old.created_at + IDEMPOTENCY_RETENTION
                        if old is not None
                        else None
                    ),
                )
                return result
        except SyncCommandError as exc:
            if exc.code == "IDEMPOTENCY_KEY_REUSED":
                raise IdempotencyConflictError() from None
            raise

    def _replay[Result](
        self,
        receipt: ReceiptCommand[Connection],
        *,
        execute: Callable[[], Result],
        load: Callable[[Json | None], Result],
        recoverable: bool,
    ) -> Result:
        replay = receipt.replay
        assert replay is not None
        if replay["outcome"] != "accepted":
            raise SyncCommandError("COMMAND_INTEGRITY")
        if not replay["result_redacted"]:
            return load(replay["result"])
        if not recoverable:
            raise IdempotencyReceiptUnavailableError()
        unit: OwnerUnitOfWork[Connection] = receipt.unit
        before = unit.activity
        try:
            with self._executing():
                result = execute()
        except (
            ConflictError,
            NotFoundError,
            ValidationFailure,
            ReviewRequestError,
        ):
            # The command's own preconditions failing during recovery (stale
            # revision, deleted target) means no stored record answers it.
            # Integrity and storage errors are not domain errors: they surface.
            raise IdempotencyReceiptUnavailableError() from None
        if unit.activity != before:
            raise IdempotencyReceiptUnavailableError()
        return result


def model_codec[ModelT: BaseModel](
    model: type[ModelT],
) -> tuple[Callable[[ModelT], Json | None], Callable[[Json | None], ModelT]]:
    """``dump``/``load`` of a command whose answer is a stored document."""

    def load(value: Json | None) -> ModelT:
        if value is None:
            raise SyncCommandError("COMMAND_INTEGRITY")
        return model.model_validate(value)

    return (lambda result: result.model_dump(mode="json")), load


def dict_codec() -> tuple[Callable[[Json], Json | None], Callable[[Json | None], Json]]:
    def load(value: Json | None) -> Json:
        if value is None:
            raise SyncCommandError("COMMAND_INTEGRITY")
        return value

    return (lambda result: dict(result)), load


def none_codec() -> tuple[Callable[[None], Json | None], Callable[[Json | None], None]]:
    return (lambda _result: None), (lambda _value: None)
