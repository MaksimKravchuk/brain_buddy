"""Device-origin execution of the Review and Navigator consent commands (spec 026 PR-31d).

Runs inside the receipt unit the command route already opened, so the receipt id
is the device ``command_id`` and replay or lookup by it is exact. There is no new
domain rule: each command calls the same ``ReviewService``, ``ReviewFlowService``
or ``NavigatorService`` writer the web path does (the body ``serialized_write``
wraps, which would otherwise open a second receipt), and the feed transaction is
``ReviewProjection`` over what that writer wrote. Only the envelope is translated:
creation IDs come from ``entity_id``, ``expected_revision`` from the typed
preconditions, and a domain refusal becomes a rejected receipt with no feed change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from sqlite3 import Connection
from typing import Any, cast

from pydantic import ValidationError

from app.exceptions import (
    ConflictError,
    IdempotencyConflictError,
    NotFoundError,
    ValidationFailure,
)
from app.modules.tasks import formulation
from app.modules.tasks.navigator import NavigatorService, NavigatorStatus
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.review_domain import (
    AutoParkResultDocument,
    DecisionResultDocument,
    ReviewRequestError,
    ReviewSessionDocument,
    ReviewSettingsDocument,
    UndoResultDocument,
)
from app.modules.tasks.review_flow import (
    OpenSessionExistsError,
    ReviewFlowService,
    StepOutsideRunError,
)
from app.modules.tasks.review_service import ReviewService
from app.modules.tasks.rust_adapter import DomainRefusal, RustCore
from app.modules.tasks.rust_review_facade import (
    encode_release,
    encode_session,
)
from app.modules.tasks.rust_task_facade import encode_settings
from app.schemas.review import (
    AutoParkRequest,
    BulkReleaseRequest,
    DecisionRequest,
    ExplainerAcknowledgeRequest,
    NavigatorConsentGrantRequest,
    ParkAcknowledgeRequest,
    ReviewSettingsUpdateRequest,
    SessionFinishRequest,
    SessionProgressRequest,
    SessionStartRequest,
    UndoDecisionRequest,
)

from .device_executor import register_family
from .receipts import ReceiptCommand
from .review_projection import (
    ReviewProjection,
    consent_value,
    executing,
    public_value,
)
from .wire import DeviceCommandExecutor, ProtocolFailure

_SUPPORTED = frozenset(
    {
        "review.decide",
        "review.undo_decision",
        "review.auto_park",
        "review.explainer_ack",
        "review.settings",
        "review.parks_ack",
        "review.session_start",
        "review.session_progress",
        "review.session_finish",
        "review.bulk_release",
        "review.bulk_undo",
        "review.consent_grant",
        "review.consent_revoke",
    }
)
type Receipt = dict[str, Any]
type Json = dict[str, Any]

# The server's 409/400 reason codes of contracts/http.md, in the frozen refusal
# vocabulary of the core (``Reason``). A code not listed is an invalid value.
_REASONS = {
    "id_conflict": ("id_already_exists", "id"),
    "open_session_exists": ("id_already_exists", "replace_open"),
    "details_too_long": ("text_length", None),
    "provider_mismatch": ("provider_unavailable", "provider"),
    "consent_text_outdated": ("consent_text_outdated", "consent_text_version"),
    "decision_not_allowed": ("decision_not_allowed", None),
    "extension_already_used": ("extension_already_used", None),
    "extension_not_due": ("extension_not_due", None),
    "project_archived": ("project_archived", None),
    "undo_unavailable": ("undo_unavailable", None),
    "invalid_time_zone": ("invalid_time_zone", "time_zone"),
}
_ENTITIES = {
    "Task": "task",
    "Review session": "review_session",
    "Review settings": "review_settings",
}
_DOMAIN_ERRORS = (
    ConflictError,
    NotFoundError,
    ValidationFailure,
    ReviewRequestError,
    StepOutsideRunError,
)


def _invalid() -> ProtocolFailure:
    return ProtocolFailure("INVALID_REQUEST")


def _raw(method: Callable[..., Any]) -> Callable[..., Any]:
    """The command ``serialized_write`` wraps.

    The wrapper dispatches to the legacy receipt boundary, which would open a
    second receipt inside this one; the receipt here is the idempotency record.
    """
    return cast(Callable[..., Any], method.__wrapped__)  # type: ignore[attr-defined]


_DECIDE = _raw(ReviewService.decide)
_UNDO = _raw(ReviewService.undo_decision)
_AUTO_PARK = _raw(ReviewService.auto_park)
_EXPLAINER = _raw(ReviewService.acknowledge_explainer)
_SETTINGS = _raw(ReviewService.update_settings)
_PARKS = _raw(ReviewService.acknowledge_parks)
_START = _raw(ReviewFlowService.start_session)
_PROGRESS = _raw(ReviewFlowService.progress_session)
_FINISH = _raw(ReviewFlowService.finish_session)
_RELEASE = _raw(ReviewFlowService.bulk_release)
_RELEASE_UNDO = _raw(ReviewFlowService.undo_bulk_release)
_GRANT = _raw(NavigatorService.grant_consent)
_REVOKE = _raw(NavigatorService.revoke_consent)


class _RestResults:
    """Decision, Undo and auto-park results as the Review API returns them."""

    def __init__(self, review: ReviewService, owner: str) -> None:
        from app.api import review as rest  # noqa: PLC0415 - api is above modules

        self._rest, self._review, self._owner = rest, review, owner

    def decision(self, result: DecisionResultDocument) -> Json:
        response = self._rest.decision_response(result, self._review, self._owner)
        return response.model_dump(mode="json")

    def undo(self, result: UndoResultDocument) -> Json:
        response = self._rest.undo_response(result, self._review, self._owner)
        return response.model_dump(mode="json")

    def auto_park(self, result: AutoParkResultDocument) -> Json:
        response = self._rest.auto_park_response(result, self._review, self._owner)
        return response.model_dump(mode="json")


class ReviewDeviceExecutor:
    """``DeviceCommandExecutor`` for Review, Navigator consent and park commands."""

    def __init__(
        self,
        review: ReviewService,
        flow: ReviewFlowService,
        navigator: NavigatorService,
        repo: TaskRepository,
        projection: ReviewProjection,
    ) -> None:
        self._review, self._flow, self._navigator = review, flow, navigator
        self._repo, self._projection = repo, projection

    def supports(self, command_type: str) -> bool:
        return command_type in _SUPPORTED

    def _public(self, owner: str) -> _RestResults:
        """Task-bearing results in the REST response shape (one source of shape)."""
        return _RestResults(self._review, owner)

    def execute(
        self, command: ReceiptCommand[Connection], envelope: Mapping[str, Any]
    ) -> Receipt:
        try:
            blocked = self._dependencies(command, envelope)
            if blocked is not None:
                return blocked
            handler = getattr(self, "_" + envelope["type"].replace(".", "_"))
            return handler(command, envelope, dict(envelope["payload"]))  # type: ignore[no-any-return]
        except ValidationError:
            raise _invalid() from None

    # ------------------------------------------------------------- envelope
    @staticmethod
    def _receipt(command: ReceiptCommand[Connection], command_id: str) -> Any:
        return command.store._lookup(
            command.unit, command_id, command.authority, now=command.now
        )

    def _dependencies(
        self, command: ReceiptCommand[Connection], envelope: Mapping[str, Any]
    ) -> Receipt | None:
        """A pending predecessor is retryable; a rejected one is terminal."""
        pending: list[str] = []
        for dependency in envelope["depends_on"]:
            known = self._receipt(command, dependency)
            if known is None:
                pending.append(dependency)
            elif known["outcome"] == "rejected":
                return command.reject(
                    DomainRefusal("dependency_rejected", None, None, None)
                )
        if pending:
            raise ProtocolFailure(
                "DEPENDENCY_PENDING", details={"dependency_ids": pending}
            )
        return None

    def _expected(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        entity_type: str,
        entity_id: str,
    ) -> int:
        """``expected_revision`` from this entity's precondition (or its command)."""
        for item in envelope["preconditions"]:
            if "after_command" in item:
                ref = item["after_command"]
                if (ref["entity_type"], ref["entity_id"]) != (entity_type, entity_id):
                    continue
                if ref["command_id"] not in envelope["depends_on"]:
                    raise _invalid()
                return self._revision_after(command, ref, entity_type, entity_id)
            if (item["entity_type"], item["entity_id"]) == (entity_type, entity_id):
                return int(item["edit_revision"])
        raise _invalid()

    def _revision_after(
        self,
        command: ReceiptCommand[Connection],
        ref: Mapping[str, Any],
        entity_type: str,
        entity_id: str,
    ) -> int:
        receipt = self._receipt(command, ref["command_id"])
        for version in (receipt or {}).get("result_versions", []):
            key = version["record_key"]
            # The owner's settings are a singleton: their record key is empty.
            if version["entity_type"] == entity_type and (
                (key[-1] == entity_id if key else entity_type == "review_settings")
                and "edit_revision" in version
            ):
                return int(version["edit_revision"])
        raise _invalid()

    # ------------------------------------------------------------ execution
    def _run(
        self,
        command: ReceiptCommand[Connection],
        write: Callable[[], Any],
        dump: Callable[[Any], Json | None],
    ) -> Receipt:
        """One legacy writer inside the receipt unit, published as its feed commit.

        A refusal made before the writer wrote anything is a rejected receipt; one
        that follows a write cannot be rejected (the unit would hold the write), so
        it propagates and rolls the whole unit back.
        """
        owner, before = command.unit.owner_id, command.unit.activity
        try:
            with executing():
                result = write()
        except _DOMAIN_ERRORS as refused:
            if command.unit.activity != before:
                raise
            return command.reject(self._refusal(refused, owner))
        except IdempotencyConflictError:  # pragma: no cover - the key is unique
            raise ProtocolFailure("COMMAND_INTEGRITY") from None
        changes = self._projection.changes_for_writes(owner, command.unit.writes)
        return command.accept(changes, result=dump(result))

    def _refusal(self, error: Exception, owner: str) -> DomainRefusal:
        if isinstance(error, ConflictError):
            return self._stale(error, owner)
        if isinstance(error, NotFoundError):
            entity = _ENTITIES.get(error.resource)
            return DomainRefusal(
                "not_found" if entity != "review_session" else "session_not_found",
                None,
                None if entity is None else (entity, [error.identifier]),
                None,
            )
        if isinstance(error, StepOutsideRunError):
            return DomainRefusal("step_not_in_review", error.field, None, None)
        if isinstance(error, ReviewRequestError):
            reason, field = _REASONS.get(error.reason, ("invalid_value", None))
            named = (
                ("review_session", [error.session_id])
                if isinstance(error, OpenSessionExistsError) and error.session_id
                else None
            )
            return DomainRefusal(reason, field, named, None)
        return DomainRefusal("invalid_value", None, None, None)

    def _stale(self, error: ConflictError, owner: str) -> DomainRefusal:
        """A failed revision check, naming the record and the revision it is at."""
        entity = _ENTITIES.get(error.resource)
        current: int | None = None
        if entity == "task":
            try:
                current = self._repo.get_for_owner(
                    error.identifier, owner_id=owner
                ).revision
            except NotFoundError:
                current = None
        elif entity == "review_settings":
            settings = self._repo.get_review_settings(owner)
            current = None if settings is None else settings.revision
        if entity is None:
            return DomainRefusal("invalid_value", None, None, None)
        return DomainRefusal(
            "revision_conflict", None, (entity, [error.identifier]), current
        )

    def _owner_entity(
        self, command: ReceiptCommand[Connection], envelope: Mapping[str, Any]
    ) -> str:
        """Owner singletons (settings, consent) name the owner as their entity."""
        owner = command.unit.owner_id
        if envelope["entity_id"] != owner:
            raise _invalid()
        return owner

    @staticmethod
    def _empty(body: Mapping[str, Any]) -> None:
        if body:
            raise _invalid()

    # ------------------------------------------------------------ decisions
    def _review_decide(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner, task_id = command.unit.owner_id, envelope["entity_id"]
        if "expected_revision" in body or "decision_id" not in body:
            raise _invalid()
        request = DecisionRequest(
            **body, expected_revision=self._expected(command, envelope, "task", task_id)
        )
        missing = self._missing_client_id(owner, task_id, request)
        if missing is not None:
            return command.reject(DomainRefusal("invalid_value", missing, None, None))
        return self._run(
            command,
            lambda: _DECIDE(
                self._review,
                task_id,
                request,
                owner_id=owner,
                idempotency_key=command.command_id,
            ),
            lambda result: self._public(owner).decision(result),
        )

    def _missing_client_id(
        self, owner: str, task_id: str, request: DecisionRequest
    ) -> str | None:
        """The client-created id a decision needs and the device left out.

        The server never mints an id on a device command, or its feed would
        diverge from the offline client's own: a follow-up needs its task id, and
        a decision that starts a formulation needs that id (``first_step``,
        ``return_to_next`` and a substantive ``reformulate``).
        """
        if request.type == "follow_up" and request.follow_up_task_id is None:
            return "follow_up_task_id"
        if request.new_formulation_id is not None:
            return None
        starts = request.type in ("first_step", "return_to_next")
        if request.type == "reformulate":
            try:
                task = self._repo.get_for_owner(task_id, owner_id=owner)
            except NotFoundError:
                return None
            starts = formulation.is_substantive(task.title, request.title or "")
        return "new_formulation_id" if starts else None

    def _review_undo_decision(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner, decision_id = command.unit.owner_id, envelope["entity_id"]
        self._empty(body)
        decision = self._repo.get_review_decision(owner, decision_id)
        if decision is None:
            return command.reject(
                DomainRefusal(
                    "not_found", None, ("review_decision", [decision_id]), None
                )
            )
        request = UndoDecisionRequest(
            expected_task_revision=self._expected(
                command, envelope, "task", decision.task_id
            )
        )
        return self._run(
            command,
            lambda: _UNDO(
                self._review,
                decision_id,
                request,
                owner_id=owner,
                idempotency_key=command.command_id,
            ),
            lambda result: self._public(owner).undo(result),
        )

    def _review_auto_park(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner, task_id = command.unit.owner_id, envelope["entity_id"]
        request = AutoParkRequest(**body)
        return self._run(
            command,
            lambda: _AUTO_PARK(
                self._review,
                task_id,
                request,
                owner_id=owner,
                idempotency_key=command.command_id,
                exposed=self._review.is_exposed(owner),
            ),
            lambda result: self._public(owner).auto_park(result),
        )

    # ------------------------------------------------- settings and activation
    def _review_explainer_ack(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner = self._owner_entity(command, envelope)
        request = ExplainerAcknowledgeRequest(**body)
        return self._run(
            command,
            lambda: _EXPLAINER(
                self._review,
                request,
                owner_id=owner,
                idempotency_key=command.command_id,
            ),
            _settings_result,
        )

    def _review_settings(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner = self._owner_entity(command, envelope)
        if "expected_revision" in body:
            raise _invalid()
        request = ReviewSettingsUpdateRequest(
            **body,
            expected_revision=self._expected(
                command, envelope, "review_settings", owner
            ),
        )
        return self._run(
            command,
            lambda: _SETTINGS(
                self._review,
                request,
                owner_id=owner,
                idempotency_key=command.command_id,
            ),
            _settings_result,
        )

    def _review_parks_ack(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner = self._owner_entity(command, envelope)
        request = ParkAcknowledgeRequest(**body)
        return self._run(
            command,
            lambda: _PARKS(
                self._review,
                request,
                owner_id=owner,
                idempotency_key=command.command_id,
            ),
            lambda _none: None,
        )

    # --------------------------------------------------------------- sessions
    def _review_session_start(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner = command.unit.owner_id
        if "id" in body:
            raise _invalid()
        request = SessionStartRequest(id=envelope["entity_id"], **body)
        return self._run(
            command,
            lambda: _START(
                self._flow, request, owner_id=owner, idempotency_key=command.command_id
            ),
            _session_result,
        )

    def _review_session_progress(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner, session_id = command.unit.owner_id, envelope["entity_id"]
        request = SessionProgressRequest(**body)
        return self._run(
            command,
            lambda: _PROGRESS(
                self._flow,
                session_id,
                request,
                owner_id=owner,
                idempotency_key=command.command_id,
            ),
            _session_result,
        )

    def _review_session_finish(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner, session_id = command.unit.owner_id, envelope["entity_id"]
        request = SessionFinishRequest(**body)
        return self._run(
            command,
            lambda: _FINISH(
                self._flow,
                session_id,
                request,
                owner_id=owner,
                idempotency_key=command.command_id,
            ),
            _session_result,
        )

    # ------------------------------------------------------------------ bulk
    def _review_bulk_release(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner = command.unit.owner_id
        if "id" in body:
            raise _invalid()
        request = BulkReleaseRequest(id=envelope["entity_id"], **body)
        return self._run(
            command,
            lambda: _RELEASE(
                self._flow, request, owner_id=owner, idempotency_key=command.command_id
            ),
            lambda release: public_value(encode_release(release)),
        )

    def _review_bulk_undo(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner, bulk_id = command.unit.owner_id, envelope["entity_id"]
        self._empty(body)
        return self._run(
            command,
            lambda: _RELEASE_UNDO(
                self._flow,
                bulk_id,
                owner_id=owner,
                idempotency_key=command.command_id,
            ),
            dict,
        )

    # ---------------------------------------------------------------- consent
    def _review_consent_grant(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        owner = self._owner_entity(command, envelope)
        request = NavigatorConsentGrantRequest(**body)
        if not self._review.is_exposed(owner):
            # The grant is exposure, like the web route's ``weekly_review`` gate.
            return command.reject(DomainRefusal("review_unavailable", None, None, None))
        return self._run(
            command,
            lambda: _GRANT(
                self._navigator,
                request,
                owner_id=owner,
                idempotency_key=command.command_id,
            ),
            _grant_result,
        )

    def _review_consent_revoke(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Json,
    ) -> Receipt:
        """Owner-wide, whatever provider the payload names, and never gated.

        A replay of this command_id is answered by its receipt before any code
        here runs, so a late retry never revokes a newer grant.
        """
        owner = self._owner_entity(command, envelope)
        if set(body) - {"provider"}:
            raise _invalid()
        return self._run(
            command,
            lambda: _REVOKE(
                self._navigator, owner_id=owner, idempotency_key=command.command_id
            ),
            lambda _none: None,
        )


# ------------------------------------------------------------------ results
def _settings_result(settings: ReviewSettingsDocument) -> Json:
    return public_value(encode_settings(settings))  # type: ignore[no-any-return]


def _session_result(session: ReviewSessionDocument) -> Json:
    return public_value(encode_session(session))  # type: ignore[no-any-return]


def _grant_result(status: NavigatorStatus) -> Json:
    """The status the web grant answers; the consent without its history."""
    return {
        "provider": status.provider,
        "consent": (
            None if status.consent is None else consent_value(status.consent)["consent"]
        ),
        "consent_current": status.consent_current,
        "consent_text_version": status.consent_text_version,
        "available": status.available,
    }


@register_family
def _review_family(container: Any, core: RustCore) -> DeviceCommandExecutor:
    tasks = container.task_service
    return ReviewDeviceExecutor(
        container.review_service,
        container.review_flow_service,
        container.navigator_service,
        tasks.task_repo,
        ReviewProjection(tasks.task_repo, core),
    )
