"""Behaviour of the external-agent relay service.

Every acceptance scenario in ``specs/006-external-agent-relay/spec.md`` that does
not need HTTP plumbing lives here, driven through a fake connector so no test
ever touches a network or a paid provider.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections import OrderedDict
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.modules.agents.connector import (
    ConnectorCommandOutcome,
    ConnectorStartOutcome,
    ConnectorTarget,
    ConnectorTestOutcome,
)
from app.modules.agents.domain import (
    PROTOCOL_VERSION,
    AgentCapabilities,
    AgentConnectionDocument,
)
from app.modules.agents.headers import RESERVED_AUTH_HEADER_NAMES
from app.modules.agents.repository import IDEMPOTENCY_RETENTION, AgentRepository
from app.modules.agents.secrets import SecretBox
from app.modules.agents.service import (
    AgentRelayService,
    EventRejected,
    RelayFingerprintUnreadable,
    RelayKeyRotationUnsafe,
    TaskSnapshot,
)
from app.schemas.agents import (
    AgentConnectionCreateRequest,
    AgentConnectionDisconnectRequest,
    AgentConnectionRotateRequest,
    AgentConnectionRotateSigningSecretRequest,
    AgentConnectionUpdateRequest,
    AgentContextItemRequest,
    AgentHandoffConfirmRequest,
    AgentHandoffPreviewRequest,
    AgentReplyRequest,
)

OWNER = "user_a"
OTHER_OWNER = "user_b"
CALLBACK = "https://brainbuddy.example/api/agent-events"


class FakeConnector:
    """A scriptable stand-in for a user's agent."""

    def __init__(self) -> None:
        self.test_outcome = ConnectorTestOutcome(
            "ready", AgentCapabilities(progress=True, reply=True, cancel=True)
        )
        self.start_outcome = ConnectorStartOutcome("sent")
        self.command_outcome = ConnectorCommandOutcome("confirmed")
        self.starts: list[dict[str, Any]] = []
        self.commands: list[dict[str, Any]] = []
        self.tests: list[ConnectorTarget] = []

    def test(self, target: ConnectorTarget) -> ConnectorTestOutcome:
        self.tests.append(target)
        return self.test_outcome

    def start(
        self, target: ConnectorTarget, *, envelope: dict[str, Any]
    ) -> ConnectorStartOutcome:
        self.starts.append(envelope)
        return self.start_outcome

    def command(
        self, target: ConnectorTarget, *, envelope: dict[str, Any]
    ) -> ConnectorCommandOutcome:
        self.commands.append(envelope)
        return self.command_outcome


class BlockingTestConnector(FakeConnector):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def test(self, target: ConnectorTarget) -> ConnectorTestOutcome:
        self.tests.append(target)
        self.entered.set()
        assert self.release.wait(timeout=5)
        return self.test_outcome


class BlockingIoConnector(FakeConnector):
    def __init__(self) -> None:
        super().__init__()
        self.block_kind: str | None = None
        self.entered = Event()
        self.release = Event()

    def _block(self, kind: str) -> None:
        if self.block_kind == kind:
            self.entered.set()
            assert self.release.wait(timeout=5)

    def start(
        self, target: ConnectorTarget, *, envelope: dict[str, Any]
    ) -> ConnectorStartOutcome:
        self.starts.append(envelope)
        self._block("start")
        return self.start_outcome

    def command(
        self, target: ConnectorTarget, *, envelope: dict[str, Any]
    ) -> ConnectorCommandOutcome:
        self.commands.append(envelope)
        self._block(str(envelope["type"]))
        return self.command_outcome


class Clock:
    """A controllable clock so retention and silence are testable."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


TASKS = {
    "task_1": TaskSnapshot(
        id="task_1",
        title="Draft the migration plan",
        details="Cover rollback and the data backfill.",
    ),
    "task_2": TaskSnapshot(id="task_2", title="Second task", details=None),
}


def task_snapshot(task_id: str, *, owner_id: str) -> TaskSnapshot:
    if owner_id != OWNER or task_id not in TASKS:
        raise NotFoundError("Task", task_id)
    return TASKS[task_id]


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 8, 9, 12, 0, tzinfo=UTC))


@pytest.fixture
def connector() -> FakeConnector:
    return FakeConnector()


def fake_resolver(host: str, port: int) -> list[str]:
    """Resolve the suite's example hosts without touching real DNS."""

    return {
        "agent.example.com": ["93.184.216.34"],
        "second.example.com": ["93.184.216.35"],
    }[host]


def build_service(
    repo: AgentRepository,
    connector: FakeConnector,
    clock: Clock,
    *,
    key: bytes = b"\x07" * 32,
    keys: OrderedDict[str, bytes] | None = None,
) -> AgentRelayService:
    return AgentRelayService(
        repo,
        connector=connector,
        secret_box=SecretBox(keys if keys is not None else OrderedDict({"v1": key})),
        task_snapshot=task_snapshot,
        callback_url=CALLBACK,
        resolver=fake_resolver,
        now=clock,
    )


@pytest.fixture
def service(
    tmp_path: Path, connector: FakeConnector, clock: Clock
) -> AgentRelayService:
    return build_service(AgentRepository(tmp_path), connector, clock)


def create_request(**overrides: Any) -> AgentConnectionCreateRequest:
    payload: dict[str, Any] = {
        "name": "Hermes",
        "endpoint_url": "https://agent.example.com/hooks",
        "credential": "Bearer super-secret-token",
        "current_password": "correct-horse-battery-staple",
    }
    payload.update(overrides)
    return AgentConnectionCreateRequest.model_validate(payload)


def connect(service: AgentRelayService, key: str = "idem-create") -> str:
    created = service.create_connection(
        create_request(), owner_id=OWNER, idempotency_key=key, reauthenticated=True
    )
    return created.id


def make_ready(service: AgentRelayService, connection_id: str) -> None:
    service.test_connection(connection_id, owner_id=OWNER)


def review(
    service: AgentRelayService,
    connection_id: str,
    *,
    task_id: str = "task_1",
    context: list[AgentContextItemRequest] | None = None,
) -> AgentHandoffConfirmRequest:
    """Run the review and return the exact confirmation it authorises."""

    preview = service.preview_handoff(
        task_id,
        AgentHandoffPreviewRequest(
            connection_id=connection_id, context_items=context or []
        ),
        owner_id=OWNER,
    )
    return AgentHandoffConfirmRequest(
        connection_id=connection_id,
        context_items=context or [],
        manifest_token=preview.token,
    )


def dispatch(
    service: AgentRelayService,
    connection_id: str,
    *,
    task_id: str = "task_1",
    key: str = "idem-dispatch",
    context: list[AgentContextItemRequest] | None = None,
) -> Any:
    return service.dispatch_run(
        task_id,
        review(service, connection_id, task_id=task_id, context=context),
        owner_id=OWNER,
        idempotency_key=key,
    )


# --- User Story 1: connect an agent honestly ---------------------------------


class TestConnectAnAgent:
    def test_connection_document_defensively_rejects_a_blank_name(
        self, clock: Clock
    ) -> None:
        with pytest.raises(PydanticValidationError):
            AgentConnectionDocument(
                id="agentconn_blank",
                owner_id=OWNER,
                name="   ",
                endpoint_url="https://agent.example.com/hooks",
                created_at=clock.now,
                updated_at=clock.now,
            )

    @pytest.mark.parametrize(
        "auth_header_name",
        [*sorted(RESERVED_AUTH_HEADER_NAMES), "aUtHoRiZaTiOn", "X Bad"],
    )
    def test_connection_document_defensively_rejects_unsafe_auth_headers(
        self, clock: Clock, auth_header_name: str
    ) -> None:
        with pytest.raises(PydanticValidationError):
            AgentConnectionDocument(
                id="agentconn_bad_header",
                owner_id=OWNER,
                name="Hermes",
                endpoint_url="https://agent.example.com/hooks",
                auth_header_name=auth_header_name,
                created_at=clock.now,
                updated_at=clock.now,
            )

    def test_a_saved_connection_starts_untested_and_hides_its_secret(
        self, service: AgentRelayService
    ) -> None:
        """AC-001: a new connection is saved but not yet claimed to work."""

        created = service.create_connection(
            create_request(),
            owner_id=OWNER,
            idempotency_key="idem-1",
            reauthenticated=True,
        )

        assert created.status == "untested"
        assert created.ready_for_handoff is False
        assert "credential" not in created.model_dump()
        assert "super-secret-token" not in json.dumps(created.model_dump(mode="json"))

    def test_the_inbound_signing_secret_is_returned_exactly_once(
        self, service: AgentRelayService
    ) -> None:
        """The owner needs it to configure their agent; we never show it again."""

        created = service.create_connection(
            create_request(),
            owner_id=OWNER,
            idempotency_key="idem-1",
            reauthenticated=True,
        )

        assert len(created.inbound_signing_secret) >= 32
        fetched = service.get_connection(created.id, owner_id=OWNER)
        assert not hasattr(fetched, "inbound_signing_secret")
        assert created.inbound_signing_secret not in json.dumps(
            fetched.model_dump(mode="json")
        )

    def test_creating_a_connection_requires_reauthentication(
        self, service: AgentRelayService
    ) -> None:
        """FR-003: registering a destination is a re-authenticated action."""

        with pytest.raises(ValidationFailure):
            service.create_connection(
                create_request(),
                owner_id=OWNER,
                idempotency_key="idem-1",
                reauthenticated=False,
            )

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://127.0.0.1/hooks",
            "https://169.254.169.254/latest",
            "https://10.0.0.5/hooks",
            "http://agent.example.com/hooks",
        ],
    )
    def test_an_unsafe_destination_is_refused_before_saving(
        self, service: AgentRelayService, endpoint: str
    ) -> None:
        """AC-005: unsafe network classes never become a saved connection."""

        with pytest.raises(ValidationFailure):
            service.create_connection(
                create_request(endpoint_url=endpoint),
                owner_id=OWNER,
                idempotency_key="idem-1",
                reauthenticated=True,
            )

        assert service.list_connections(owner_id=OWNER) == []

    def test_replaying_the_creation_key_returns_the_same_connection(
        self, service: AgentRelayService
    ) -> None:
        """A retried create must not mint a second connection."""

        first = service.create_connection(
            create_request(),
            owner_id=OWNER,
            idempotency_key="idem-1",
            reauthenticated=True,
        )
        second = service.create_connection(
            create_request(),
            owner_id=OWNER,
            idempotency_key="idem-1",
            reauthenticated=True,
        )

        assert first.id == second.id
        assert len(service.list_connections(owner_id=OWNER)) == 1

    def test_a_successful_test_reports_ready_with_capabilities_and_contact(
        self, service: AgentRelayService, connector: FakeConnector, clock: Clock
    ) -> None:
        """AC-001: after a good test the user sees what the agent can do."""

        connection_id = connect(service)

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "ready"
        assert tested.ready_for_handoff is True
        assert tested.capabilities.reply is True
        assert tested.last_contact_at == clock.now
        assert connector.tests[0].credential == "Bearer super-secret-token"

    def test_invalid_credentials_are_reported_without_echoing_the_secret(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """AC-002: an auth rejection is actionable and leaks nothing."""

        connection_id = connect(service)
        connector.test_outcome = ConnectorTestOutcome(
            "invalid_credentials",
            AgentCapabilities(),
            error_code="connector_credentials_rejected",
        )

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "invalid_credentials"
        assert tested.ready_for_handoff is False
        assert tested.last_contact_at is None
        assert "super-secret-token" not in json.dumps(tested.model_dump(mode="json"))

    def test_unreachable_is_distinguished_from_invalid_credentials(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """AC-003: the user can tell 'wrong key' from 'nothing answered'."""

        connection_id = connect(service)
        connector.test_outcome = ConnectorTestOutcome(
            "unreachable", AgentCapabilities(), error_code="connector_unreachable"
        )

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "unreachable"
        assert tested.last_test_error_code == "connector_unreachable"

    def test_a_connector_without_start_idempotency_is_never_ready(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """FR-006: no dedup guarantee means no hand-off."""

        connection_id = connect(service)
        connector.test_outcome = ConnectorTestOutcome(
            "unsupported",
            AgentCapabilities(progress=True),
            error_code="connector_start_not_idempotent",
        )

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "unsupported"
        assert tested.ready_for_handoff is False

    def test_a_ready_connection_goes_stale_once_contact_ages_out(
        self, service: AgentRelayService, clock: Clock
    ) -> None:
        """AC-004: staleness is derived from the clock, not a stored flag."""

        connection_id = connect(service)
        make_ready(service, connection_id)

        assert service.get_connection(connection_id, owner_id=OWNER).stale is False

        clock.advance(service.stale_after + timedelta(seconds=1))
        stale = service.get_connection(connection_id, owner_id=OWNER)

        assert stale.stale is True
        assert stale.ready_for_handoff is False
        assert stale.last_contact_at is not None

    def test_another_owner_cannot_see_or_test_the_connection(
        self, service: AgentRelayService
    ) -> None:
        """Owner isolation holds at the service boundary."""

        connection_id = connect(service)

        assert service.list_connections(owner_id=OTHER_OWNER) == []
        with pytest.raises(NotFoundError):
            service.get_connection(connection_id, owner_id=OTHER_OWNER)
        with pytest.raises(NotFoundError):
            service.test_connection(connection_id, owner_id=OTHER_OWNER)

    def test_rotating_the_credential_requires_reauthentication_and_resets_readiness(
        self, service: AgentRelayService
    ) -> None:
        """A new secret is a new scope: it must be re-tested before use."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        current = service.get_connection(connection_id, owner_id=OWNER)

        rotated = service.rotate_credential(
            connection_id,
            AgentConnectionRotateRequest(
                credential="Bearer rotated-token",
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-rotate",
            reauthenticated=True,
        )

        assert rotated.status == "untested"
        assert rotated.ready_for_handoff is False

    def test_rotation_with_a_stale_revision_conflicts(
        self, service: AgentRelayService
    ) -> None:
        """Concurrent edits are refused rather than silently merged."""

        connection_id = connect(service)

        with pytest.raises(ConflictError):
            service.rotate_credential(
                connection_id,
                AgentConnectionRotateRequest(
                    credential="Bearer rotated-token",
                    current_password="correct-horse-battery-staple",
                    expected_revision=99,
                ),
                owner_id=OWNER,
                idempotency_key="idem-rotate",
                reauthenticated=True,
            )

    def test_name_only_update_preserves_readiness_without_reauthentication(
        self, service: AgentRelayService
    ) -> None:
        connection_id = connect(service)
        make_ready(service, connection_id)
        current = service.get_connection(connection_id, owner_id=OWNER)

        updated = service.update_connection(
            connection_id,
            AgentConnectionUpdateRequest(
                name="Renamed agent", expected_revision=current.revision
            ),
            owner_id=OWNER,
            idempotency_key="idem-rename",
            reauthenticated=False,
        )

        assert updated.name == "Renamed agent"
        assert updated.endpoint_url == current.endpoint_url
        assert updated.status == "ready"
        assert updated.capabilities == current.capabilities
        assert updated.last_tested_at == current.last_tested_at
        assert updated.revision == current.revision + 1

    def test_update_with_identical_values_is_a_true_no_op(
        self, service: AgentRelayService, clock: Clock
    ) -> None:
        connection_id = connect(service)
        current = service.get_connection(connection_id, owner_id=OWNER)
        request = AgentConnectionUpdateRequest(
            name=current.name,
            endpoint_url=current.endpoint_url,
            expected_revision=current.revision,
        )
        stored_before = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        audit_before = service.list_audit(owner_id=OWNER)

        clock.advance(timedelta(hours=1))
        first = service.update_connection(
            connection_id,
            request,
            owner_id=OWNER,
            idempotency_key="idem-no-op",
            reauthenticated=False,
        )
        replay = service.update_connection(
            connection_id,
            request,
            owner_id=OWNER,
            idempotency_key="idem-no-op",
            reauthenticated=False,
        )

        assert first == replay == current
        assert first.revision == current.revision
        assert (
            service.agent_repo.get_connection(connection_id, owner_id=OWNER).updated_at
            == stored_before.updated_at
        )
        assert service.list_audit(owner_id=OWNER) == audit_before
        with pytest.raises(ConflictError):
            service.update_connection(
                connection_id,
                AgentConnectionUpdateRequest(
                    name="Different", expected_revision=current.revision
                ),
                owner_id=OWNER,
                idempotency_key="idem-no-op",
                reauthenticated=False,
            )

    def test_destination_update_requires_reauthentication_and_resets_destination_state(
        self, service: AgentRelayService
    ) -> None:
        connection_id = connect(service)
        make_ready(service, connection_id)
        current = service.get_connection(connection_id, owner_id=OWNER)
        request = AgentConnectionUpdateRequest(
            endpoint_url="https://second.example.com/hooks",
            expected_revision=current.revision,
        )

        with pytest.raises(ValidationFailure) as refused:
            service.update_connection(
                connection_id,
                request,
                owner_id=OWNER,
                idempotency_key="idem-move-refused",
                reauthenticated=False,
            )
        updated = service.update_connection(
            connection_id,
            request,
            owner_id=OWNER,
            idempotency_key="idem-move",
            reauthenticated=True,
        )

        assert refused.value.detail == {"reason": "reauthentication_required"}
        assert updated.endpoint_url == "https://second.example.com/hooks"
        assert updated.status == "untested"
        assert updated.capabilities.model_dump() == AgentCapabilities().model_dump()
        assert updated.last_contact_at is None
        assert updated.last_tested_at is None
        assert updated.revision == current.revision + 1

    def test_update_is_owner_scoped_revisioned_and_idempotent(
        self, service: AgentRelayService
    ) -> None:
        connection_id = connect(service)
        current = service.get_connection(connection_id, owner_id=OWNER)
        request = AgentConnectionUpdateRequest(
            name="Renamed agent", expected_revision=current.revision
        )
        first = service.update_connection(
            connection_id,
            request,
            owner_id=OWNER,
            idempotency_key="idem-update",
            reauthenticated=False,
        )
        latest = service.update_connection(
            connection_id,
            AgentConnectionUpdateRequest(
                name="Latest name", expected_revision=first.revision
            ),
            owner_id=OWNER,
            idempotency_key="idem-update-latest",
            reauthenticated=False,
        )
        replay = service.update_connection(
            connection_id,
            request,
            owner_id=OWNER,
            idempotency_key="idem-update",
            reauthenticated=False,
        )

        assert replay == first
        assert replay != latest
        with pytest.raises(ConflictError):
            service.update_connection(
                connection_id,
                AgentConnectionUpdateRequest(
                    name="Different", expected_revision=current.revision
                ),
                owner_id=OWNER,
                idempotency_key="idem-update",
                reauthenticated=False,
            )
        with pytest.raises(NotFoundError):
            service.update_connection(
                connection_id,
                request,
                owner_id=OTHER_OWNER,
                idempotency_key="idem-other",
                reauthenticated=False,
            )
        with pytest.raises(ConflictError):
            service.update_connection(
                connection_id,
                AgentConnectionUpdateRequest(
                    name="Stale", expected_revision=current.revision
                ),
                owner_id=OWNER,
                idempotency_key="idem-stale",
                reauthenticated=False,
            )


class TestConnectionTestConcurrency:
    def test_slow_test_cannot_restore_readiness_after_destination_update(
        self, tmp_path: Path, clock: Clock
    ) -> None:
        connector = BlockingTestConnector()
        service = build_service(AgentRepository(tmp_path), FakeConnector(), clock)
        connection_id = connect(service)
        make_ready(service, connection_id)
        service.connector = connector
        tested: list[Any] = []
        worker = Thread(
            target=lambda: tested.append(
                service.test_connection(connection_id, owner_id=OWNER)
            )
        )
        worker.start()
        assert connector.entered.wait(timeout=5)

        current = service.get_connection(connection_id, owner_id=OWNER)
        moved = service.update_connection(
            connection_id,
            AgentConnectionUpdateRequest(
                endpoint_url="https://second.example.com/hooks",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-race-move",
            reauthenticated=True,
        )
        connector.release.set()
        worker.join(timeout=5)

        assert moved.status == "untested"
        assert tested[0].status == "untested"
        assert (
            service.get_connection(connection_id, owner_id=OWNER).status == "untested"
        )

    def test_a_slow_test_cannot_restore_a_concurrently_disconnected_connection(
        self, tmp_path: Path, clock: Clock
    ) -> None:
        connector = BlockingTestConnector()
        service = build_service(AgentRepository(tmp_path), connector, clock)
        connection_id = connect(service)
        tested: list[Any] = []
        worker = Thread(
            target=lambda: tested.append(
                service.test_connection(connection_id, owner_id=OWNER)
            )
        )
        worker.start()
        assert connector.entered.wait(timeout=5)

        current = service.get_connection(connection_id, owner_id=OWNER)
        service.disconnect_connection(
            connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-disconnect-race",
            reauthenticated=True,
        )
        connector.release.set()
        worker.join(timeout=5)

        persisted = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert persisted.status == "disconnected"
        assert persisted.credential is None
        assert persisted.inbound_secret is None
        assert persisted.disconnected_at is not None
        assert tested and tested[0].status == "disconnected"

    def test_a_slow_test_cannot_restore_a_concurrently_rotated_credential(
        self, tmp_path: Path, clock: Clock
    ) -> None:
        connector = BlockingTestConnector()
        service = build_service(AgentRepository(tmp_path), connector, clock)
        connection_id = connect(service)
        tested: list[Any] = []
        worker = Thread(
            target=lambda: tested.append(
                service.test_connection(connection_id, owner_id=OWNER)
            )
        )
        worker.start()
        assert connector.entered.wait(timeout=5)

        current = service.get_connection(connection_id, owner_id=OWNER)
        service.rotate_credential(
            connection_id,
            AgentConnectionRotateRequest(
                credential="Bearer rotated-token",
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-rotate-race",
            reauthenticated=True,
        )
        connector.release.set()
        worker.join(timeout=5)

        persisted = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert persisted.status == "untested"
        assert service._target(persisted).credential == "Bearer rotated-token"
        assert persisted.last_tested_at is None
        assert tested and tested[0].status == "untested"


class TestExternalIoLockScope:
    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    def test_slow_external_io_releases_global_and_sqlite_writer_locks(
        self, tmp_path: Path, clock: Clock, operation: str
    ) -> None:
        connector = BlockingIoConnector()
        repo = AgentRepository(tmp_path)
        service = build_service(repo, connector, clock)
        connection_id = connect(service)
        make_ready(service, connection_id)

        if operation == "start":
            confirmation = review(service, connection_id)

            def invoke() -> None:
                service.dispatch_run(
                    "task_1",
                    confirmation,
                    owner_id=OWNER,
                    idempotency_key="idem-slow-start",
                )

        else:
            run = dispatch(service, connection_id)
            if operation == "reply":
                payload = AgentReplyRequest(
                    message="Use staging.",
                    expected_revision=service.get_run(run.id, owner_id=OWNER).revision,
                )

                def invoke() -> None:
                    service.reply_to_run(
                        run.id,
                        payload,
                        owner_id=OWNER,
                        idempotency_key="idem-slow-reply",
                    )

            else:

                def invoke() -> None:
                    service.cancel_run(
                        run.id,
                        owner_id=OWNER,
                        idempotency_key="idem-slow-cancel",
                    )

        connector.block_kind = operation
        worker_errors: list[BaseException] = []

        def run_worker() -> None:
            try:
                invoke()
            except BaseException as exc:  # pragma: no cover - asserted below
                worker_errors.append(exc)

        worker = Thread(target=run_worker)
        worker.start()
        assert connector.entered.wait(timeout=5)

        unrelated_finished = Event()
        maintenance_finished = Event()

        def unrelated_command() -> None:
            with repo.command_lock(OTHER_OWNER):
                unrelated_finished.set()

        def maintenance_write() -> None:
            repo.purge_expired_audit(now=clock.now)
            maintenance_finished.set()

        unrelated = Thread(target=unrelated_command)
        maintenance = Thread(target=maintenance_write)
        unrelated.start()
        maintenance.start()
        unrelated_during_io = unrelated_finished.wait(timeout=0.5)
        maintenance_during_io = maintenance_finished.wait(timeout=0.5)
        connector.release.set()
        worker.join(timeout=5)
        unrelated.join(timeout=5)
        maintenance.join(timeout=5)

        assert unrelated_during_io is True
        assert maintenance_during_io is True
        assert worker_errors == []

    @pytest.mark.parametrize(
        "transport_status", ["sent", "not_sent", "delivery_unconfirmed"]
    )
    @pytest.mark.parametrize(
        ("callback_type", "callback_fields", "expire_content"),
        [
            ("accepted", {}, True),
            ("completed", {"result": "Finished during dispatch"}, False),
        ],
    )
    def test_authenticated_callback_during_start_owns_state_and_transport_merge_is_monotonic(
        self,
        tmp_path: Path,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
        transport_status: Any,
        callback_type: str,
        callback_fields: dict[str, str],
        expire_content: bool,
    ) -> None:
        connector = FakeConnector()
        service = build_service(AgentRepository(tmp_path), connector, clock)
        created = service.create_connection(
            create_request(),
            owner_id=OWNER,
            idempotency_key="idem-callback-create",
            reauthenticated=True,
        )
        make_ready(service, created.id)
        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=created.id),
            owner_id=OWNER,
        )
        confirmation = AgentHandoffConfirmRequest(
            connection_id=created.id,
            manifest_token=preview.token,
        )
        before_io = clock.now

        def start_with_callback(
            target: ConnectorTarget, *, envelope: dict[str, Any]
        ) -> ConnectorStartOutcome:
            connector.starts.append(envelope)
            clock.advance(timedelta(minutes=2))
            event = {
                "protocol_version": PROTOCOL_VERSION,
                "connection_id": created.id,
                "event_id": f"evt_sync_{callback_type}",
                "run_id": preview.run_id,
                "type": callback_type,
                "run_version": 1,
                **callback_fields,
            }
            body = json.dumps(event).encode("utf-8")
            timestamp = int(clock.now.timestamp())
            accepted = service.ingest_event(
                raw_body=body,
                connection_id=created.id,
                timestamp=str(timestamp),
                signature=sign(created.inbound_signing_secret, timestamp, body),
            )
            assert accepted.accepted is True
            if expire_content:
                persisted = service.agent_repo.get_run(preview.run_id, owner_id=OWNER)
                clock.now = persisted.content_expires_at
                service.agent_repo.expire_due_content(now=clock.now)
            clock.advance(timedelta(seconds=1))
            return ConnectorStartOutcome(transport_status, "stale_transport_error")

        monkeypatch.setattr(connector, "start", start_with_callback)

        run = service.dispatch_run(
            "task_1",
            confirmation,
            owner_id=OWNER,
            idempotency_key=f"idem-sync-start-{callback_type}-{transport_status}",
        )

        assert run.dispatch_state == "sent"
        assert run.dispatch_error_code is None
        assert run.reported_state == callback_type
        assert run.run_version == 1
        assert run.result_text == callback_fields.get("result")
        assert run.content_expired is expire_content
        persisted = service.agent_repo.get_run(run.id, owner_id=OWNER)
        assert persisted.updated_at == clock.now
        assert persisted.updated_at > before_io
        assert len(connector.starts) == 1

    @pytest.mark.parametrize("bypass_operation_lock", [False, True])
    def test_concurrent_same_key_dispatches_contend_and_converge_only_with_lock(
        self,
        tmp_path: Path,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
        bypass_operation_lock: bool,
    ) -> None:
        connector = BlockingIoConnector()
        repo = AgentRepository(tmp_path)
        service = build_service(repo, connector, clock)
        connection_id = connect(service)
        make_ready(service, connection_id)
        confirmation = review(service, connection_id)
        connector.block_kind = "start"
        results: list[Any] = []
        errors: list[BaseException] = []
        attempts: list[tuple[str, str]] = []
        second_attempted = Event()
        second_acquired = Event()
        second_finished = Event()
        operation_lock = repo.operation_lock
        expected_fingerprint = service._key_fingerprint(OWNER, "idem-concurrent-start")

        @contextmanager
        def observed_operation_lock(owner_id: str, operation_fingerprint: str) -> Any:
            attempts.append((owner_id, operation_fingerprint))
            attempt_number = len(attempts)
            if attempt_number == 2:
                second_attempted.set()
            if bypass_operation_lock:
                if attempt_number == 2:
                    second_acquired.set()
                yield
                return
            with operation_lock(owner_id, operation_fingerprint):
                if attempt_number == 2:
                    second_acquired.set()
                yield

        monkeypatch.setattr(repo, "operation_lock", observed_operation_lock)

        def invoke(*, second: bool = False) -> None:
            try:
                results.append(
                    service.dispatch_run(
                        "task_1",
                        confirmation,
                        owner_id=OWNER,
                        idempotency_key="idem-concurrent-start",
                    )
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)
            finally:
                if second:
                    second_finished.set()

        first = Thread(target=invoke)
        second = Thread(target=lambda: invoke(second=True))
        first.start()
        assert connector.entered.wait(timeout=5)
        second.start()
        assert second_attempted.wait(timeout=5)
        assert attempts == [
            (OWNER, expected_fingerprint),
            (OWNER, expected_fingerprint),
        ]
        if bypass_operation_lock:
            assert second_acquired.wait(timeout=5)
            assert second_finished.wait(timeout=5)
        else:
            assert second_acquired.is_set() is False
            assert second_finished.is_set() is False
        connector.release.set()
        first.join(timeout=5)
        second.join(timeout=5)

        assert errors == []
        assert len(connector.starts) == 1
        assert len(results) == 2
        assert results[0].id == results[1].id
        if bypass_operation_lock:
            assert results[0].model_dump() != results[1].model_dump()
        else:
            assert second_acquired.is_set() is True
            assert results[0].model_dump() == results[1].model_dump()


# --- User Story 2: review and hand one task to the agent ---------------------


class TestHandOffReview:
    def test_the_preview_lists_every_field_that_will_be_sent(
        self, service: AgentRelayService
    ) -> None:
        """AC-006: nothing leaves BrainBuddy that the review did not show."""

        connection_id = connect(service)
        make_ready(service, connection_id)

        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(
                connection_id=connection_id,
                context_items=[
                    AgentContextItemRequest(label="Runbook", body="Step one...")
                ],
            ),
            owner_id=OWNER,
        )

        assert preview.title == "Draft the migration plan"
        assert preview.details == "Cover rollback and the data backfill."
        assert [item.label for item in preview.context_items] == ["Runbook"]
        assert preview.task_id == "task_1"
        assert preview.run_id
        assert preview.agent_name == "Hermes"
        assert preview.reporting_instructions
        assert preview.destination_endpoint == "https://agent.example.com/hooks"
        assert "cannot guarantee" in preview.external_copy_notice

    def test_excluding_details_removes_them_from_the_manifest_and_the_token(
        self, service: AgentRelayService
    ) -> None:
        """AC-007: what the user removed is not sent, and re-review is forced."""

        connection_id = connect(service)
        make_ready(service, connection_id)

        with_details = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )
        without_details = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(
                connection_id=connection_id, include_details=False
            ),
            owner_id=OWNER,
        )

        assert without_details.details is None
        assert without_details.token != with_details.token

    def test_confirming_a_token_that_no_longer_matches_is_refused(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """FR-005: a changed payload invalidates the confirmation."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )

        with pytest.raises(ValidationFailure):
            service.dispatch_run(
                "task_1",
                AgentHandoffConfirmRequest(
                    connection_id=connection_id,
                    context_items=[
                        AgentContextItemRequest(label="Sneaky", body="added later")
                    ],
                    manifest_token=preview.token,
                ),
                owner_id=OWNER,
                idempotency_key="idem-dispatch",
            )

        assert connector.starts == []

    def test_cancelling_the_review_creates_no_run(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """AC-007: a preview alone never becomes an external run."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )

        assert service.list_runs_for_task("task_1", owner_id=OWNER) == []
        assert connector.starts == []

    def test_one_confirmation_produces_exactly_one_run_and_one_start(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """AC-008: dispatch is Sent, linked to the Task, and singular."""

        connection_id = connect(service)
        make_ready(service, connection_id)

        run = dispatch(service, connection_id)

        assert run.dispatch_state == "sent"
        assert run.task_id == "task_1"
        assert run.reported_state is None
        assert run.primary_state_label == "Sent"
        assert len(connector.starts) == 1
        assert len(service.list_runs_for_task("task_1", owner_id=OWNER)) == 1

    def test_the_start_envelope_carries_the_correlated_identifiers(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """FR-006: start(prompt, task_id, run_id, idempotency_key)."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        run = dispatch(service, connection_id)

        envelope = connector.starts[0]
        assert envelope["run_id"] == run.id
        assert envelope["task_id"] == "task_1"
        assert envelope["idempotency_key"]
        assert envelope["title"] == "Draft the migration plan"
        reporting = envelope["reporting"]
        assert reporting == {
            "callback_url": CALLBACK,
            "connection_id": connection_id,
            "connection_header": "X-BrainBuddy-Connection",
            "timestamp_header": "X-BrainBuddy-Timestamp",
            "signature_header": "X-BrainBuddy-Signature",
            "timestamp_format": "ascii-base-10-unix-seconds-no-sign-space-or-leading-zero",
            "signature_algorithm": "hmac-sha256",
            "signing_bytes": "timestamp_bytes + b'.' + raw_body",
            "signature_format": "v1=<lowercase hex>",
            "body_envelope_version": PROTOCOL_VERSION,
            "instructions": reporting["instructions"],
            "instructions_version": "v2",
        }
        assert "super-secret-token" not in json.dumps(reporting)

    @pytest.mark.parametrize("replays", [1, 2, 3])
    def test_replaying_the_dispatch_returns_the_same_run_without_restarting(
        self, service: AgentRelayService, connector: FakeConnector, replays: int
    ) -> None:
        """AC-009 / SC-001: identical replays never start a second external run."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        confirmation = review(service, connection_id)
        first = service.dispatch_run(
            "task_1", confirmation, owner_id=OWNER, idempotency_key="idem-dispatch"
        )

        for _ in range(replays):
            repeat = service.dispatch_run(
                "task_1", confirmation, owner_id=OWNER, idempotency_key="idem-dispatch"
            )
            assert repeat.id == first.id
            assert repeat.dispatch_state == first.dispatch_state

        assert len(connector.starts) == 1
        assert len(service.list_runs_for_task("task_1", owner_id=OWNER)) == 1

    def test_reusing_a_key_for_a_different_confirmation_is_a_conflict(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """A key is bound to one request; reuse for another is refused."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        service.dispatch_run(
            "task_1",
            review(service, connection_id),
            owner_id=OWNER,
            idempotency_key="idem-dispatch",
        )

        with pytest.raises(ConflictError):
            service.dispatch_run(
                "task_1",
                review(service, connection_id),
                owner_id=OWNER,
                idempotency_key="idem-dispatch",
            )

        assert len(connector.starts) == 1

    @pytest.mark.parametrize(
        "outcome,expected",
        [
            (ConnectorStartOutcome("delivery_unconfirmed"), "delivery_unconfirmed"),
            (ConnectorStartOutcome("not_sent", "connector_http_400"), "not_sent"),
        ],
    )
    def test_dispatch_reports_its_own_delivery_honestly(
        self,
        service: AgentRelayService,
        connector: FakeConnector,
        outcome: ConnectorStartOutcome,
        expected: str,
    ) -> None:
        """FR-006: ambiguous loss is never called failure, and vice versa."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        connector.start_outcome = outcome

        run = dispatch(service, connection_id)

        assert run.dispatch_state == expected
        assert run.reported_state is None

    def test_an_unconfirmed_delivery_keeps_its_run_and_is_never_auto_retried(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """FR-006: a retry reuses the original run and key, never a new one."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        connector.start_outcome = ConnectorStartOutcome("delivery_unconfirmed")
        confirmation = review(service, connection_id)
        first = service.dispatch_run(
            "task_1", confirmation, owner_id=OWNER, idempotency_key="idem-dispatch"
        )

        repeat = service.dispatch_run(
            "task_1", confirmation, owner_id=OWNER, idempotency_key="idem-dispatch"
        )

        assert repeat.id == first.id
        assert repeat.dispatch_state == "delivery_unconfirmed"
        assert len(connector.starts) == 1

    @pytest.mark.parametrize(
        "status,error",
        [
            ("untested", None),
            ("invalid_credentials", "connector_credentials_rejected"),
            ("unreachable", "connector_unreachable"),
        ],
    )
    def test_a_connection_that_is_not_ready_refuses_before_sending_content(
        self,
        service: AgentRelayService,
        connector: FakeConnector,
        status: str,
        error: str | None,
    ) -> None:
        """AC-010: task content never leaves through an unusable connection."""

        connection_id = connect(service)
        if status != "untested":
            connector.test_outcome = ConnectorTestOutcome(
                status,  # type: ignore[arg-type]
                AgentCapabilities(),
                error_code=error,
            )
            service.test_connection(connection_id, owner_id=OWNER)

        with pytest.raises(ValidationFailure):
            dispatch(service, connection_id)

        assert connector.starts == []

    def test_a_stale_connection_refuses_the_hand_off(
        self, service: AgentRelayService, connector: FakeConnector, clock: Clock
    ) -> None:
        """AC-010: silence past the stale threshold blocks a new hand-off."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        clock.advance(service.stale_after + timedelta(seconds=1))

        with pytest.raises(ValidationFailure):
            dispatch(service, connection_id)

        assert connector.starts == []

    def test_another_owners_connection_cannot_be_used(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """AC-010: cross-owner hand-off fails closed."""

        connection_id = connect(service)
        make_ready(service, connection_id)

        with pytest.raises(NotFoundError):
            service.preview_handoff(
                "task_1",
                AgentHandoffPreviewRequest(connection_id=connection_id),
                owner_id=OTHER_OWNER,
            )
        assert connector.starts == []

    def test_a_later_hand_off_creates_a_distinct_run(
        self, service: AgentRelayService
    ) -> None:
        """Editing the Task later never rewrites the frozen sent content."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        first = dispatch(service, connection_id, key="idem-a")

        second = dispatch(service, connection_id, key="idem-b")

        assert second.id != first.id
        assert len(service.list_runs_for_task("task_1", owner_id=OWNER)) == 2

    def test_the_frozen_manifest_is_kept_on_the_run(
        self, service: AgentRelayService
    ) -> None:
        """The run records exactly what was sent, for later inspection."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        run = dispatch(service, connection_id)

        assert run.manifest is not None
        assert run.manifest.title == "Draft the migration plan"


# --- User Story 3: monitor and respond without false claims ------------------


def sign(secret: str, timestamp: int, body: bytes) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"v1={digest}"


REQUIRED_EVENT_CONTENT: dict[str, dict[str, Any]] = {
    "blocked": {"question": "Which environment?"},
    "completed": {"result": "Done."},
    "failed": {"reason": "Out of credit"},
}
"""The payload each terminal-or-blocking type must carry to be well formed."""


class Relay:
    """Bundle a ready connection, a dispatched run, and its signing secret."""

    def __init__(self, service: AgentRelayService, clock: Clock) -> None:
        created = service.create_connection(
            create_request(),
            owner_id=OWNER,
            idempotency_key="idem-create",
            reauthenticated=True,
        )
        self.connection_id = created.id
        self.secret = created.inbound_signing_secret
        service.test_connection(self.connection_id, owner_id=OWNER)
        self.run = dispatch(service, self.connection_id)
        self.service = service
        self.clock = clock

    def emit(self, payload: dict[str, Any], *, secret: str | None = None) -> Any:
        body = json.dumps(payload).encode("utf-8")
        timestamp = int(self.clock.now.timestamp())
        return self.service.ingest_event(
            raw_body=body,
            connection_id=self.connection_id,
            timestamp=str(timestamp),
            signature=sign(secret or self.secret, timestamp, body),
        )

    def event(
        self, event_id: str, event_type: str, version: int, **extra: Any
    ) -> dict[str, Any]:
        """A realistic, fully-formed envelope for this connection's run.

        Every field the strict contract requires is present, including the
        ``connection_id`` the signature binds, so a test that wants a rejection
        has to say which single thing it is breaking.
        """

        payload: dict[str, Any] = {
            "protocol_version": PROTOCOL_VERSION,
            "connection_id": self.connection_id,
            "event_id": event_id,
            "run_id": self.run.id,
            "type": event_type,
            "run_version": version,
        }
        payload.update(REQUIRED_EVENT_CONTENT.get(event_type, {}))
        payload.update(extra)
        return payload

    def projection(self) -> Any:
        return self.service.get_run(self.run.id, owner_id=OWNER)


@pytest.fixture
def relay(service: AgentRelayService, clock: Clock) -> Relay:
    return Relay(service, clock)


class TestMonitorRun:
    def test_accepted_and_running_events_update_the_projection(
        self, relay: Relay, clock: Clock
    ) -> None:
        """AC-011: reported state, progress, and last contact — nothing invented."""

        relay.emit(relay.event("evt_1", "accepted", 1))
        clock.advance(timedelta(minutes=1))
        relay.emit(relay.event("evt_2", "running", 2, progress="Cloning the repo"))

        run = relay.projection()
        assert run.reported_state == "running"
        assert run.run_version == 2
        assert run.progress_text == "Cloning the repo"
        assert run.last_contact_at == clock.now
        assert run.primary_state_label == "Running"
        assert [event.type for event in run.events] == ["accepted", "running"]

    def test_the_projection_never_carries_a_percentage_or_eta(
        self, relay: Relay
    ) -> None:
        """FR-011: BrainBuddy has no basis for either, so it exposes neither."""

        relay.emit(relay.event("evt_1", "running", 1, progress="Halfway-ish"))

        fields = set(relay.projection().model_dump())
        assert not fields & {
            "percent",
            "percent_complete",
            "eta",
            "eta_seconds",
            "stage",
        }

    def test_a_completed_event_is_labelled_as_the_agents_claim(
        self, relay: Relay
    ) -> None:
        """AC-014: BrainBuddy did not verify the work, and says so."""

        relay.emit(
            relay.event("evt_1", "completed", 1, result="Here is the migration plan.")
        )

        run = relay.projection()
        assert run.reported_state == "completed"
        assert run.primary_state_label == "Agent reported complete"
        assert run.result_text == "Here is the migration plan."

    @pytest.mark.parametrize(
        "link",
        [
            "https://results.example.com/1",
            "https://rebind.7f000001.nip.io/1",
            "http://results.example.com/1",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "https://169.254.169.254/1",
            "https://[::ffff:127.0.0.1]/1",
        ],
    )
    def test_a_reported_result_link_is_shown_but_never_interactive(
        self, relay: Relay, link: str
    ) -> None:
        """FR-014 (v1): the link is displayed honestly, as inert text."""

        relay.emit(relay.event("evt_1", "completed", 1, result=None, result_link=link))

        run = relay.projection()
        assert run.result_link == link
        assert run.result_link_interactive is False

    def test_a_failed_event_shows_the_reported_reason(self, relay: Relay) -> None:
        """AC-015: failure is reported, not retried."""

        relay.emit(relay.event("evt_1", "failed", 1, reason="Out of credit"))

        run = relay.projection()
        assert run.primary_state_label == "Failed"
        assert run.failure_reason == "Out of credit"

    def test_silence_past_the_reporting_window_shows_stopped_reporting(
        self, relay: Relay, clock: Clock
    ) -> None:
        """AC-016: an overlay, not a claim that the agent stopped."""

        relay.emit(relay.event("evt_1", "running", 1))
        clock.advance(relay.service.reporting_window + timedelta(seconds=1))

        run = relay.projection()
        assert run.stopped_reporting is True
        assert run.reported_state == "running"
        assert run.primary_state_label == "Stopped reporting"
        assert run.last_contact_at is not None

    def test_a_completion_after_silence_still_lands_and_clears_the_overlay(
        self, relay: Relay, clock: Clock
    ) -> None:
        """Edge case: a late but valid event wins over the silence marker."""

        relay.emit(relay.event("evt_1", "running", 1))
        clock.advance(relay.service.reporting_window + timedelta(minutes=5))
        assert relay.projection().stopped_reporting is True

        relay.emit(relay.event("evt_2", "completed", 2, result="Late but done"))

        run = relay.projection()
        assert run.stopped_reporting is False
        assert run.primary_state_label == "Agent reported complete"
        assert [event.type for event in run.events] == ["running", "completed"]

    def test_a_terminal_run_never_leaves_its_terminal_state(self, relay: Relay) -> None:
        """FR-008: after a terminal state, later state changes are rejected."""

        relay.emit(relay.event("evt_1", "completed", 1, result="Done"))

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_2", "running", 2))

        assert relay.projection().reported_state == "completed"

    def test_a_terminal_run_does_not_go_stale(self, relay: Relay, clock: Clock) -> None:
        """FR-013: the reporting window only applies to non-terminal runs."""

        relay.emit(relay.event("evt_1", "completed", 1, result="Done"))
        clock.advance(relay.service.reporting_window * 10)

        assert relay.projection().stopped_reporting is False

    def test_a_completed_run_does_not_touch_the_canonical_task(
        self, relay: Relay
    ) -> None:
        """FR-012: an external report never mutates the Task."""

        relay.emit(relay.event("evt_1", "completed", 1, result="Done"))

        # The snapshot port is read-only by construction; assert the run knows
        # it is only evidence attached to the task.
        assert relay.projection().task_id == "task_1"
        assert TASKS["task_1"].title == "Draft the migration plan"


class TestEventAuthentication:
    def test_a_wrong_signature_changes_nothing(self, relay: Relay) -> None:
        """SC-003: an unauthenticated event is rejected with zero effect."""

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_1", "running", 1), secret="not-the-secret")

        assert relay.projection().reported_state is None

    @pytest.mark.parametrize("timestamp", ["+1", "01", " 1", "1 ", "-1"])
    def test_noncanonical_timestamp_text_is_refused(
        self, relay: Relay, timestamp: str
    ) -> None:
        body = json.dumps(relay.event("evt_1", "running", 1)).encode("utf-8")

        with pytest.raises(EventRejected) as rejected:
            relay.service.ingest_event(
                raw_body=body,
                connection_id=relay.connection_id,
                timestamp=timestamp,
                signature="v1=" + "0" * 64,
            )

        assert rejected.value.code == "timestamp_invalid"

    def test_a_tampered_body_changes_nothing(self, relay: Relay, clock: Clock) -> None:
        """The signature covers the whole request, so edits are detected."""

        payload = relay.event("evt_1", "running", 1)
        body = json.dumps(payload).encode("utf-8")
        timestamp = int(clock.now.timestamp())
        signature = sign(relay.secret, timestamp, body)
        tampered = json.dumps({**payload, "type": "completed"}).encode("utf-8")

        with pytest.raises(EventRejected):
            relay.service.ingest_event(
                raw_body=tampered,
                connection_id=relay.connection_id,
                timestamp=str(timestamp),
                signature=signature,
            )

        assert relay.projection().reported_state is None

    def test_a_stale_timestamp_is_refused(self, relay: Relay, clock: Clock) -> None:
        """Freshness bounds replay of a captured, correctly signed request."""

        payload = relay.event("evt_1", "running", 1)
        body = json.dumps(payload).encode("utf-8")
        old = int((clock.now - timedelta(hours=2)).timestamp())

        with pytest.raises(EventRejected):
            relay.service.ingest_event(
                raw_body=body,
                connection_id=relay.connection_id,
                timestamp=str(old),
                signature=sign(relay.secret, old, body),
            )

        assert relay.projection().reported_state is None

    def test_a_duplicate_event_id_is_consumed_once(self, relay: Relay) -> None:
        """Duplicate delivery is idempotent."""

        relay.emit(relay.event("evt_1", "running", 1, progress="First"))

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_1", "running", 2, progress="Second"))

        run = relay.projection()
        assert run.progress_text == "First"
        assert run.run_version == 1

    @pytest.mark.parametrize("version", [1, 2])
    def test_an_equal_or_lower_version_cannot_overwrite_a_newer_state(
        self, relay: Relay, version: int
    ) -> None:
        """FR-009: an older event never regresses the projection."""

        relay.emit(relay.event("evt_1", "running", 2, progress="Newer"))

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_late", "accepted", version))

        assert relay.projection().progress_text == "Newer"

    def test_an_unknown_run_is_refused(self, relay: Relay) -> None:
        """A signed event for a run we do not have changes nothing."""

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_x", "running", 1, run_id="agentrun_missing"))

    def test_an_event_for_another_connections_run_is_refused(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """A connection may only report on runs it was dispatched."""

        other = service.create_connection(
            create_request(name="Second agent"),
            owner_id=OWNER,
            idempotency_key="idem-other",
            reauthenticated=True,
        )
        # Signed correctly, by the right owner, and internally consistent: the
        # only thing wrong is that this run was never dispatched to *this*
        # connection.
        payload = relay.event("evt_1", "running", 1, connection_id=other.id)
        body = json.dumps(payload).encode("utf-8")
        timestamp = int(relay.clock.now.timestamp())

        with pytest.raises(EventRejected):
            service.ingest_event(
                raw_body=body,
                connection_id=other.id,
                timestamp=str(timestamp),
                signature=sign(other.inbound_signing_secret, timestamp, body),
            )

        assert relay.projection().reported_state is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"run_id": "x", "type": "running", "run_version": 1},
            {"event_id": "e", "type": "running", "run_version": 1},
            {"event_id": "e", "run_id": "x", "run_version": 1},
            {"event_id": "e", "run_id": "x", "type": "running"},
            {"event_id": "e", "run_id": "x", "type": "nonsense", "run_version": 1},
            {"event_id": "e", "run_id": "x", "type": "running", "run_version": 0},
            {"event_id": "e", "run_id": "x", "type": "running", "run_version": "one"},
        ],
    )
    def test_a_malformed_envelope_is_refused(
        self, relay: Relay, payload: dict[str, Any]
    ) -> None:
        """SC-003: schema violations change nothing."""

        with pytest.raises(EventRejected):
            relay.emit(payload)

        assert relay.projection().reported_state is None


class TestStrictEventEnvelope:
    """FR-009: the versioned envelope is exact, and checked before any mutation.

    A connector report is an unauthenticated caller's JSON until the signature
    verifies, and even then it is only *authentic*, not *well formed*. Anything
    the contract does not name for that event type is a protocol error, not
    something to quietly ignore — silently dropping an unknown field is how a
    connector ends up believing it reported something BrainBuddy never stored.
    """

    def test_a_well_formed_envelope_names_its_own_connection(
        self, relay: Relay
    ) -> None:
        """The happy path binds protocol version and connection inside the body."""

        payload = relay.event("evt_1", "running", 1, progress="Cloning the repo")

        assert payload["protocol_version"] == PROTOCOL_VERSION
        assert payload["connection_id"] == relay.connection_id
        assert relay.emit(payload).accepted is True

    @pytest.mark.parametrize(
        "override",
        [
            {"protocol_version": "1999-01-01"},
            {"protocol_version": ""},
            {"connection_id": "agentconn_someone_else"},
            {"connection_id": ""},
        ],
    )
    def test_a_body_that_names_the_wrong_scope_is_refused(
        self, relay: Relay, override: dict[str, Any]
    ) -> None:
        """The signature proves who sent it; the body has to agree with that."""

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_1", "running", 1, **override))

        assert relay.projection().reported_state is None

    @pytest.mark.parametrize("field", ["protocol_version", "connection_id"])
    def test_an_envelope_missing_a_binding_field_is_refused(
        self, relay: Relay, field: str
    ) -> None:
        """Both bindings are required, not defaulted."""

        payload = relay.event("evt_1", "running", 1)
        payload.pop(field)

        with pytest.raises(EventRejected):
            relay.emit(payload)

        assert relay.projection().reported_state is None

    def test_an_unknown_field_is_refused_rather_than_ignored(
        self, relay: Relay
    ) -> None:
        """`extra=forbid`: a field we do not understand is a protocol error."""

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_1", "running", 1, percent_complete=42))

        assert relay.projection().reported_state is None

    @pytest.mark.parametrize(
        ("event_type", "override"),
        [
            ("blocked", {"question": None}),
            ("blocked", {"question": "   "}),
            ("completed", {"result": None}),
            ("failed", {"reason": None}),
            ("failed", {"reason": ""}),
        ],
    )
    def test_a_type_without_its_required_payload_is_refused(
        self, relay: Relay, event_type: str, override: dict[str, Any]
    ) -> None:
        """Each type's own required content is part of the contract."""

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_1", event_type, 1, **override))

        assert relay.projection().reported_state is None

    def test_completed_is_satisfied_by_a_result_link_alone(self, relay: Relay) -> None:
        """A result the agent hosts elsewhere is still a reported result."""

        relay.emit(
            relay.event(
                "evt_1",
                "completed",
                1,
                result=None,
                result_link="https://results.example.com/1",
            )
        )

        assert relay.projection().reported_state == "completed"

    @pytest.mark.parametrize("event_type", ["accepted", "running"])
    @pytest.mark.parametrize(
        "override",
        [
            {"question": "Which environment?"},
            {"result": "Done."},
            {"reason": "Out of credit"},
            {"result_link": "https://results.example.com/1"},
        ],
    )
    def test_a_non_terminal_type_cannot_carry_terminal_content(
        self, relay: Relay, event_type: str, override: dict[str, Any]
    ) -> None:
        """`running` with a result is not a completion, so it is not accepted."""

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_1", event_type, 1, **override))

        assert relay.projection().reported_state is None

    @pytest.mark.parametrize(
        ("event_type", "override"),
        [
            ("blocked", {"result": "Done."}),
            ("blocked", {"progress": "Halfway"}),
            ("completed", {"reason": "Out of credit"}),
            ("completed", {"question": "Which environment?"}),
            ("completed", {"progress": "Halfway"}),
            ("failed", {"result": "Done."}),
            ("failed", {"result_link": "https://results.example.com/1"}),
            ("cancelled", {"result": "Done."}),
            ("cancelled", {"reason": "Out of credit"}),
            ("cancelled", {"progress": "Halfway"}),
        ],
    )
    def test_a_type_carrying_another_types_field_is_refused(
        self, relay: Relay, event_type: str, override: dict[str, Any]
    ) -> None:
        """Each type carries its own payload and nothing else."""

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_1", event_type, 1, **override))

        assert relay.projection().reported_state is None

    @pytest.mark.parametrize(
        "override",
        [
            {"run_version": "2"},
            {"event_id": 7},
            {"run_id": None},
            {"progress": 12},
        ],
    )
    def test_a_wrongly_typed_field_is_refused(
        self, relay: Relay, override: dict[str, Any]
    ) -> None:
        """No coercion: a string version is not a version."""

        with pytest.raises(EventRejected):
            relay.emit({**relay.event("evt_1", "running", 1), **override})

        assert relay.projection().reported_state is None

    def test_a_rejected_envelope_leaves_its_event_id_unspent(
        self, relay: Relay
    ) -> None:
        """FR-009: a malformed event must not burn the replay identifier.

        Otherwise one malformed delivery would permanently block the connector
        from ever retrying that event correctly.
        """

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_1", "running", 1, percent_complete=42))

        relay.emit(relay.event("evt_1", "running", 1, progress="Cloning the repo"))

        run = relay.projection()
        assert run.reported_state == "running"
        assert run.progress_text == "Cloning the repo"

    def test_an_over_long_field_is_refused_without_truncation(
        self, relay: Relay
    ) -> None:
        """Finite limits are refusals, not silent trims."""

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_1", "blocked", 1, question="q" * 4_001))

        assert relay.projection().reported_state is None

    def test_an_oversized_event_is_refused(self, relay: Relay) -> None:
        """Bounded payloads: a flood cannot be persisted."""

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_big", "running", 1, progress="x" * 200_000))

        assert relay.projection().reported_state is None

    def test_agent_text_is_stored_inert(self, relay: Relay) -> None:
        """FR-014: markup is text, never something a client should execute."""

        relay.emit(
            relay.event(
                "evt_1", "completed", 1, result="<script>alert('x')</script> done"
            )
        )

        # Stored verbatim as text; escaping is the renderer's job, and no
        # server-side interpretation ever happens.
        assert relay.projection().result_text == "<script>alert('x')</script> done"


class TestReplyAndCancel:
    def test_a_blocked_event_asks_the_user_and_flags_needs_you(
        self, relay: Relay
    ) -> None:
        """AC-012: a question surfaces as a needs-you condition."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))

        run = relay.projection()
        assert run.reported_state == "blocked"
        assert run.question_text == "Which environment?"
        assert run.needs_user is True
        assert run.primary_state_label == "Needs you"

    @pytest.mark.parametrize(
        ("event_type", "label"),
        [
            ("running", "Running"),
            ("accepted", "Accepted"),
            ("completed", "Agent reported complete"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
    )
    def test_leaving_blocked_clears_the_question(
        self, relay: Relay, event_type: str, label: str
    ) -> None:
        """FR-008: the question belongs to `blocked`, so it must not outlive it.

        A stale `question_text` is what makes a finished run still offer an
        answer control for a question nobody is waiting on.
        """

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        relay.emit(relay.event("evt_2", event_type, 2))

        run = relay.projection()
        assert run.reported_state == event_type
        assert run.question_text is None
        assert run.needs_user is False
        assert run.primary_state_label == label

    def test_clearing_the_question_keeps_it_in_the_timeline(self, relay: Relay) -> None:
        """History is preserved: only the live state-owned field is cleared."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        relay.emit(relay.event("evt_2", "running", 2, progress="Deploying"))

        run = relay.projection()
        assert run.question_text is None
        assert [(event.type, event.summary) for event in run.events] == [
            ("blocked", "Which environment?"),
            ("running", "Deploying"),
        ]

    def test_a_second_blocked_event_replaces_the_earlier_question(
        self, relay: Relay
    ) -> None:
        """Re-entering `blocked` asks the new question, never the old one."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        relay.emit(relay.event("evt_2", "running", 2))
        relay.emit(relay.event("evt_3", "blocked", 3, question="Which branch?"))

        run = relay.projection()
        assert run.question_text == "Which branch?"
        assert run.needs_user is True

    def test_a_blocked_event_without_a_question_is_refused(self, relay: Relay) -> None:
        """`blocked` means "I need an answer", so the question is mandatory.

        Accepting a questionless block would leave the user a needs-you badge
        with nothing to answer, and would tempt the projection into showing the
        previous question as if it were still live.
        """

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        relay.emit(relay.event("evt_2", "running", 2))

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_3", "blocked", 3, question=None))

        run = relay.projection()
        assert run.reported_state == "running"
        assert run.question_text is None

    def test_leaving_blocked_leaves_other_reported_content_intact(
        self, relay: Relay
    ) -> None:
        """Only the question is state-owned; progress and results are history."""

        relay.emit(relay.event("evt_1", "running", 1, progress="Cloning the repo"))
        relay.emit(relay.event("evt_2", "blocked", 2, question="Which environment?"))
        relay.emit(relay.event("evt_3", "completed", 3, result="Done, see the PR."))

        run = relay.projection()
        assert run.question_text is None
        assert run.progress_text == "Cloning the repo"
        assert run.result_text == "Done, see the PR."

    def test_a_reply_is_routed_once_and_does_not_clear_blocked(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """AC-012 / FR-008: only a later authenticated event moves the state."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))

        run = service.reply_to_run(
            relay.run.id,
            AgentReplyRequest(
                message="Use staging.", expected_revision=relay.projection().revision
            ),
            owner_id=OWNER,
            idempotency_key="idem-reply",
        )

        assert run.reported_state == "blocked"
        assert [command.kind for command in run.commands if command.kind == "reply"]
        assert len(relay.service.connector.commands) == 1  # type: ignore[attr-defined]

    def test_a_synchronous_callback_during_reply_wins_over_transport_merge(
        self,
        relay: Relay,
        service: AgentRelayService,
        connector: FakeConnector,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        expected_revision = relay.projection().revision

        def command_with_callback(
            target: ConnectorTarget, *, envelope: dict[str, Any]
        ) -> ConnectorCommandOutcome:
            connector.commands.append(envelope)
            relay.emit(relay.event("evt_2", "running", 2, progress="Continuing"))
            return ConnectorCommandOutcome("confirmed")

        monkeypatch.setattr(connector, "command", command_with_callback)

        run = service.reply_to_run(
            relay.run.id,
            AgentReplyRequest(
                message="Use staging.", expected_revision=expected_revision
            ),
            owner_id=OWNER,
            idempotency_key="idem-sync-reply",
        )

        assert run.reported_state == "running"
        assert run.run_version == 2
        assert run.progress_text == "Continuing"
        assert run.reply_pending is False
        assert len(connector.commands) == 1

    def test_a_synchronous_callback_during_cancel_wins_over_transport_merge(
        self,
        relay: Relay,
        service: AgentRelayService,
        connector: FakeConnector,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def command_with_callback(
            target: ConnectorTarget, *, envelope: dict[str, Any]
        ) -> ConnectorCommandOutcome:
            connector.commands.append(envelope)
            relay.emit(relay.event("evt_1", "completed", 1, result="Already done"))
            return ConnectorCommandOutcome("confirmed")

        monkeypatch.setattr(connector, "command", command_with_callback)

        run = service.cancel_run(
            relay.run.id,
            owner_id=OWNER,
            idempotency_key="idem-sync-cancel",
        )

        assert run.reported_state == "completed"
        assert run.result_text == "Already done"
        assert run.cancel_requested is False
        assert len(connector.commands) == 1

    def test_a_synchronous_nonterminal_callback_during_cancel_preserves_cancellation_overlay(
        self,
        relay: Relay,
        service: AgentRelayService,
        connector: FakeConnector,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        before = relay.projection()
        attempted_at = clock.now
        callback_at = attempted_at + timedelta(minutes=1)
        mutation_at = attempted_at + timedelta(minutes=2)

        def command_with_callback(
            target: ConnectorTarget, *, envelope: dict[str, Any]
        ) -> ConnectorCommandOutcome:
            connector.commands.append(envelope)
            clock.advance(timedelta(minutes=1))
            relay.emit(
                relay.event("evt_running", "running", 1, progress="Still working")
            )
            clock.advance(timedelta(minutes=1))
            return ConnectorCommandOutcome("confirmed")

        monkeypatch.setattr(connector, "command", command_with_callback)

        run = service.cancel_run(
            relay.run.id,
            owner_id=OWNER,
            idempotency_key="idem-sync-nonterminal-cancel",
        )

        persisted = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        assert run.reported_state == "running"
        assert run.run_version == 1
        assert run.progress_text == "Still working"
        assert run.cancel_requested is True
        assert persisted.cancel_requested_at == attempted_at
        assert persisted.updated_at >= callback_at
        assert persisted.updated_at == mutation_at
        assert run.revision == before.revision + 2
        command = next(item for item in run.commands if item.kind == "cancel")
        assert command.delivery == "confirmed"

    def test_a_stale_reply_revision_is_refused_before_connector_delivery(
        self, relay: Relay, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        stale_revision = relay.projection().revision
        relay.emit(relay.event("evt_2", "blocked", 2, question="Which region?"))

        with pytest.raises(ConflictError):
            service.reply_to_run(
                relay.run.id,
                AgentReplyRequest(
                    message="Use staging.", expected_revision=stale_revision
                ),
                owner_id=OWNER,
                idempotency_key="idem-stale-reply",
            )

        assert connector.commands == []
        assert [c for c in relay.projection().commands if c.kind == "reply"] == []

    def test_replaying_a_reply_causes_at_most_one_connector_action(
        self, relay: Relay, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """FR-007: a duplicate submission returns the same command."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        payload = AgentReplyRequest(
            message="Use staging.", expected_revision=relay.projection().revision
        )
        for _ in range(3):
            service.reply_to_run(
                relay.run.id,
                payload,
                owner_id=OWNER,
                idempotency_key="idem-reply",
            )

        assert len(connector.commands) == 1

    def test_an_unconfirmed_reply_stays_visibly_unconfirmed(
        self, relay: Relay, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """Edge case: a timed-out reply is never claimed as delivered."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        connector.command_outcome = ConnectorCommandOutcome("unconfirmed")

        run = service.reply_to_run(
            relay.run.id,
            AgentReplyRequest(
                message="Use staging.", expected_revision=relay.projection().revision
            ),
            owner_id=OWNER,
            idempotency_key="idem-reply",
        )

        reply = next(c for c in run.commands if c.kind == "reply")
        assert reply.delivery == "unconfirmed"
        assert run.reply_pending is True

    def test_replying_through_a_connector_without_reply_support_is_refused(
        self, service: AgentRelayService, connector: FakeConnector, clock: Clock
    ) -> None:
        """AC-013: an unsupported control is unavailable, never simulated."""

        connector.test_outcome = ConnectorTestOutcome(
            "ready", AgentCapabilities(progress=True, reply=False, cancel=False)
        )
        relay = Relay(service, clock)
        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))

        run = relay.projection()
        assert run.capabilities.reply is False

        with pytest.raises(ValidationFailure):
            service.reply_to_run(
                relay.run.id,
                AgentReplyRequest(
                    message="Use staging.",
                    expected_revision=relay.projection().revision,
                ),
                owner_id=OWNER,
                idempotency_key="idem-reply",
            )

    def test_cancel_is_requested_but_not_claimed_until_confirmed(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """AC-017: 'Cancelling' is not 'Cancelled'."""

        relay.emit(relay.event("evt_1", "running", 1))

        run = service.cancel_run(
            relay.run.id, owner_id=OWNER, idempotency_key="idem-cancel"
        )

        assert run.cancel_requested is True
        assert run.reported_state == "running"
        assert run.primary_state_label == "Cancellation requested"

    def test_cancel_becomes_cancelled_only_on_a_connector_event(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """The connector's own report is what makes it cancelled."""

        relay.emit(relay.event("evt_1", "running", 1))
        service.cancel_run(relay.run.id, owner_id=OWNER, idempotency_key="idem-cancel")

        relay.emit(relay.event("evt_2", "cancelled", 2))

        run = relay.projection()
        assert run.reported_state == "cancelled"
        assert run.primary_state_label == "Cancelled"
        assert run.cancel_requested is False

    @pytest.mark.parametrize(
        ("terminal_type", "content"),
        [
            ("completed", {"result": "Done."}),
            ("failed", {"reason": "Broken."}),
            ("cancelled", {}),
        ],
    )
    def test_every_terminal_event_clears_the_pending_cancellation_condition(
        self,
        relay: Relay,
        service: AgentRelayService,
        terminal_type: str,
        content: dict[str, str],
    ) -> None:
        relay.emit(relay.event("evt_1", "running", 1))
        service.cancel_run(relay.run.id, owner_id=OWNER, idempotency_key="idem-cancel")

        relay.emit(relay.event("evt_2", terminal_type, 2, **content))

        run = relay.projection()
        assert run.reported_state == terminal_type
        assert run.cancel_requested is False
        assert [
            command.kind for command in run.commands if command.kind == "cancel"
        ] == ["cancel"]

    def test_cancelling_through_a_connector_without_cancel_support_is_refused(
        self, service: AgentRelayService, connector: FakeConnector, clock: Clock
    ) -> None:
        """AC-017: without support the control is absent, not fake."""

        connector.test_outcome = ConnectorTestOutcome(
            "ready", AgentCapabilities(progress=True, reply=True, cancel=False)
        )
        relay = Relay(service, clock)

        with pytest.raises(ValidationFailure):
            service.cancel_run(
                relay.run.id, owner_id=OWNER, idempotency_key="idem-cancel"
            )

    def test_another_owner_cannot_reply_to_or_cancel_the_run(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """Owner isolation covers commands too."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))

        with pytest.raises(NotFoundError):
            service.reply_to_run(
                relay.run.id,
                AgentReplyRequest(message="Nope.", expected_revision=1),
                owner_id=OTHER_OWNER,
                idempotency_key="idem-reply",
            )
        with pytest.raises(NotFoundError):
            service.cancel_run(
                relay.run.id, owner_id=OTHER_OWNER, idempotency_key="idem-cancel"
            )


class TestExternalIoMergeRaces:
    @pytest.mark.parametrize("operation", ["reply", "cancel"])
    @pytest.mark.parametrize("bypass_operation_lock", [False, True])
    def test_concurrent_same_key_commands_contend_and_converge_only_with_lock(
        self,
        tmp_path: Path,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
        operation: str,
        bypass_operation_lock: bool,
    ) -> None:
        connector = BlockingIoConnector()
        repo = AgentRepository(tmp_path)
        service = build_service(repo, connector, clock)
        relay = Relay(service, clock)
        connector.commands.clear()
        idempotency_key = f"idem-concurrent-{operation}"
        if operation == "reply":
            relay.emit(relay.event("evt_blocked", "blocked", 1))
            payload = AgentReplyRequest(
                message="Use staging.", expected_revision=relay.projection().revision
            )

            def invoke_command() -> Any:
                return service.reply_to_run(
                    relay.run.id,
                    payload,
                    owner_id=OWNER,
                    idempotency_key=idempotency_key,
                )

        else:

            def invoke_command() -> Any:
                return service.cancel_run(
                    relay.run.id,
                    owner_id=OWNER,
                    idempotency_key=idempotency_key,
                )

        connector.block_kind = operation
        results: list[Any] = []
        errors: list[BaseException] = []
        attempts: list[tuple[str, str]] = []
        second_attempted = Event()
        second_acquired = Event()
        second_finished = Event()
        operation_lock = repo.operation_lock
        expected_fingerprint = service._key_fingerprint(OWNER, idempotency_key)

        @contextmanager
        def observed_operation_lock(owner_id: str, operation_fingerprint: str) -> Any:
            attempts.append((owner_id, operation_fingerprint))
            attempt_number = len(attempts)
            if attempt_number == 2:
                second_attempted.set()
            if bypass_operation_lock:
                if attempt_number == 2:
                    second_acquired.set()
                yield
                return
            with operation_lock(owner_id, operation_fingerprint):
                if attempt_number == 2:
                    second_acquired.set()
                yield

        monkeypatch.setattr(repo, "operation_lock", observed_operation_lock)

        def invoke(*, second: bool = False) -> None:
            try:
                results.append(invoke_command())
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)
            finally:
                if second:
                    second_finished.set()

        first = Thread(target=invoke)
        second = Thread(target=lambda: invoke(second=True))
        first.start()
        assert connector.entered.wait(timeout=5)
        second.start()
        assert second_attempted.wait(timeout=5)
        assert attempts == [
            (OWNER, expected_fingerprint),
            (OWNER, expected_fingerprint),
        ]
        if bypass_operation_lock:
            assert second_acquired.wait(timeout=5)
            assert second_finished.wait(timeout=5)
        else:
            assert second_acquired.is_set() is False
            assert second_finished.is_set() is False
        connector.release.set()
        first.join(timeout=5)
        second.join(timeout=5)

        assert errors == []
        assert len(connector.commands) == 1
        assert len(results) == 2
        command_id = connector.commands[0]["command_id"]
        assert results[0].id == results[1].id == relay.run.id
        assert [item.id for item in results[0].commands if item.kind == operation] == [
            command_id
        ]
        assert [item.id for item in results[1].commands if item.kind == operation] == [
            command_id
        ]
        if bypass_operation_lock:
            assert results[0].model_dump() != results[1].model_dump()
        else:
            assert second_acquired.is_set() is True
            assert results[0].model_dump() == results[1].model_dump()

    @pytest.mark.parametrize(
        "race", ["terminal", "retention", "rotation", "disconnect"]
    )
    def test_cancel_transport_merge_cannot_revive_or_overwrite_newer_state(
        self, tmp_path: Path, clock: Clock, race: str
    ) -> None:
        connector = BlockingIoConnector()
        service = build_service(AgentRepository(tmp_path), connector, clock)
        relay = Relay(service, clock)
        connector.commands.clear()
        connector.block_kind = "cancel"
        errors: list[BaseException] = []

        def invoke() -> None:
            try:
                service.cancel_run(
                    relay.run.id,
                    owner_id=OWNER,
                    idempotency_key=f"idem-cancel-race-{race}",
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        worker = Thread(target=invoke)
        worker.start()
        assert connector.entered.wait(timeout=5)
        if race == "terminal":
            relay.emit(relay.event("evt_cancel_done", "completed", 1, result="Done"))
        elif race == "retention":
            persisted = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
            service.agent_repo.expire_due_content(now=persisted.content_expires_at)
        elif race == "rotation":
            current = service.get_connection(relay.connection_id, owner_id=OWNER)
            service.rotate_credential(
                relay.connection_id,
                AgentConnectionRotateRequest(
                    credential="Bearer rotated-token",
                    current_password="correct-horse-battery-staple",
                    expected_revision=current.revision,
                ),
                owner_id=OWNER,
                idempotency_key="idem-cancel-race-rotation-connection",
                reauthenticated=True,
            )
        else:
            current = service.get_connection(relay.connection_id, owner_id=OWNER)
            service.disconnect_connection(
                relay.connection_id,
                AgentConnectionDisconnectRequest(
                    current_password="correct-horse-battery-staple",
                    expected_revision=current.revision,
                ),
                owner_id=OWNER,
                idempotency_key="idem-cancel-race-disconnect-connection",
                reauthenticated=True,
            )
        connector.release.set()
        worker.join(timeout=5)

        assert errors == []
        run = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        assert len(connector.commands) == 1
        if race == "terminal":
            assert run.reported_state == "completed"
            assert run.cancel_requested_at is None
        elif race == "retention":
            assert run.content_expired is True
            assert run.manifest is None
        elif race == "rotation":
            connection = service.agent_repo.get_connection(
                relay.connection_id, owner_id=OWNER
            )
            assert connection.status == "untested"
            assert run.cancel_requested_at is None
        else:
            assert run.connection_disconnected_at is not None
            assert run.cancel_requested_at is None

    def test_start_retention_race_is_a_write_barrier_not_content_revival(
        self, tmp_path: Path, clock: Clock
    ) -> None:
        connector = BlockingIoConnector()
        service = build_service(AgentRepository(tmp_path), connector, clock)
        connection_id = connect(service)
        make_ready(service, connection_id)
        confirmation = review(service, connection_id)
        reserved = service.agent_repo.list_runs_for_task("task_1", owner_id=OWNER)[0]
        connector.block_kind = "start"
        errors: list[BaseException] = []

        def invoke() -> None:
            try:
                service.dispatch_run(
                    "task_1",
                    confirmation,
                    owner_id=OWNER,
                    idempotency_key="idem-start-retention-race",
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        worker = Thread(target=invoke)
        worker.start()
        assert connector.entered.wait(timeout=5)
        service.agent_repo.expire_due_content(now=clock.now + service.content_retention)
        connector.release.set()
        worker.join(timeout=5)

        assert errors == []
        current = service.agent_repo.get_run(reserved.id, owner_id=OWNER)
        assert current.content_expired is True
        assert current.manifest is None
        assert len(connector.starts) == 1

    @pytest.mark.parametrize("race", ["terminal", "rotation", "disconnect"])
    def test_start_transport_merge_preserves_newer_terminal_or_connection_state(
        self, tmp_path: Path, clock: Clock, race: str
    ) -> None:
        connector = BlockingIoConnector()
        service = build_service(AgentRepository(tmp_path), connector, clock)
        created = service.create_connection(
            create_request(),
            owner_id=OWNER,
            idempotency_key="idem-start-race-create",
            reauthenticated=True,
        )
        make_ready(service, created.id)
        confirmation = review(service, created.id)
        reserved = service.agent_repo.list_runs_for_task("task_1", owner_id=OWNER)[0]
        connector.block_kind = "start"
        errors: list[BaseException] = []

        def invoke() -> None:
            try:
                service.dispatch_run(
                    "task_1",
                    confirmation,
                    owner_id=OWNER,
                    idempotency_key=f"idem-start-race-{race}",
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        worker = Thread(target=invoke)
        worker.start()
        assert connector.entered.wait(timeout=5)
        if race == "terminal":
            event = {
                "protocol_version": PROTOCOL_VERSION,
                "connection_id": created.id,
                "event_id": "evt_start_done",
                "run_id": reserved.id,
                "type": "completed",
                "run_version": 1,
                "result": "Already done",
            }
            body = json.dumps(event).encode("utf-8")
            timestamp = int(clock.now.timestamp())
            service.ingest_event(
                raw_body=body,
                connection_id=created.id,
                timestamp=str(timestamp),
                signature=sign(created.inbound_signing_secret, timestamp, body),
            )
        elif race == "rotation":
            current = service.get_connection(created.id, owner_id=OWNER)
            service.rotate_credential(
                created.id,
                AgentConnectionRotateRequest(
                    credential="Bearer rotated-token",
                    current_password="correct-horse-battery-staple",
                    expected_revision=current.revision,
                ),
                owner_id=OWNER,
                idempotency_key="idem-start-race-rotation-connection",
                reauthenticated=True,
            )
        else:
            current = service.get_connection(created.id, owner_id=OWNER)
            service.disconnect_connection(
                created.id,
                AgentConnectionDisconnectRequest(
                    current_password="correct-horse-battery-staple",
                    expected_revision=current.revision,
                ),
                owner_id=OWNER,
                idempotency_key="idem-start-race-disconnect-connection",
                reauthenticated=True,
            )
        connector.release.set()
        worker.join(timeout=5)

        assert errors == []
        current_run = service.agent_repo.get_run(reserved.id, owner_id=OWNER)
        assert len(connector.starts) == 1
        if race == "terminal":
            assert current_run.reported_state == "completed"
            assert current_run.result_text == "Already done"
        elif race == "rotation":
            connection = service.agent_repo.get_connection(created.id, owner_id=OWNER)
            assert connection.status == "untested"
            assert service._target(connection).credential == "Bearer rotated-token"
        else:
            assert current_run.connection_disconnected_at is not None

    @pytest.mark.parametrize(
        "race", ["terminal", "retention", "rotation", "disconnect"]
    )
    def test_reply_transport_merge_cannot_overwrite_newer_state(
        self, tmp_path: Path, clock: Clock, race: str
    ) -> None:
        connector = BlockingIoConnector()
        service = build_service(AgentRepository(tmp_path), connector, clock)
        relay = Relay(service, clock)
        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        payload = AgentReplyRequest(
            message="Use staging.", expected_revision=relay.projection().revision
        )
        connector.block_kind = "reply"
        results: list[Any] = []
        errors: list[BaseException] = []

        def invoke() -> None:
            try:
                results.append(
                    service.reply_to_run(
                        relay.run.id,
                        payload,
                        owner_id=OWNER,
                        idempotency_key=f"idem-race-{race}",
                    )
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        worker = Thread(target=invoke)
        worker.start()
        assert connector.entered.wait(timeout=5)

        if race == "terminal":
            relay.emit(relay.event("evt_2", "completed", 2, result="Finished"))
        elif race == "retention":
            persisted = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
            service.agent_repo.expire_due_content(now=persisted.content_expires_at)
        elif race == "rotation":
            current = service.get_connection(relay.connection_id, owner_id=OWNER)
            service.rotate_credential(
                relay.connection_id,
                AgentConnectionRotateRequest(
                    credential="Bearer rotated-token",
                    current_password="correct-horse-battery-staple",
                    expected_revision=current.revision,
                ),
                owner_id=OWNER,
                idempotency_key="idem-race-rotation-connection",
                reauthenticated=True,
            )
        else:
            current = service.get_connection(relay.connection_id, owner_id=OWNER)
            service.disconnect_connection(
                relay.connection_id,
                AgentConnectionDisconnectRequest(
                    current_password="correct-horse-battery-staple",
                    expected_revision=current.revision,
                ),
                owner_id=OWNER,
                idempotency_key="idem-race-disconnect-connection",
                reauthenticated=True,
            )

        connector.release.set()
        worker.join(timeout=5)

        assert errors == []
        assert len(results) == 1
        current_run = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        replies = service.agent_repo.list_commands(relay.run.id, owner_id=OWNER)
        reply = next(command for command in replies if command.kind == "reply")
        assert current_run.reply_pending_command_id is None
        assert reply.delivery == "confirmed"

        if race == "terminal":
            assert current_run.reported_state == "completed"
            assert current_run.result_text == "Finished"
        elif race == "retention":
            assert current_run.content_expired is True
            assert current_run.manifest is None
            assert reply.body is None
        elif race == "rotation":
            connection = service.agent_repo.get_connection(
                relay.connection_id, owner_id=OWNER
            )
            assert connection.status == "untested"
            assert service._target(connection).credential == "Bearer rotated-token"
        else:
            connection = service.agent_repo.get_connection(
                relay.connection_id, owner_id=OWNER
            )
            assert connection.status == "disconnected"
            assert connection.credential is None
            assert current_run.connection_disconnected_at is not None


class TestCommandReplayAfterTheWorldMoved:
    """A completed command answers its retry from the record, not the world.

    The dangerous window is the one where BrainBuddy already did the work and
    the caller never learned it: the reply went out, then the run finished or
    the connection was pulled, and only then does the retry arrive. Re-checking
    the *live* preconditions there would answer a successful command with "this
    run has already finished" — telling the owner their reply never happened
    when it did, and inviting a client to send it again under a fresh key. The
    settled record is the honest answer, and it costs no connector call.
    """

    def reply(
        self,
        service: AgentRelayService,
        relay: Relay,
        *,
        key: str = "idem-reply",
        message: str = "Use staging.",
        expected_revision: int | None = None,
    ) -> Any:
        revisions = getattr(self, "_reply_revisions", {})
        revision = expected_revision
        if revision is None:
            revision = revisions.setdefault(key, relay.projection().revision)
        self._reply_revisions = revisions
        return service.reply_to_run(
            relay.run.id,
            AgentReplyRequest(message=message, expected_revision=revision),
            owner_id=OWNER,
            idempotency_key=key,
        )

    def disconnect(self, service: AgentRelayService, relay: Relay) -> None:
        current = service.get_connection(relay.connection_id, owner_id=OWNER)
        service.disconnect_connection(
            relay.connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-disconnect",
            reauthenticated=True,
        )

    def test_a_reply_replayed_after_the_run_finished_returns_its_outcome(
        self, relay: Relay, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """The lost response is recovered even though the run has since ended."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        self.reply(service, relay)
        relay.emit(relay.event("evt_2", "completed", 2, result="Shipped."))

        replay = self.reply(service, relay)

        assert replay.id == relay.run.id
        assert [c.body for c in replay.commands if c.kind == "reply"] == [
            "Use staging."
        ]
        assert replay.reported_state == "completed"
        assert len(connector.commands) == 1

    def test_a_completed_reply_replay_precedes_the_live_revision_check(
        self, relay: Relay, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        revision = relay.projection().revision
        payload = AgentReplyRequest(message="Use staging.", expected_revision=revision)
        service.reply_to_run(
            relay.run.id,
            payload,
            owner_id=OWNER,
            idempotency_key="idem-reply-revision-replay",
        )
        relay.emit(relay.event("evt_2", "completed", 2, result="Shipped."))

        replay = service.reply_to_run(
            relay.run.id,
            payload,
            owner_id=OWNER,
            idempotency_key="idem-reply-revision-replay",
        )

        assert replay.reported_state == "completed"
        assert replay.revision > revision
        assert len(connector.commands) == 1

    def test_a_reply_replayed_after_a_disconnect_returns_its_outcome(
        self, relay: Relay, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """A pulled connection cannot retroactively un-send a delivered reply."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        self.reply(service, relay)
        self.disconnect(service, relay)

        replay = self.reply(service, relay)

        assert [c.body for c in replay.commands if c.kind == "reply"] == [
            "Use staging."
        ]
        assert replay.connection_disconnected is True
        assert len(connector.commands) == 1

    def test_a_cancel_replayed_after_the_run_finished_returns_its_outcome(
        self, relay: Relay, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """The request was really made, so the retry says so rather than 'too late'."""

        relay.emit(relay.event("evt_1", "running", 1))
        service.cancel_run(relay.run.id, owner_id=OWNER, idempotency_key="idem-cancel")
        relay.emit(relay.event("evt_2", "cancelled", 2))

        replay = service.cancel_run(
            relay.run.id, owner_id=OWNER, idempotency_key="idem-cancel"
        )

        assert replay.cancel_requested is False
        assert replay.reported_state == "cancelled"
        assert [c.kind for c in replay.commands if c.kind == "cancel"] == ["cancel"]
        assert len(connector.commands) == 1

    def test_a_cancel_replayed_after_a_disconnect_returns_its_outcome(
        self, relay: Relay, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """Same for the connection going away between attempt and retry."""

        relay.emit(relay.event("evt_1", "running", 1))
        service.cancel_run(relay.run.id, owner_id=OWNER, idempotency_key="idem-cancel")
        self.disconnect(service, relay)

        replay = service.cancel_run(
            relay.run.id, owner_id=OWNER, idempotency_key="idem-cancel"
        )

        assert replay.cancel_requested is True
        assert [c.kind for c in replay.commands if c.kind == "cancel"] == ["cancel"]
        assert len(connector.commands) == 1

    def test_another_owner_cannot_replay_a_settled_command(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """The record is owner-scoped, and so is the run it points at."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        self.reply(service, relay)

        with pytest.raises(NotFoundError):
            service.reply_to_run(
                relay.run.id,
                AgentReplyRequest(
                    message="Use staging.",
                    expected_revision=relay.projection().revision,
                ),
                owner_id=OTHER_OWNER,
                idempotency_key="idem-reply",
            )

    def test_the_same_key_with_a_different_message_still_conflicts(
        self, relay: Relay, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """Replay is for the *same* request; a new one must not ride the record."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        self.reply(service, relay)
        relay.emit(relay.event("evt_2", "completed", 2, result="Shipped."))

        with pytest.raises(ConflictError):
            self.reply(service, relay, message="Actually production.")

        assert len(connector.commands) == 1

    def test_a_fresh_key_on_a_finished_run_is_still_refused(
        self, relay: Relay, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """Nothing above weakens the live guard for a genuinely new command."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        self.reply(service, relay)
        relay.emit(relay.event("evt_2", "completed", 2, result="Shipped."))

        with pytest.raises(ValidationFailure) as refused:
            self.reply(service, relay, key="idem-reply-2")

        assert refused.value.detail == {"reason": "run_terminal"}
        assert len(connector.commands) == 1


# --- User Story 4: disconnect and bounded retention --------------------------


class TestDisconnectAndRetention:
    def test_disconnect_destroys_the_credential_and_blocks_new_hand_offs(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """AC-018: the secret is destroyed and the connection stops working."""

        current = service.get_connection(relay.connection_id, owner_id=OWNER)

        disconnected = service.disconnect_connection(
            relay.connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-disconnect",
            reauthenticated=True,
        )

        assert disconnected.status == "disconnected"
        assert disconnected.ready_for_handoff is False
        with pytest.raises(ValidationFailure):
            dispatch(service, relay.connection_id, key="idem-after-disconnect")

    def test_disconnect_requires_reauthentication(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """FR-016: destructive disconnect is a re-authenticated action."""

        current = service.get_connection(relay.connection_id, owner_id=OWNER)

        with pytest.raises(ValidationFailure):
            service.disconnect_connection(
                relay.connection_id,
                AgentConnectionDisconnectRequest(
                    current_password="correct-horse-battery-staple",
                    expected_revision=current.revision,
                ),
                owner_id=OWNER,
                idempotency_key="idem-disconnect",
                reauthenticated=False,
            )

    def test_disconnect_marks_active_runs_and_preserves_their_history(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """FR-016: history stays understandable; the run is not falsely ended."""

        relay.emit(relay.event("evt_1", "running", 1, progress="Working"))
        current = service.get_connection(relay.connection_id, owner_id=OWNER)
        service.disconnect_connection(
            relay.connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-disconnect",
            reauthenticated=True,
        )

        run = relay.projection()
        assert run.connection_disconnected is True
        assert run.primary_state_label == "Connection disconnected"
        assert run.progress_text == "Working"
        assert [event.type for event in run.events] == ["running"]

    def test_events_signed_by_a_destroyed_credential_are_refused(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """FR-016: a disconnected connection can no longer report."""

        current = service.get_connection(relay.connection_id, owner_id=OWNER)
        service.disconnect_connection(
            relay.connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-disconnect",
            reauthenticated=True,
        )

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_late", "completed", 5, result="Too late"))

    def test_replying_through_a_disconnected_connection_is_refused(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """FR-016: commands stop with the connection."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        current = service.get_connection(relay.connection_id, owner_id=OWNER)
        service.disconnect_connection(
            relay.connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-disconnect",
            reauthenticated=True,
        )

        with pytest.raises(ValidationFailure):
            service.reply_to_run(
                relay.run.id,
                AgentReplyRequest(
                    message="Use staging.",
                    expected_revision=relay.projection().revision,
                ),
                owner_id=OWNER,
                idempotency_key="idem-reply",
            )

    def test_relayed_content_expires_after_thirty_days(
        self, relay: Relay, clock: Clock, service: AgentRelayService
    ) -> None:
        """AC-020 / FR-010: content goes, the run stays, expiry is explicit."""

        relay.emit(relay.event("evt_1", "completed", 1, result="Sensitive result"))
        clock.advance(service.content_retention + timedelta(seconds=1))

        assert service.run_retention_sweep() == 1

        run = relay.projection()
        assert run.content_expired is True
        assert run.result_text is None
        assert run.manifest is None
        assert run.primary_state_label == "Content expired under retention policy"
        assert run.events and run.events[0].summary is None

    def test_due_unswept_content_is_redacted_at_every_read_boundary(
        self, relay: Relay, clock: Clock, service: AgentRelayService
    ) -> None:
        """FR-015 is an access boundary, not merely a maintenance schedule."""

        relay.emit(relay.event("evt_due", "blocked", 1, question="Secret question?"))
        service.reply_to_run(
            relay.run.id,
            AgentReplyRequest(
                message="Secret answer", expected_revision=relay.projection().revision
            ),
            owner_id=OWNER,
            idempotency_key="idem-due-reply",
        )
        persisted = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        clock.now = persisted.content_expires_at

        detail = service.get_run(relay.run.id, owner_id=OWNER)
        listed = service.list_runs_for_task("task_1", owner_id=OWNER)[0]
        summary = service.latest_run_summaries(owner_id=OWNER, task_ids=["task_1"])[
            "task_1"
        ]

        for projected in (detail, listed):
            assert projected.content_expired is True
            assert (
                projected.primary_state_label
                == "Content expired under retention policy"
            )
            assert projected.manifest is None
            assert projected.question_text is None
            assert all(event.summary is None for event in projected.events)
            assert all(command.body is None for command in projected.commands)
        assert summary.primary_state_label == "Content expired under retention policy"
        assert summary.needs_user is False

        unchanged = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        assert unchanged == persisted
        assert unchanged.content_expired is False
        assert unchanged.question_text == "Secret question?"

    def test_due_unswept_run_rejects_reply_but_still_allows_cancel(
        self,
        relay: Relay,
        clock: Clock,
        service: AgentRelayService,
        connector: FakeConnector,
    ) -> None:
        relay.emit(relay.event("evt_due", "blocked", 1, question="Secret question?"))
        persisted = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        clock.now = persisted.content_expires_at

        with pytest.raises(ValidationFailure) as refused:
            service.reply_to_run(
                relay.run.id,
                AgentReplyRequest(
                    message="Too late", expected_revision=persisted.revision
                ),
                owner_id=OWNER,
                idempotency_key="idem-due-refused",
            )
        cancelled = service.cancel_run(
            relay.run.id,
            owner_id=OWNER,
            idempotency_key="idem-due-cancel",
        )

        assert refused.value.detail == {"reason": "run_content_expired"}
        assert [command["type"] for command in connector.commands] == ["cancel"]
        assert cancelled.content_expired is True
        assert all(command.body is None for command in cancelled.commands)

    def test_a_fresh_reply_to_an_expired_run_is_refused_without_content_write(
        self,
        relay: Relay,
        clock: Clock,
        service: AgentRelayService,
        connector: FakeConnector,
    ) -> None:
        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        clock.advance(service.content_retention + timedelta(seconds=1))
        assert service.run_retention_sweep() == 1
        revision = relay.projection().revision

        with pytest.raises(ValidationFailure) as refused:
            service.reply_to_run(
                relay.run.id,
                AgentReplyRequest(message="New secret", expected_revision=revision),
                owner_id=OWNER,
                idempotency_key="idem-after-expiry",
            )

        assert refused.value.detail == {"reason": "run_content_expired"}
        assert connector.commands == []
        assert all(command.body is None for command in relay.projection().commands)

    def test_a_completed_same_key_reply_replays_after_content_expiry(
        self,
        relay: Relay,
        clock: Clock,
        service: AgentRelayService,
        connector: FakeConnector,
    ) -> None:
        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        payload = AgentReplyRequest(
            message="Use staging.", expected_revision=relay.projection().revision
        )
        first = service.reply_to_run(
            relay.run.id,
            payload,
            owner_id=OWNER,
            idempotency_key="idem-reply-before-expiry",
        )
        persisted = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        service.agent_repo.save_run(
            persisted.model_copy(update={"content_expires_at": clock.now})
        )
        clock.advance(timedelta(seconds=1))
        assert service.run_retention_sweep() == 1

        replay = service.reply_to_run(
            relay.run.id,
            payload,
            owner_id=OWNER,
            idempotency_key="idem-reply-before-expiry",
        )

        assert replay.id == first.id
        assert replay.content_expired is True
        assert len(connector.commands) == 1
        assert all(command.body is None for command in replay.commands)

    @pytest.mark.parametrize(
        ("event_type", "content"),
        [
            ("running", {"progress": "Secret progress"}),
            ("blocked", {"question": "Secret question?"}),
            ("completed", {"result": "Secret result"}),
            ("failed", {"reason": "Secret failure"}),
        ],
    )
    def test_late_events_advance_expired_runs_without_repopulating_content(
        self,
        relay: Relay,
        clock: Clock,
        service: AgentRelayService,
        event_type: str,
        content: dict[str, str],
    ) -> None:
        clock.advance(service.content_retention + timedelta(seconds=1))
        assert service.run_retention_sweep() == 1

        relay.emit(relay.event("evt_late", event_type, 1, **content))

        run = relay.projection()
        assert run.content_expired is True
        assert run.reported_state == event_type
        assert run.run_version == 1
        assert run.last_contact_at == clock.now
        assert run.progress_text is None
        assert run.question_text is None
        assert run.result_text is None
        assert run.result_link is None
        assert run.failure_reason is None
        assert run.events[-1].summary is None
        assert service.run_retention_sweep() == 0
        assert all(event.summary is None for event in relay.projection().events)

    def test_expiry_leaves_no_manifest_fingerprint_in_run_storage(
        self, relay: Relay, clock: Clock, service: AgentRelayService, tmp_path: Path
    ) -> None:
        """FR-015: the manifest token is content-derived, so it expires with it.

        The token is a hash over every content-bearing value the hand-off sent.
        Keeping a copy after retention would leave a fingerprint an attacker
        holding the database could confirm guesses against, which is exactly
        what expiring the content is supposed to prevent.
        """

        token = relay.run.manifest.token if relay.run.manifest else None
        assert token is not None
        relay.emit(relay.event("evt_1", "completed", 1, result="Sensitive result"))
        clock.advance(service.content_retention + timedelta(seconds=1))

        assert service.run_retention_sweep() == 1

        with sqlite3.connect(tmp_path / "agents.sqlite3") as conn:
            rows = conn.execute(
                "SELECT manifest_token, payload FROM agent_runs WHERE id = ?",
                (relay.run.id,),
            ).fetchall()

        assert rows and rows[0][0] is None
        stored = json.loads(rows[0][1])
        assert stored["manifest"] is None
        assert token not in rows[0][1]
        assert not [
            key
            for key, value in stored.items()
            if isinstance(value, str) and value == token
        ]

    def test_content_within_retention_is_untouched(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """Nothing expires early."""

        relay.emit(relay.event("evt_1", "completed", 1, result="Still here"))

        assert service.run_retention_sweep() == 0
        assert relay.projection().result_text == "Still here"

    def test_the_latest_run_summary_powers_the_compact_task_surface(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """FR-010: the compact surface shows only the latest run, honestly."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))

        summaries = service.latest_run_summaries(
            owner_id=OWNER, task_ids=["task_1", "task_2"]
        )

        assert summaries["task_1"].needs_user is True
        assert summaries["task_1"].primary_state_label == "Needs you"
        assert "task_2" not in summaries

    def test_purging_an_owner_removes_every_relay_record(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """AC-021: account purge leaves no connection, run, or audit behind."""

        relay.emit(relay.event("evt_1", "running", 1))

        service.delete_all_for_owner(owner_id=OWNER)

        assert service.list_connections(owner_id=OWNER) == []
        with pytest.raises(NotFoundError):
            service.get_run(relay.run.id, owner_id=OWNER)

    def test_event_authenticated_before_account_purge_cannot_recreate_relay_rows(
        self,
        relay: Relay,
        service: AgentRelayService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        authenticated = Event()
        resume = Event()
        original_apply = service._apply_authenticated_event

        def paused_apply(connection: AgentConnectionDocument, event: Any) -> None:
            authenticated.set()
            assert resume.wait(timeout=5)
            original_apply(connection, event)

        monkeypatch.setattr(service, "_apply_authenticated_event", paused_apply)
        failures: list[BaseException] = []

        def ingest() -> None:
            try:
                relay.emit(relay.event("evt_purge_race", "running", 1))
            except BaseException as exc:  # captured for deterministic thread assertion
                failures.append(exc)

        contender = Thread(target=ingest)
        contender.start()
        assert authenticated.wait(timeout=5)
        service.delete_all_for_owner(owner_id=OWNER)
        resume.set()
        contender.join(timeout=5)

        assert len(failures) == 1
        assert isinstance(failures[0], EventRejected)
        assert failures[0].code == "connection_scope_changed"
        assert service.list_connections(owner_id=OWNER) == []
        assert service.list_audit(owner_id=OWNER) == []
        assert service.agent_repo.export_owner_data(
            owner_id=OWNER, now=relay.clock.now
        ) == {
            "connections": [],
            "runs": [],
            "events": [],
            "commands": [],
            "audit": [],
        }


class TestAudit:
    def test_the_audit_trail_records_actions_without_content_or_secrets(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """FR-017: IDs, outcomes, and timings only."""

        relay.emit(relay.event("evt_1", "running", 1, progress="Cloning the repo"))

        entries = service.list_audit(owner_id=OWNER)
        actions = {entry.action for entry in entries}
        assert {"connection_created", "connection_tested", "run_dispatched"} <= actions

        serialized = json.dumps([entry.model_dump(mode="json") for entry in entries])
        assert "super-secret-token" not in serialized
        assert "Cloning the repo" not in serialized
        assert relay.secret not in serialized

    def test_pre_authentication_rejections_do_not_create_durable_audit_rows(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        before = len(service.list_audit(owner_id=OWNER))

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_1", "running", 1), secret="wrong")

        assert len(service.list_audit(owner_id=OWNER)) == before

    def test_pre_authentication_rejection_floods_are_bounded_and_valid_events_continue(
        self, relay: Relay, service: AgentRelayService, clock: Clock
    ) -> None:
        before = len(service.list_audit(owner_id=OWNER))
        body = json.dumps(relay.event("evt_stale", "running", 1)).encode("utf-8")
        stale = int((clock.now - timedelta(hours=2)).timestamp())

        for index in range(20):
            with pytest.raises(EventRejected):
                relay.emit(
                    relay.event(f"evt_bad_{index}", "running", 1), secret="wrong"
                )
            with pytest.raises(EventRejected):
                service.ingest_event(
                    raw_body=body,
                    connection_id=relay.connection_id,
                    timestamp=str(stale),
                    signature=sign(relay.secret, stale, body),
                )

        assert len(service.list_audit(owner_id=OWNER)) == before
        accepted = relay.emit(relay.event("evt_valid", "running", 1))
        assert accepted.accepted is True

        current = service.get_connection(relay.connection_id, owner_id=OWNER)
        service.disconnect_connection(
            relay.connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-disconnect-audit-flood",
            reauthenticated=True,
        )
        after_disconnect = len(service.list_audit(owner_id=OWNER))
        for index in range(20):
            with pytest.raises(EventRejected):
                relay.emit(relay.event(f"evt_disconnected_{index}", "running", 2))

        assert len(service.list_audit(owner_id=OWNER)) == after_disconnect

        replacement = service.create_connection(
            create_request(name="Replacement"),
            owner_id=OWNER,
            idempotency_key="idem-create-after-flood",
            reauthenticated=True,
        )
        make_ready(service, replacement.id)
        replacement_run = dispatch(
            service,
            replacement.id,
            task_id="task_2",
            key="idem-dispatch-after-flood",
        )
        body = json.dumps(
            {
                "protocol_version": PROTOCOL_VERSION,
                "connection_id": replacement.id,
                "event_id": "evt_after_flood",
                "run_id": replacement_run.id,
                "type": "running",
                "run_version": 1,
            }
        ).encode("utf-8")
        timestamp = int(clock.now.timestamp())
        accepted = service.ingest_event(
            raw_body=body,
            connection_id=replacement.id,
            timestamp=str(timestamp),
            signature=sign(
                replacement.inbound_signing_secret,
                timestamp,
                body,
            ),
        )
        assert accepted.accepted is True

    def test_authenticated_semantic_rejection_audit_is_fixed_cardinality(
        self, relay: Relay, service: AgentRelayService, clock: Clock
    ) -> None:
        before = len(service.list_audit(owner_id=OWNER))
        timestamp = int(clock.now.timestamp())

        for index in range(20):
            body = json.dumps(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "connection_id": relay.connection_id,
                    "event_id": f"evt_invalid_{index}",
                }
            ).encode("utf-8")
            with pytest.raises(EventRejected) as rejected:
                service.ingest_event(
                    raw_body=body,
                    connection_id=relay.connection_id,
                    timestamp=str(timestamp),
                    signature=sign(relay.secret, timestamp, body),
                )
            assert rejected.value.code == "envelope_invalid"

        entries = service.list_audit(owner_id=OWNER)
        assert len(entries) == before + 1
        rejection = next(entry for entry in entries if entry.action == "event_rejected")
        assert rejection.outcome == "envelope_invalid"
        assert rejection.connection_id == relay.connection_id
        assert rejection.run_id is None
        assert rejection.correlation_id is None
        serialized = json.dumps(rejection.model_dump(mode="json"))
        assert "evt_invalid_" not in serialized

        mismatch_body = json.dumps(
            {
                "protocol_version": PROTOCOL_VERSION,
                "connection_id": "agentconn_other",
                "event_id": "evt_attacker_controlled",
                "run_id": "agentrun_attacker_controlled",
                "type": "running",
                "run_version": 1,
            }
        ).encode("utf-8")
        with pytest.raises(EventRejected) as rejected:
            service.ingest_event(
                raw_body=mismatch_body,
                connection_id=relay.connection_id,
                timestamp=str(timestamp),
                signature=sign(relay.secret, timestamp, mismatch_body),
            )
        assert rejected.value.code == "connection_mismatch"

        entries = service.list_audit(owner_id=OWNER)
        assert len(entries) == before + 2
        assert {
            entry.outcome for entry in entries if entry.action == "event_rejected"
        } == {
            "connection_mismatch",
            "envelope_invalid",
        }
        serialized = json.dumps(
            [
                entry.model_dump(mode="json")
                for entry in entries
                if entry.action == "event_rejected"
            ]
        )
        assert "evt_attacker_controlled" not in serialized
        assert "agentrun_attacker_controlled" not in serialized

        accepted = relay.emit(relay.event("evt_valid_after_auth_flood", "running", 1))
        assert accepted.accepted is True

        for index in range(5):
            with pytest.raises(EventRejected) as rejected:
                relay.emit(relay.event(f"evt_stale_{index}", "running", 1))
            assert rejected.value.code == "run_version_not_newer"

        rejection_entries = [
            entry
            for entry in service.list_audit(owner_id=OWNER)
            if entry.action == "event_rejected"
        ]
        assert len(rejection_entries) == 3
        assert {entry.outcome for entry in rejection_entries} == {
            "connection_mismatch",
            "envelope_invalid",
            "run_version_not_newer",
        }


class TestSecretHandling:
    def test_no_service_response_can_ever_carry_the_stored_credential(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """AC-019: the saved secret is unreachable through every read path."""

        relay.emit(relay.event("evt_1", "completed", 1, result="Done"))

        payloads = [
            json.dumps(
                service.get_connection(relay.connection_id, owner_id=OWNER).model_dump(
                    mode="json"
                )
            ),
            json.dumps(
                [
                    c.model_dump(mode="json")
                    for c in service.list_connections(owner_id=OWNER)
                ]
            ),
            json.dumps(
                service.get_run(relay.run.id, owner_id=OWNER).model_dump(mode="json")
            ),
            json.dumps(
                [e.model_dump(mode="json") for e in service.list_audit(owner_id=OWNER)]
            ),
        ]

        for payload in payloads:
            assert "super-secret-token" not in payload
            assert relay.secret not in payload

    def test_the_credential_is_not_stored_in_plaintext_on_disk(
        self, tmp_path: Path, service: AgentRelayService
    ) -> None:
        """FR-003: a disk leak yields ciphertext, not a usable token."""

        connect(service)

        database = (tmp_path / "agents.sqlite3").read_bytes()
        assert b"super-secret-token" not in database

    def test_a_connection_row_copied_to_another_owner_cannot_be_used(
        self, tmp_path: Path, connector: FakeConnector, clock: Clock
    ) -> None:
        """The credential's AAD names the owner, so a copied row is inert.

        Owner isolation is enforced by every query, but a row that leaks between
        owners — a bad restore, a support script, a future non-unique ID — must
        not additionally hand the second owner a working credential.
        """

        repo = AgentRepository(tmp_path)
        service = build_service(repo, connector, clock)
        connection_id = connect(service)
        stolen = repo.get_connection(connection_id, owner_id=OWNER)

        repo.create_connection(stolen.model_copy(update={"owner_id": OTHER_OWNER}))

        with pytest.raises(ValidationFailure) as rejected:
            service.test_connection(connection_id, owner_id=OTHER_OWNER)
        assert rejected.value.detail == {"reason": "credential_unreadable"}
        assert connector.tests == []

    def test_a_signing_secret_copied_to_another_connection_cannot_verify(
        self, relay: Relay, service: AgentRelayService, tmp_path: Path
    ) -> None:
        """The signing secret's AAD names its connection, so it cannot move."""

        repo = AgentRepository(tmp_path)
        source = repo.get_connection(relay.connection_id, owner_id=OWNER)
        second = service.create_connection(
            create_request(name="Second agent"),
            owner_id=OWNER,
            idempotency_key="idem-second",
            reauthenticated=True,
        )
        target = repo.get_connection(second.id, owner_id=OWNER)
        repo.save_connection(
            target.model_copy(update={"inbound_secret": source.inbound_secret})
        )

        body = json.dumps(
            relay.event("evt_1", "running", 1, connection_id=second.id)
        ).encode("utf-8")
        timestamp = int(relay.clock.now.timestamp())

        with pytest.raises(EventRejected) as rejected:
            service.ingest_event(
                raw_body=body,
                connection_id=second.id,
                timestamp=str(timestamp),
                signature=sign(relay.secret, timestamp, body),
            )
        assert rejected.value.code == "signing_secret_unreadable"

    def test_a_ciphertext_that_cannot_be_opened_fails_closed(
        self, tmp_path: Path, connector: FakeConnector, clock: Clock
    ) -> None:
        """Losing key material blocks use rather than sending an empty header."""

        repo = AgentRepository(tmp_path)
        original = build_service(repo, connector, clock)
        connection_id = connect(original)

        rekeyed = build_service(repo, connector, clock, key=b"\x09" * 32)

        with pytest.raises(ValidationFailure):
            rekeyed.test_connection(connection_id, owner_id=OWNER)


class TestSigningSecretRotation:
    """Recovering from a lost create response without weakening FR-003.

    The inbound signing secret is shown once. If that one response is lost — a
    dropped connection, a closed sheet, a crashed app — the owner has a
    connection they cannot configure and no way back. Rotation is that way back:
    a re-authenticated, revision-checked, idempotent replacement that invalidates
    the old secret the moment it is issued.
    """

    def rotate(
        self,
        service: AgentRelayService,
        connection_id: str,
        *,
        key: str = "idem-signing",
        revision: int | None = None,
        owner_id: str = OWNER,
        reauthenticated: bool = True,
    ) -> Any:
        current = revision
        if current is None:
            current = service.get_connection(connection_id, owner_id=OWNER).revision
        return service.rotate_signing_secret(
            connection_id,
            AgentConnectionRotateSigningSecretRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current,
            ),
            owner_id=owner_id,
            idempotency_key=key,
            reauthenticated=reauthenticated,
        )

    def test_event_authenticated_before_concurrent_rotation_cannot_mutate(
        self,
        relay: Relay,
        service: AgentRelayService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """S1 authentication cannot cross an S2 rotation's owner lock."""

        authenticated = Event()
        resume = Event()
        original_apply = service._apply_authenticated_event

        def paused_apply(connection: AgentConnectionDocument, event: Any) -> None:
            authenticated.set()
            assert resume.wait(timeout=5)
            original_apply(connection, event)

        monkeypatch.setattr(service, "_apply_authenticated_event", paused_apply)
        payload = relay.event("evt_rotation_race", "running", 1, progress="old secret")
        failures: list[BaseException] = []

        def ingest_old_secret() -> None:
            try:
                relay.emit(payload, secret=relay.secret)
            except BaseException as exc:  # captured for deterministic thread assertion
                failures.append(exc)

        contender = Thread(target=ingest_old_secret)
        contender.start()
        assert authenticated.wait(timeout=5)
        rotated = self.rotate(service, relay.connection_id, key="idem-race-rotation")
        resume.set()
        contender.join(timeout=5)

        assert len(failures) == 1
        assert isinstance(failures[0], EventRejected)
        assert failures[0].code == "connection_scope_changed"
        assert relay.projection().reported_state is None
        assert service.agent_repo.list_events(relay.run.id, owner_id=OWNER) == []

        relay.emit(payload, secret=rotated.inbound_signing_secret)
        assert relay.projection().progress_text == "old secret"

    def test_rotation_issues_a_new_secret_and_kills_the_old_one(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """The replacement works immediately; the old one stops working."""

        rotated = self.rotate(service, relay.connection_id)

        assert rotated.inbound_signing_secret
        assert rotated.inbound_signing_secret != relay.secret

        with pytest.raises(EventRejected):
            relay.emit(relay.event("evt_old", "running", 1), secret=relay.secret)

        relay.emit(
            relay.event("evt_new", "running", 1, progress="Cloning the repo"),
            secret=rotated.inbound_signing_secret,
        )
        assert relay.projection().progress_text == "Cloning the repo"

    def test_a_lost_response_is_recovered_by_replaying_the_same_key(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """The whole point: a retry returns the secret, never a blank success.

        Returning an empty string here would be the worst of both worlds — the
        old secret is already dead, and the caller is told "ok" while holding
        nothing it can configure its agent with.
        """

        revision = service.get_connection(relay.connection_id, owner_id=OWNER).revision
        first = self.rotate(service, relay.connection_id, revision=revision)

        replay = self.rotate(service, relay.connection_id, revision=revision)

        assert replay.inbound_signing_secret == first.inbound_signing_secret
        assert replay.revision == first.revision
        relay.emit(
            relay.event("evt_1", "running", 1),
            secret=replay.inbound_signing_secret,
        )

    def test_signing_secret_replay_requires_reauthentication(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        revision = service.get_connection(relay.connection_id, owner_id=OWNER).revision
        first = self.rotate(service, relay.connection_id, revision=revision)

        with pytest.raises(ValidationFailure) as refused:
            self.rotate(
                service,
                relay.connection_id,
                revision=revision,
                reauthenticated=False,
            )

        assert refused.value.detail == {"reason": "reauthentication_required"}
        assert first.inbound_signing_secret not in str(refused.value)

    def test_a_replay_does_not_rotate_a_second_time(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """One key, one rotation: the recovered secret is still the live one."""

        revision = service.get_connection(relay.connection_id, owner_id=OWNER).revision
        first = self.rotate(service, relay.connection_id, revision=revision)
        self.rotate(service, relay.connection_id, revision=revision)

        relay.emit(
            relay.event("evt_1", "running", 1),
            secret=first.inbound_signing_secret,
        )
        assert relay.projection().reported_state == "running"

    def test_a_fresh_key_rotates_again_and_retires_the_previous_replacement(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """A genuinely new request is a new rotation, not a replay."""

        first = self.rotate(service, relay.connection_id, key="idem-a")
        second = self.rotate(service, relay.connection_id, key="idem-b")

        assert second.inbound_signing_secret != first.inbound_signing_secret
        with pytest.raises(EventRejected):
            relay.emit(
                relay.event("evt_1", "running", 1),
                secret=first.inbound_signing_secret,
            )

    def test_a_replay_of_a_superseded_rotation_never_returns_the_dead_secret(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """Key A, then key B, then A again: A's receipt describes a dead secret.

        A receipt outlives the rotation that wrote it, so once a later rotation
        has installed a different secret the earlier one verifies nothing.
        Handing it back on a replay would be the worst possible answer — a
        success-shaped response carrying a secret that cannot sign a single
        report — so the stale replay is refused instead.
        """

        revision = service.get_connection(relay.connection_id, owner_id=OWNER).revision
        first = self.rotate(
            service, relay.connection_id, key="idem-a", revision=revision
        )
        second = self.rotate(service, relay.connection_id, key="idem-b")

        with pytest.raises(ConflictError) as refused:
            self.rotate(service, relay.connection_id, key="idem-a", revision=revision)

        assert first.inbound_signing_secret not in str(refused.value)
        relay.emit(
            relay.event("evt_1", "running", 1),
            secret=second.inbound_signing_secret,
        )
        assert relay.projection().reported_state == "running"

    def test_a_replay_still_recovers_after_an_unrelated_connection_change(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """What retires a receipt is a newer secret, not any newer revision.

        A connection test bumps the revision without touching the inbound
        secret, so the replacement this receipt names is still the live one and
        the lost-response retry must still deliver it.
        """

        revision = service.get_connection(relay.connection_id, owner_id=OWNER).revision
        first = self.rotate(
            service, relay.connection_id, key="idem-a", revision=revision
        )
        service.test_connection(relay.connection_id, owner_id=OWNER)

        replay = self.rotate(
            service, relay.connection_id, key="idem-a", revision=revision
        )

        assert replay.inbound_signing_secret == first.inbound_signing_secret
        relay.emit(
            relay.event("evt_1", "running", 1),
            secret=replay.inbound_signing_secret,
        )

    def test_rotation_requires_reauthentication(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """FR-003: replacing credential material is a re-authenticated action."""

        with pytest.raises(ValidationFailure) as refused:
            self.rotate(service, relay.connection_id, reauthenticated=False)

        assert refused.value.detail == {"reason": "reauthentication_required"}
        relay.emit(relay.event("evt_1", "running", 1))

    def test_a_stale_expected_revision_is_a_conflict(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """The owner has to be acting on the connection they last saw."""

        current = service.get_connection(relay.connection_id, owner_id=OWNER).revision

        with pytest.raises(ConflictError):
            self.rotate(service, relay.connection_id, revision=current - 1)

        relay.emit(relay.event("evt_1", "running", 1))

    def test_a_disconnected_connection_cannot_be_given_a_new_secret(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """FR-016: disconnect destroys credentials; it does not mint them."""

        current = service.get_connection(relay.connection_id, owner_id=OWNER)
        service.disconnect_connection(
            relay.connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-disconnect",
            reauthenticated=True,
        )

        with pytest.raises(ValidationFailure) as refused:
            self.rotate(service, relay.connection_id, revision=current.revision + 1)

        assert refused.value.detail == {"reason": "connection_disconnected"}

    def test_another_owner_cannot_rotate_the_secret(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """Owner isolation, including the shape of the refusal."""

        with pytest.raises(NotFoundError):
            self.rotate(service, relay.connection_id, owner_id=OTHER_OWNER)

    def test_no_ordinary_read_exposes_the_replacement(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """FR-003: the secret is returned by rotation and by nothing else."""

        rotated = self.rotate(service, relay.connection_id)
        secret = rotated.inbound_signing_secret

        reads = [
            json.dumps(
                service.get_connection(relay.connection_id, owner_id=OWNER).model_dump(
                    mode="json"
                )
            ),
            json.dumps(
                [
                    c.model_dump(mode="json")
                    for c in service.list_connections(owner_id=OWNER)
                ]
            ),
            json.dumps(
                service.get_run(relay.run.id, owner_id=OWNER).model_dump(mode="json")
            ),
            json.dumps(
                [e.model_dump(mode="json") for e in service.list_audit(owner_id=OWNER)]
            ),
        ]

        for payload in reads:
            assert secret not in payload
        assert "inbound_signing_secret" not in reads[0]

    def test_the_recovery_copy_is_never_stored_in_plaintext(
        self, relay: Relay, service: AgentRelayService, tmp_path: Path
    ) -> None:
        """The retry copy is sealed, so the database still holds no secret."""

        rotated = self.rotate(service, relay.connection_id)

        database = (tmp_path / "agents.sqlite3").read_bytes()
        assert rotated.inbound_signing_secret.encode("utf-8") not in database

    def test_rotation_is_audited_without_the_secret(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        """FR-017: IDs and outcome only."""

        rotated = self.rotate(service, relay.connection_id)

        entries = service.list_audit(owner_id=OWNER)
        assert any(entry.action == "signing_secret_rotated" for entry in entries)
        serialized = json.dumps([entry.model_dump(mode="json") for entry in entries])
        assert rotated.inbound_signing_secret not in serialized


class TestRelayFailureRecoveryEdges:
    """Release-risk failures stay recoverable and fail closed without leakage."""

    def test_invalid_header_migration_leaves_unparseable_rows_untouched(self) -> None:
        database = sqlite3.connect(":memory:")
        database.row_factory = sqlite3.Row
        database.execute(
            "CREATE TABLE agent_connections "
            "(owner_id TEXT, id TEXT, status TEXT, payload TEXT)"
        )
        database.executemany(
            "INSERT INTO agent_connections VALUES (?, ?, ?, ?)",
            [
                (OWNER, "malformed", "ready", "not-json"),
                (OWNER, "wrong-shape", "ready", "[]"),
            ],
        )

        AgentRepository._migrate_legacy_invalid_header_connections(database)

        assert [
            row[0]
            for row in database.execute(
                "SELECT payload FROM agent_connections ORDER BY id"
            )
        ] == ["not-json", "[]"]
        database.close()

    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    @pytest.mark.parametrize(
        "window", ["reservation", "reserved_before_marker", "marker_before_connector"]
    )
    def test_command_crash_windows_preserve_at_most_once_recovery(
        self,
        tmp_path: Path,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
        operation: str,
        window: str,
    ) -> None:
        connector = FakeConnector()
        service = build_service(AgentRepository(tmp_path), connector, clock)
        key = f"idem-window-{operation}-{window}"
        if operation == "start":
            connection_id = connect(service)
            make_ready(service, connection_id)
            payload: Any = review(service, connection_id)

            def invoke() -> Any:
                return service.dispatch_run(
                    "task_1", payload, owner_id=OWNER, idempotency_key=key
                )

        else:
            relay = Relay(service, clock)
            connector.starts.clear()
            connector.commands.clear()
            if operation == "reply":
                relay.emit(relay.event("evt_window_blocked", "blocked", 1))
                payload = AgentReplyRequest(
                    message="Use staging.",
                    expected_revision=relay.projection().revision,
                )

                def invoke() -> Any:
                    return service.reply_to_run(
                        relay.run.id, payload, owner_id=OWNER, idempotency_key=key
                    )

            else:

                def invoke() -> Any:
                    return service.cancel_run(
                        relay.run.id, owner_id=OWNER, idempotency_key=key
                    )

        if window == "reservation":
            original_save_idempotency = service.agent_repo.save_idempotency

            def fail_reservation(*, owner_id: str, record: Any) -> None:
                if not record.completed and not record.delivery_attempted:
                    raise RuntimeError("reservation write failed")
                original_save_idempotency(owner_id=owner_id, record=record)

            monkeypatch.setattr(
                service.agent_repo, "save_idempotency", fail_reservation
            )
            expected = "reservation write failed"
        elif window == "reserved_before_marker":
            original_remember = service._remember

            def fail_attempted_marker(**kwargs: Any) -> None:
                if kwargs.get("delivery_attempted") is True:
                    raise RuntimeError("attempted marker write failed")
                original_remember(**kwargs)

            monkeypatch.setattr(service, "_remember", fail_attempted_marker)
            expected = "attempted marker write failed"
        else:
            original_begin_delivery_attempt = service._begin_delivery_attempt

            def fail_after_marker(**kwargs: Any) -> None:
                original_begin_delivery_attempt(**kwargs)
                raise RuntimeError("marker_before_connector")

            monkeypatch.setattr(service, "_begin_delivery_attempt", fail_after_marker)
            expected = "marker_before_connector"

        with pytest.raises(RuntimeError, match=expected):
            invoke()
        assert connector.starts == []
        assert connector.commands == []

        key_hash = service._key_fingerprint(OWNER, key)
        with sqlite3.connect(tmp_path / "agents.sqlite3") as database:
            durable_row = database.execute(
                "SELECT command_id, completed, delivery_attempted "
                "FROM agent_idempotency WHERE owner_id = ? AND key_hash = ?",
                (OWNER, key_hash),
            ).fetchone()
        if window == "reservation":
            assert durable_row is None
        elif window == "reserved_before_marker":
            assert durable_row is not None
            assert durable_row[0] is not None
            assert durable_row[1:] == (0, 0)
        else:
            assert durable_row is not None
            assert durable_row[0] is not None
            assert durable_row[1:] == (0, 1)

        service = build_service(AgentRepository(tmp_path), connector, clock)
        recovered = invoke()

        external_calls = (
            connector.starts if operation == "start" else connector.commands
        )
        if window == "marker_before_connector":
            assert external_calls == []
            command = next(
                item for item in recovered.commands if item.kind == operation
            )
            assert command.delivery == "unconfirmed"
        else:
            assert len(external_calls) == 1
            wire_id = (
                external_calls[0]["run_id"]
                if operation == "start"
                else external_calls[0]["command_id"]
            )
            projected_id = (
                recovered.id
                if operation == "start"
                else next(
                    item.id for item in recovered.commands if item.kind == operation
                )
            )
            assert projected_id == wire_id

    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    @pytest.mark.parametrize("delivery_column_exists", [False, True])
    def test_legacy_incomplete_command_rows_migrate_as_ambiguous_without_redelivery(
        self,
        tmp_path: Path,
        clock: Clock,
        operation: str,
        delivery_column_exists: bool,
    ) -> None:
        connector = FakeConnector()
        service = build_service(AgentRepository(tmp_path), connector, clock)
        key = f"idem-legacy-incomplete-{operation}"
        if operation == "start":
            connection_id = connect(service)
            make_ready(service, connection_id)
            payload: Any = review(service, connection_id)
            resource_id = service.agent_repo.list_runs_for_task(
                "task_1", owner_id=OWNER
            )[0].id
            command = "dispatch_run"
            canonical = service._canonical_request(command, payload, target="task_1")

            def retry() -> Any:
                return service.dispatch_run(
                    "task_1", payload, owner_id=OWNER, idempotency_key=key
                )

            response_body: dict[str, object] = {"id": resource_id}
        else:
            relay = Relay(service, clock)
            resource_id = relay.run.id
            if operation == "reply":
                relay.emit(
                    relay.event(
                        "evt_legacy_blocked",
                        "blocked",
                        1,
                        question="Which environment?",
                    )
                )
                payload = AgentReplyRequest(
                    message="Use staging.",
                    expected_revision=relay.projection().revision,
                )
                command = "reply_to_run"
                canonical = service._canonical_request(
                    command, payload, target=resource_id
                )

                def retry() -> Any:
                    return service.reply_to_run(
                        resource_id, payload, owner_id=OWNER, idempotency_key=key
                    )

                response_body = {"id": resource_id}
            else:
                command = "cancel_run"
                canonical = service._canonical_request(command, {}, target=resource_id)

                def retry() -> Any:
                    return service.cancel_run(
                        resource_id, owner_id=OWNER, idempotency_key=key
                    )

                connection = service.agent_repo.get_connection(
                    relay.connection_id, owner_id=OWNER
                )
                response_body = {
                    "id": resource_id,
                    "connection_revision": connection.revision,
                }

        key_hash = service._key_fingerprint(OWNER, key)
        command_id = f"agentcmd_legacy_{operation}"
        request_hash = service.secret_box.fingerprint(canonical)
        database_path = tmp_path / "agents.sqlite3"
        delivery_column = (
            "delivery_attempted INTEGER NOT NULL DEFAULT 0,"
            if delivery_column_exists
            else ""
        )
        with sqlite3.connect(database_path) as database:
            database.executescript(f"""
                ALTER TABLE agent_idempotency RENAME TO agent_idempotency_new;
                CREATE TABLE agent_idempotency (
                    owner_id TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    command TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    command_id TEXT,
                    {delivery_column}
                    completed INTEGER NOT NULL DEFAULT 1,
                    response_body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (owner_id, key_hash)
                );
                DROP TABLE agent_idempotency_new;
                """)
            database.execute(
                "DELETE FROM agent_schema_migrations "
                "WHERE name = 'delivery_attempted_backfill_v1'"
            )
            database.execute(
                """
                INSERT INTO agent_idempotency (
                    owner_id, key_hash, command, request_hash, resource_id,
                    command_id, completed, response_body, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    OWNER,
                    key_hash,
                    command,
                    request_hash,
                    resource_id,
                    command_id,
                    json.dumps(response_body),
                    clock.now.isoformat(),
                ),
            )

        connector.starts.clear()
        connector.commands.clear()
        restarted = build_service(AgentRepository(tmp_path), connector, clock)
        service = restarted
        recovered = retry()

        assert connector.starts == []
        assert connector.commands == []
        assert [item.id for item in recovered.commands if item.id == command_id] == [
            command_id
        ]
        with sqlite3.connect(database_path) as database:
            row = database.execute(
                "SELECT completed, delivery_attempted FROM agent_idempotency "
                "WHERE owner_id = ? AND key_hash = ?",
                (OWNER, key_hash),
            ).fetchone()
        assert row == (1, 1)

    def test_malformed_legacy_revision_is_safely_coerced_during_header_quarantine(
        self,
        relay: Relay,
        tmp_path: Path,
        clock: Clock,
    ) -> None:
        connection = relay.service.agent_repo.get_connection(
            relay.connection_id, owner_id=OWNER
        )
        legacy_payload = connection.model_dump(mode="json")
        legacy_payload.update(
            auth_header_name="Authorization",
            revision="not-an-int",
            credential="plaintext-legacy-secret",
        )
        database_path = tmp_path / "agents.sqlite3"
        with sqlite3.connect(database_path) as database:
            database.execute(
                "UPDATE agent_connections SET payload = ? WHERE owner_id = ? AND id = ?",
                (json.dumps(legacy_payload), OWNER, relay.connection_id),
            )

        restarted = build_service(AgentRepository(tmp_path), FakeConnector(), clock)
        migrated = restarted.agent_repo.get_connection(
            relay.connection_id, owner_id=OWNER
        )
        assert migrated.auth_header_name == "X-Agent-Key"
        assert migrated.credential is None
        assert migrated.status == "untested"
        assert migrated.revision == 2
        assert migrated.updated_at >= connection.updated_at

        restarted_again = build_service(
            AgentRepository(tmp_path), FakeConnector(), clock
        )
        persisted = restarted_again.agent_repo.get_connection(
            relay.connection_id, owner_id=OWNER
        )
        assert persisted.revision == migrated.revision
        with sqlite3.connect(database_path) as database:
            stored_payload = database.execute(
                "SELECT payload FROM agent_connections WHERE owner_id = ? AND id = ?",
                (OWNER, relay.connection_id),
            ).fetchone()[0]
        assert "plaintext-legacy-secret" not in stored_payload

    @pytest.mark.parametrize(
        "legacy_header",
        [
            "Authorization",
            "aUtHoRiZaTiOn",
            "Content-Type",
            "Host",
            "X Bad",
            "TE",
            123,
            None,
            ["X-Agent-Key"],
        ],
    )
    def test_legacy_invalid_header_connection_is_migrated_to_safe_readable_state(
        self,
        relay: Relay,
        tmp_path: Path,
        clock: Clock,
        legacy_header: object,
    ) -> None:
        connection = relay.service.agent_repo.get_connection(
            relay.connection_id, owner_id=OWNER
        )
        legacy_payload = connection.model_dump(mode="json")
        legacy_payload["auth_header_name"] = legacy_header
        with sqlite3.connect(tmp_path / "agents.sqlite3") as database:
            database.execute(
                "UPDATE agent_connections SET payload = ? WHERE owner_id = ? AND id = ?",
                (json.dumps(legacy_payload), OWNER, relay.connection_id),
            )

        connector = FakeConnector()
        restarted = build_service(AgentRepository(tmp_path), connector, clock)
        listed = restarted.list_connections(owner_id=OWNER)
        run = restarted.get_run(relay.run.id, owner_id=OWNER)
        migrated = restarted.agent_repo.get_connection(
            relay.connection_id, owner_id=OWNER
        )

        assert [item.id for item in listed] == [relay.connection_id]
        assert listed[0].auth_header_name == "X-Agent-Key"
        assert listed[0].status == "untested"
        assert (
            listed[0].last_test_error_code
            == "legacy_invalid_auth_header_requires_reconfiguration"
        )
        assert migrated.credential is None
        assert migrated.revision == connection.revision + 1
        assert migrated.updated_at > connection.updated_at
        assert run.id == relay.run.id
        assert run.connection_id == relay.connection_id
        with pytest.raises(ValidationFailure) as refused:
            restarted.test_connection(relay.connection_id, owner_id=OWNER)
        assert refused.value.detail == {"reason": "credential_missing"}
        with pytest.raises(ValidationFailure):
            dispatch(
                restarted,
                relay.connection_id,
                task_id="task_2",
                key=f"idem-legacy-invalid-header-{legacy_header}",
            )
        assert connector.tests == []
        assert connector.starts == []

        restarted_again = build_service(
            AgentRepository(tmp_path), FakeConnector(), clock
        )
        persisted = restarted_again.get_connection(relay.connection_id, owner_id=OWNER)
        assert persisted.auth_header_name == "X-Agent-Key"
        assert persisted.last_test_error_code == (
            "legacy_invalid_auth_header_requires_reconfiguration"
        )

    def test_retry_after_a_post_send_save_failure_reconciles_the_reserved_command_id(
        self,
        relay: Relay,
        service: AgentRelayService,
        connector: FakeConnector,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        payload = AgentReplyRequest(
            message="Use staging.", expected_revision=relay.projection().revision
        )
        save_command = service.agent_repo.save_command
        failed_once = False

        def fail_after_delivery(command: Any) -> None:
            nonlocal failed_once
            if not failed_once:
                failed_once = True
                raise RuntimeError("simulated post-delivery storage outage")
            save_command(command)

        monkeypatch.setattr(service.agent_repo, "save_command", fail_after_delivery)
        with pytest.raises(RuntimeError, match="post-delivery"):
            service.reply_to_run(
                relay.run.id,
                payload,
                owner_id=OWNER,
                idempotency_key="idem-crash-reply",
            )

        recovered = service.reply_to_run(
            relay.run.id,
            payload,
            owner_id=OWNER,
            idempotency_key="idem-crash-reply",
        )

        assert len(connector.commands) == 1
        command_id = connector.commands[0]["command_id"]
        command = next(item for item in recovered.commands if item.id == command_id)
        assert command.delivery == "unconfirmed"
        assert [
            command.body for command in recovered.commands if command.kind == "reply"
        ] == ["Use staging."]

    def test_reply_retry_after_post_delivery_failure_reconciles_without_redelivery_after_terminal_callback(
        self,
        relay: Relay,
        service: AgentRelayService,
        connector: FakeConnector,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        payload = AgentReplyRequest(
            message="Use staging.", expected_revision=relay.projection().revision
        )
        save_command = service.agent_repo.save_command
        failed_once = False

        def fail_after_delivery(command: Any) -> None:
            nonlocal failed_once
            if not failed_once:
                failed_once = True
                raise RuntimeError("simulated post-delivery storage outage")
            save_command(command)

        monkeypatch.setattr(service.agent_repo, "save_command", fail_after_delivery)
        with pytest.raises(RuntimeError, match="post-delivery"):
            service.reply_to_run(
                relay.run.id,
                payload,
                owner_id=OWNER,
                idempotency_key="idem-terminal-crash-reply",
            )
        original_command_id = connector.commands[0]["command_id"]
        relay.emit(relay.event("evt_2", "completed", 2, result="Already done"))

        recovered = service.reply_to_run(
            relay.run.id,
            payload,
            owner_id=OWNER,
            idempotency_key="idem-terminal-crash-reply",
        )
        replayed = service.reply_to_run(
            relay.run.id,
            payload,
            owner_id=OWNER,
            idempotency_key="idem-terminal-crash-reply",
        )

        assert len(connector.commands) == 1
        assert recovered == replayed
        assert recovered.reported_state == "completed"
        assert recovered.result_text == "Already done"
        command = next(
            item for item in recovered.commands if item.id == original_command_id
        )
        assert command.delivery == "unconfirmed"
        assert command.body == "Use staging."

    def test_cancel_retry_after_post_delivery_failure_reconciles_without_redelivery_after_terminal_callback(
        self,
        relay: Relay,
        service: AgentRelayService,
        connector: FakeConnector,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        save_command = service.agent_repo.save_command
        failed_once = False

        def fail_after_delivery(command: Any) -> None:
            nonlocal failed_once
            if not failed_once:
                failed_once = True
                raise RuntimeError("simulated post-delivery cancel outage")
            save_command(command)

        monkeypatch.setattr(service.agent_repo, "save_command", fail_after_delivery)
        with pytest.raises(RuntimeError, match="cancel outage"):
            service.cancel_run(
                relay.run.id,
                owner_id=OWNER,
                idempotency_key="idem-terminal-crash-cancel",
            )
        original_command_id = connector.commands[0]["command_id"]
        relay.emit(relay.event("evt_done", "completed", 1, result="Finished"))

        recovered = service.cancel_run(
            relay.run.id,
            owner_id=OWNER,
            idempotency_key="idem-terminal-crash-cancel",
        )

        assert len(connector.commands) == 1
        assert recovered.reported_state == "completed"
        assert recovered.cancel_requested is False
        command = next(
            item for item in recovered.commands if item.id == original_command_id
        )
        assert command.kind == "cancel"
        assert command.delivery == "unconfirmed"

    def test_cancel_retry_after_post_delivery_failure_preserves_nonterminal_cancellation_overlay(
        self,
        relay: Relay,
        service: AgentRelayService,
        connector: FakeConnector,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        save_command = service.agent_repo.save_command
        failed_once = False

        def fail_after_delivery(command: Any) -> None:
            nonlocal failed_once
            if not failed_once:
                failed_once = True
                raise RuntimeError("simulated post-delivery cancel outage")
            save_command(command)

        monkeypatch.setattr(service.agent_repo, "save_command", fail_after_delivery)
        with pytest.raises(RuntimeError, match="cancel outage"):
            service.cancel_run(
                relay.run.id,
                owner_id=OWNER,
                idempotency_key="idem-active-crash-cancel",
            )

        clock.advance(timedelta(minutes=1))
        callback_at = clock.now
        relay.emit(
            relay.event("evt_cancel_recovery", "running", 1, progress="Still working")
        )
        clock.advance(timedelta(minutes=1))
        recovery_at = clock.now

        recovered = service.cancel_run(
            relay.run.id,
            owner_id=OWNER,
            idempotency_key="idem-active-crash-cancel",
        )

        assert len(connector.commands) == 1
        assert recovered.reported_state == "running"
        assert recovered.progress_text == "Still working"
        assert recovered.cancel_requested is True
        persisted = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        assert persisted.updated_at >= callback_at
        assert persisted.updated_at == recovery_at
        command = next(item for item in recovered.commands if item.kind == "cancel")
        assert command.delivery == "unconfirmed"

    def test_start_retry_after_ambiguous_storage_failure_reuses_wire_identifiers(
        self,
        service: AgentRelayService,
        connector: FakeConnector,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connection_id = connect(service)
        make_ready(service, connection_id)
        confirmation = review(service, connection_id)
        save_command = service.agent_repo.save_command
        calls = 0

        def fail_final_delivery_merge(command: Any) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated ambiguous start storage outage")
            save_command(command)

        monkeypatch.setattr(
            service.agent_repo, "save_command", fail_final_delivery_merge
        )
        with pytest.raises(RuntimeError, match="ambiguous start"):
            service.dispatch_run(
                "task_1",
                confirmation,
                owner_id=OWNER,
                idempotency_key="idem-crash-start",
            )
        current_connection = service.get_connection(connection_id, owner_id=OWNER)
        service.disconnect_connection(
            connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current_connection.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-disconnect-after-start-crash",
            reauthenticated=True,
        )

        recovered = service.dispatch_run(
            "task_1",
            confirmation,
            owner_id=OWNER,
            idempotency_key="idem-crash-start",
        )

        assert len(connector.starts) == 1
        assert connector.starts[0]["run_id"] == recovered.id
        assert connector.starts[0]["idempotency_key"] == recovered.id
        assert (
            len([command for command in recovered.commands if command.kind == "start"])
            == 1
        )
        assert (
            next(
                command for command in recovered.commands if command.kind == "start"
            ).delivery
            == "unconfirmed"
        )

    def test_missing_stored_credential_refuses_network_use(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        connection_id = connect(service)
        connection = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        service.agent_repo.save_connection(
            connection.model_copy(update={"credential": None})
        )

        with pytest.raises(ValidationFailure) as refused:
            service.test_connection(connection_id, owner_id=OWNER)

        assert refused.value.detail == {"reason": "credential_missing"}
        assert connector.tests == []

    def test_disconnected_connection_cannot_be_tested(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        connection_id = connect(service)
        current = service.get_connection(connection_id, owner_id=OWNER)
        service.disconnect_connection(
            connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-disconnect-before-test",
            reauthenticated=True,
        )

        with pytest.raises(ValidationFailure) as refused:
            service.test_connection(connection_id, owner_id=OWNER)

        assert refused.value.detail == {"reason": "connection_disconnected"}
        assert connector.tests == []

    def test_credential_rotation_guards_and_replay_are_stable(
        self, service: AgentRelayService
    ) -> None:
        connection_id = connect(service)
        original = service.get_connection(connection_id, owner_id=OWNER)
        payload = AgentConnectionRotateRequest(
            credential="Bearer replacement",
            current_password="correct-horse-battery-staple",
            expected_revision=original.revision,
        )

        with pytest.raises(ValidationFailure) as refused:
            service.rotate_credential(
                connection_id,
                payload,
                owner_id=OWNER,
                idempotency_key="idem-rotate-no-reauth",
                reauthenticated=False,
            )
        assert refused.value.detail == {"reason": "reauthentication_required"}

        rotated = service.rotate_credential(
            connection_id,
            payload,
            owner_id=OWNER,
            idempotency_key="idem-rotate-replay",
            reauthenticated=True,
        )
        replayed = service.rotate_credential(
            connection_id,
            payload,
            owner_id=OWNER,
            idempotency_key="idem-rotate-replay",
            reauthenticated=True,
        )
        assert replayed == rotated

        disconnected_payload = AgentConnectionDisconnectRequest(
            current_password="correct-horse-battery-staple",
            expected_revision=rotated.revision,
        )
        service.disconnect_connection(
            connection_id,
            disconnected_payload,
            owner_id=OWNER,
            idempotency_key="idem-disconnect-after-rotate",
            reauthenticated=True,
        )
        with pytest.raises(ValidationFailure) as disconnected:
            service.rotate_credential(
                connection_id,
                AgentConnectionRotateRequest(
                    credential="Bearer impossible",
                    current_password="correct-horse-battery-staple",
                    expected_revision=rotated.revision + 1,
                ),
                owner_id=OWNER,
                idempotency_key="idem-rotate-disconnected",
                reauthenticated=True,
            )
        assert disconnected.value.detail == {"reason": "connection_disconnected"}

    def test_disconnect_replay_returns_the_same_projection(self, relay: Relay) -> None:
        current = relay.service.get_connection(relay.connection_id, owner_id=OWNER)
        payload = AgentConnectionDisconnectRequest(
            current_password="correct-horse-battery-staple",
            expected_revision=current.revision,
        )
        first = relay.service.disconnect_connection(
            relay.connection_id,
            payload,
            owner_id=OWNER,
            idempotency_key="idem-disconnect-replay",
            reauthenticated=True,
        )
        second = relay.service.disconnect_connection(
            relay.connection_id,
            payload,
            owner_id=OWNER,
            idempotency_key="idem-disconnect-replay",
            reauthenticated=True,
        )

        assert second == first
        assert second.status == "disconnected"

    def test_disconnect_marks_only_dispatched_nonterminal_runs(
        self, relay: Relay, service: AgentRelayService
    ) -> None:
        terminal = dispatch(
            service, relay.connection_id, task_id="task_2", key="idem-task-2"
        )
        relay.emit(
            relay.event("evt_done", "completed", 1, result="Done", run_id=terminal.id)
        )
        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=relay.connection_id),
            owner_id=OWNER,
        )
        current = service.get_connection(relay.connection_id, owner_id=OWNER)

        service.disconnect_connection(
            relay.connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-selective-disconnect",
            reauthenticated=True,
        )

        active = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        completed = service.agent_repo.get_run(terminal.id, owner_id=OWNER)
        reserved = service.agent_repo.get_run(preview.run_id, owner_id=OWNER)
        assert active.connection_disconnected_at is not None
        assert completed.connection_disconnected_at is None
        assert reserved.connection_disconnected_at is None

    def test_unverified_scope_requires_reauthentication(
        self, service: AgentRelayService
    ) -> None:
        connection_id = connect(service)
        make_ready(service, connection_id)
        connection = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        service.agent_repo.save_connection(
            connection.model_copy(update={"scope_verified_at": None})
        )

        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )

        assert preview.reauthentication_required is True

    def test_oversized_context_is_refused_before_reservation(
        self, service: AgentRelayService
    ) -> None:
        connection_id = connect(service)
        make_ready(service, connection_id)
        context = [
            AgentContextItemRequest(label=f"Item {index}", body="bounded")
            for index in range(21)
        ]

        with pytest.raises(ValidationFailure) as refused:
            service.preview_handoff(
                "task_1",
                AgentHandoffPreviewRequest(
                    connection_id=connection_id, context_items=context
                ),
                owner_id=OWNER,
            )

        assert refused.value.detail == {"reason": "too_many_context_items"}
        assert service.list_runs_for_task("task_1", owner_id=OWNER) == []

    def test_unreserved_manifest_and_preview_run_are_not_actionable(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        connection_id = connect(service)
        make_ready(service, connection_id)
        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )

        with pytest.raises(NotFoundError):
            service.get_run(preview.run_id, owner_id=OWNER)
        with pytest.raises(NotFoundError):
            service.reply_to_run(
                preview.run_id,
                AgentReplyRequest(message="Do not send", expected_revision=1),
                owner_id=OWNER,
                idempotency_key="idem-preview-reply",
            )
        with pytest.raises(ValidationFailure) as refused:
            service.dispatch_run(
                "task_1",
                AgentHandoffConfirmRequest(
                    connection_id=connection_id, manifest_token="f" * 64
                ),
                owner_id=OWNER,
                idempotency_key="idem-unreserved-manifest",
            )

        assert refused.value.detail == {"reason": "manifest_not_reserved"}
        assert connector.starts == []

    @pytest.mark.parametrize(
        "receipt",
        [
            {},
            {"sealed_signing_secret": {"key_id": "v1", "ciphertext": "%%%"}},
        ],
    )
    def test_corrupt_signing_secret_receipt_fails_closed(
        self,
        relay: Relay,
        service: AgentRelayService,
        receipt: dict[str, Any],
    ) -> None:
        current = service.get_connection(relay.connection_id, owner_id=OWNER).revision
        service.rotate_signing_secret(
            relay.connection_id,
            AgentConnectionRotateSigningSecretRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=current,
            ),
            owner_id=OWNER,
            idempotency_key="idem-corrupt-receipt",
            reauthenticated=True,
        )
        with sqlite3.connect(service.agent_repo.db_path) as database:
            stored = database.execute(
                "SELECT response_body FROM agent_idempotency "
                "WHERE owner_id = ? AND command = 'rotate_signing_secret'",
                (OWNER,),
            ).fetchone()
            assert stored is not None
            original = json.loads(stored[0])
            receipt["installed_secret_fingerprint"] = original[
                "installed_secret_fingerprint"
            ]
            database.execute(
                "UPDATE agent_idempotency SET response_body = ? "
                "WHERE owner_id = ? AND command = 'rotate_signing_secret'",
                (json.dumps(receipt), OWNER),
            )

        with pytest.raises(ValidationFailure) as refused:
            service.rotate_signing_secret(
                relay.connection_id,
                AgentConnectionRotateSigningSecretRequest(
                    current_password="correct-horse-battery-staple",
                    expected_revision=current,
                ),
                owner_id=OWNER,
                idempotency_key="idem-corrupt-receipt",
                reauthenticated=True,
            )

        assert refused.value.detail == {"reason": "signing_secret_unrecoverable"}

    def test_overflowing_timestamp_is_rejected_without_mutation(
        self, relay: Relay
    ) -> None:
        body = json.dumps(relay.event("evt_overflow", "running", 1)).encode("utf-8")

        with pytest.raises(EventRejected) as refused:
            relay.service.ingest_event(
                raw_body=body,
                connection_id=relay.connection_id,
                timestamp="9" * 400,
                signature="v1=" + "0" * 64,
            )

        assert refused.value.code == "timestamp_invalid"
        assert relay.projection().reported_state is None

    @pytest.mark.parametrize("body", [b"\xff", b"[]"])
    def test_authenticated_non_object_body_is_rejected_and_audited(
        self, relay: Relay, body: bytes
    ) -> None:
        timestamp = int(relay.clock.now.timestamp())

        with pytest.raises(EventRejected) as refused:
            relay.service.ingest_event(
                raw_body=body,
                connection_id=relay.connection_id,
                timestamp=str(timestamp),
                signature=sign(relay.secret, timestamp, body),
            )

        assert refused.value.code == "body_invalid"
        assert any(
            entry.action == "event_rejected" and entry.outcome == "body_invalid"
            for entry in relay.service.list_audit(owner_id=OWNER)
        )

    def test_run_marked_disconnected_rejects_a_late_authenticated_event(
        self, relay: Relay
    ) -> None:
        persisted = relay.service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        relay.service.agent_repo.save_run(
            persisted.model_copy(update={"connection_disconnected_at": relay.clock.now})
        )

        with pytest.raises(EventRejected) as refused:
            relay.emit(relay.event("evt_late", "running", 1))

        assert refused.value.code == "connection_disconnected"
        assert relay.projection().reported_state is None


class TestDispatchScopeReauthentication:
    def test_a_fresh_scope_does_not_re_prompt_for_the_password(
        self, service: AgentRelayService
    ) -> None:
        """FR-003: the create-time proof covers an immediately following send."""

        connection_id = connect(service)
        make_ready(service, connection_id)

        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )

        assert preview.reauthentication_required is False

    def test_a_stale_scope_requires_the_password_for_the_first_dispatch(
        self, service: AgentRelayService, clock: Clock, connector: FakeConnector
    ) -> None:
        """FR-003: first content-bearing dispatch in an old scope re-verifies."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        clock.advance(timedelta(minutes=16))
        service.test_connection(connection_id, owner_id=OWNER)

        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )
        assert preview.reauthentication_required is True

        with pytest.raises(ValidationFailure):
            service.dispatch_run(
                "task_1",
                AgentHandoffConfirmRequest(
                    connection_id=connection_id, manifest_token=preview.token
                ),
                owner_id=OWNER,
                idempotency_key="idem-dispatch",
            )
        assert connector.starts == []

    def test_once_content_has_been_sent_the_scope_no_longer_re_prompts(
        self, service: AgentRelayService, clock: Clock
    ) -> None:
        """The trigger is the *first* dispatch in a scope, not every dispatch."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        dispatch(service, connection_id, key="idem-a")
        clock.advance(timedelta(days=1))
        service.test_connection(connection_id, owner_id=OWNER)

        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )

        assert preview.reauthentication_required is False


# --- Key-ring rotation across a rolling deploy -------------------------------

RELAY_KEY_OLD = b"\x11" * 32
RELAY_KEY_NEW = b"\x22" * 32
COMMAND_NAMES = {
    "start": "dispatch_run",
    "reply": "reply_to_run",
    "cancel": "cancel_run",
}


def old_ring() -> OrderedDict[str, bytes]:
    """The ring an instance that has not restarted yet is still running."""

    return OrderedDict({"v1": RELAY_KEY_OLD})


def rotated_ring() -> OrderedDict[str, bytes]:
    """The ring a restarted instance runs: the new key first, the old retained."""

    return OrderedDict({"v2": RELAY_KEY_NEW, "v1": RELAY_KEY_OLD})


def retired_ring() -> OrderedDict[str, bytes]:
    """The ring once the old key is dropped from the configuration."""

    return OrderedDict({"v2": RELAY_KEY_NEW})


def stored_idempotency(tmp_path: Path, command: str) -> tuple[str, str]:
    """The one persisted (key_hash, request_hash) pair for ``command``."""

    with sqlite3.connect(tmp_path / "agents.sqlite3") as database:
        rows = database.execute(
            "SELECT key_hash, request_hash FROM agent_idempotency "
            "WHERE owner_id = ? AND command = ?",
            (OWNER, command),
        ).fetchall()
    assert len(rows) == 1
    return str(rows[0][0]), str(rows[0][1])


class RotationScenario:
    """One start, reply, or cancel, replayable on any key-ring generation.

    Every instance it builds shares one database and one connector, which is
    what a rolling deploy actually looks like: the same records, read and
    written by processes whose relay key rings differ.
    """

    def __init__(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        *,
        operation: str,
        setup_ring: OrderedDict[str, bytes],
    ) -> None:
        self._tmp_path = tmp_path
        self._connector = connector
        self._clock = clock
        self.operation = operation
        self.command = COMMAND_NAMES[operation]
        # The connection is created once, so its credential is sealed under the
        # setup ring's active key and every generation under test can open it.
        setup = self.instance(setup_ring)
        self.connection_id = connect(setup)
        make_ready(setup, self.connection_id)
        self._confirm: AgentHandoffConfirmRequest | None = None
        self._reply: AgentReplyRequest | None = None
        if operation == "start":
            self._confirm = review(setup, self.connection_id)
            reserved = setup.agent_repo.list_runs_for_task("task_1", owner_id=OWNER)
            self.run_id = reserved[0].id
        else:
            self.run_id = dispatch(setup, self.connection_id, key="idem-setup").id

    def instance(self, ring: OrderedDict[str, bytes]) -> AgentRelayService:
        return build_service(
            AgentRepository(self._tmp_path), self._connector, self._clock, keys=ring
        )

    def invoke(self, service: AgentRelayService, *, key: str) -> Any:
        """Run the operation. The request is fixed, so a retry is a true retry."""

        if self.operation == "start":
            assert self._confirm is not None
            return service.dispatch_run(
                "task_1", self._confirm, owner_id=OWNER, idempotency_key=key
            )
        if self.operation == "reply":
            if self._reply is None:
                self._reply = AgentReplyRequest(
                    message="Use staging.",
                    expected_revision=service.get_run(
                        self.run_id, owner_id=OWNER
                    ).revision,
                )
            return service.reply_to_run(
                self.run_id, self._reply, owner_id=OWNER, idempotency_key=key
            )
        return service.cancel_run(self.run_id, owner_id=OWNER, idempotency_key=key)

    def invoke_fresh(self, service: AgentRelayService, *, key: str) -> Any:
        """Run a genuinely new operation of the same kind under a new key."""

        if self.operation == "start":
            make_ready(service, self.connection_id)
            return dispatch(service, self.connection_id, key=key)
        if self.operation == "reply":
            return service.reply_to_run(
                self.run_id,
                AgentReplyRequest(
                    message="Staging is fine.",
                    expected_revision=service.get_run(
                        self.run_id, owner_id=OWNER
                    ).revision,
                ),
                owner_id=OWNER,
                idempotency_key=key,
            )
        return service.cancel_run(self.run_id, owner_id=OWNER, idempotency_key=key)

    @property
    def deliveries(self) -> list[dict[str, Any]]:
        """Everything this operation has actually put on the wire."""

        if self.operation == "start":
            return self._connector.starts
        return self._connector.commands


class TestKeyRotationPreservesAtMostOnce:
    """A rotating key ring must never turn a retry into a second delivery.

    The stored identity of an Idempotency-Key is anchored to the *oldest* key
    in the ring, so every instance in a rolling overlap computes the same
    fingerprint for the same key whether or not it has the new one yet.
    """

    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    def test_a_rotated_instance_write_is_replayed_by_a_stale_instance(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        operation: str,
    ) -> None:
        """Mid-deploy, the new instance takes the command and the old one retries."""

        scenario = RotationScenario(
            tmp_path, connector, clock, operation=operation, setup_ring=old_ring()
        )
        rotated = scenario.instance(rotated_ring())
        first = scenario.invoke(rotated, key="idem-rotation")

        stale = scenario.instance(old_ring())
        replayed = scenario.invoke(stale, key="idem-rotation")

        assert len(scenario.deliveries) == 1
        assert replayed.id == first.id
        assert [item.id for item in replayed.commands] == [
            item.id for item in first.commands
        ]

    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    def test_a_stale_instance_write_is_replayed_by_a_rotated_instance(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        operation: str,
    ) -> None:
        """The other direction of the same overlap: old writes, new retries."""

        scenario = RotationScenario(
            tmp_path, connector, clock, operation=operation, setup_ring=old_ring()
        )
        stale = scenario.instance(old_ring())
        first = scenario.invoke(stale, key="idem-rotation")

        rotated = scenario.instance(rotated_ring())
        replayed = scenario.invoke(rotated, key="idem-rotation")

        assert len(scenario.deliveries) == 1
        assert replayed.id == first.id
        assert [item.id for item in replayed.commands] == [
            item.id for item in first.commands
        ]

    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    def test_the_replay_identity_is_anchored_to_the_oldest_configured_key(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
        operation: str,
    ) -> None:
        """Anchoring to the newest key would strand the record on the next rotation."""

        scenario = RotationScenario(
            tmp_path, connector, clock, operation=operation, setup_ring=old_ring()
        )
        rotated = scenario.instance(rotated_ring())
        locked: list[str] = []
        original_lock = rotated.agent_repo.operation_lock

        def spy(owner_id: str, operation_fingerprint: str) -> Any:
            locked.append(operation_fingerprint)
            return original_lock(owner_id, operation_fingerprint)

        monkeypatch.setattr(rotated.agent_repo, "operation_lock", spy)

        scenario.invoke(rotated, key="idem-anchor")

        key_hash, request_hash = stored_idempotency(tmp_path, scenario.command)
        newest_candidate = rotated._key_hashes(OWNER, "idem-anchor")[0]
        assert newest_candidate.startswith("v2:")
        assert key_hash.startswith("v1:")
        assert request_hash.startswith("v1:")
        assert key_hash != newest_candidate
        # The operation lock and the row it guards must be the same identity, or
        # two instances would serialise on different names for one command.
        assert locked == [key_hash]

    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    def test_retiring_a_key_while_its_records_live_fails_closed(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        operation: str,
    ) -> None:
        """An unfindable record must refuse the retry, never re-deliver it."""

        scenario = RotationScenario(
            tmp_path, connector, clock, operation=operation, setup_ring=rotated_ring()
        )
        rotated = scenario.instance(rotated_ring())
        scenario.invoke(rotated, key="idem-retire")
        assert len(scenario.deliveries) == 1

        retired = scenario.instance(retired_ring())
        with pytest.raises(RelayKeyRotationUnsafe) as refused:
            scenario.invoke(retired, key="idem-retire")

        assert refused.value.retired_key_ids == ("v1",)
        assert len(scenario.deliveries) == 1

    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    def test_expired_idempotency_does_not_release_a_still_sealed_connection(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        operation: str,
    ) -> None:
        """A live credential is independently enough to keep its key configured."""

        scenario = RotationScenario(
            tmp_path, connector, clock, operation=operation, setup_ring=old_ring()
        )
        rotated = scenario.instance(rotated_ring())
        scenario.invoke(rotated, key="idem-expiring-connection-live")

        clock.advance(IDEMPOTENCY_RETENTION + timedelta(hours=1))
        retired = scenario.instance(retired_ring())
        with pytest.raises(RelayKeyRotationUnsafe) as refused:
            retired._require_intact_key_ring(clock())

        assert refused.value.retired_key_ids == ("v1",)
        assert len(scenario.deliveries) == 1

    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    def test_a_key_may_be_retired_once_every_reference_is_gone(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        operation: str,
    ) -> None:
        """Retirement becomes safe only after retained receipts and secrets are gone."""

        scenario = RotationScenario(
            tmp_path, connector, clock, operation=operation, setup_ring=rotated_ring()
        )
        rotated = scenario.instance(rotated_ring())
        scenario.invoke(rotated, key="idem-expiring")

        clock.advance(IDEMPOTENCY_RETENTION + timedelta(hours=1))
        rotated.agent_repo.purge_expired_idempotency(owner_id=OWNER, now=clock())
        rotated.agent_repo.delete_all_for_owner(owner_id=OWNER)
        retired = scenario.instance(retired_ring())

        retired._require_intact_key_ring(clock())
        assert retired.agent_repo.live_sealed_key_ids(now=clock()).key_ids == set()


def rewrite_stored_key_hash(tmp_path: Path, command: str, key_hash: str) -> None:
    """Corrupt the one stored fingerprint for ``command``, as a bad write would."""

    with sqlite3.connect(tmp_path / "agents.sqlite3") as database:
        updated = database.execute(
            "UPDATE agent_idempotency SET key_hash = ? "
            "WHERE owner_id = ? AND command = ?",
            (key_hash, OWNER, command),
        ).rowcount
    assert updated == 1


MALFORMED_FINGERPRINTS = [
    # The dangerous one: reading the text before the first colon calls this the
    # configured key id "v2" and the record looks perfectly findable.
    "v2",
    "v2:",
    "v2:short",
    "v2:" + "f" * 63,
    "v2:" + "f" * 64 + "f",
    "v2:" + "z" * 64,
    "v2:" + "F" * 64,
    "v2:v1:" + "f" * 64,
    "relay key:" + "f" * 64,
    "relay,key:" + "f" * 64,
    "relay\x00key:" + "f" * 64,
    "clé:" + "f" * 64,
    "a" * 65 + ":" + "f" * 64,
    "",
]


class TestMalformedStoredFingerprintsFailClosed:
    """A stored fingerprint that cannot be read is an unprovable replay.

    The record is still within retention and still describes a command that may
    already have reached the user's agent, but nothing can match a key against
    it. Serving the request anyway would deliver the command a second time, so
    the relay refuses instead — the same fail-closed rule a retired key gets.
    """

    @pytest.mark.parametrize("key_hash", MALFORMED_FINGERPRINTS)
    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    def test_a_malformed_live_record_refuses_the_command(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        operation: str,
        key_hash: str,
    ) -> None:
        """Nothing reaches the connector while a live record is unreadable."""

        scenario = RotationScenario(
            tmp_path, connector, clock, operation=operation, setup_ring=rotated_ring()
        )
        rotated = scenario.instance(rotated_ring())
        scenario.invoke(rotated, key="idem-corrupt")
        assert len(scenario.deliveries) == 1
        rewrite_stored_key_hash(tmp_path, scenario.command, key_hash)

        with pytest.raises(RelayFingerprintUnreadable) as refused:
            scenario.invoke(scenario.instance(rotated_ring()), key="idem-corrupt")

        assert refused.value.unreadable_records == 1
        assert len(scenario.deliveries) == 1

    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    def test_a_malformed_record_also_refuses_an_unrelated_command(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        operation: str,
    ) -> None:
        """The doubt is about the owner's records, not about this one key."""

        scenario = RotationScenario(
            tmp_path, connector, clock, operation=operation, setup_ring=rotated_ring()
        )
        rotated = scenario.instance(rotated_ring())
        scenario.invoke(rotated, key="idem-corrupt-other")
        rewrite_stored_key_hash(tmp_path, scenario.command, "v2:not-a-mac")

        with pytest.raises(RelayFingerprintUnreadable):
            scenario.invoke_fresh(scenario.instance(rotated_ring()), key="idem-fresh")

        assert len(scenario.deliveries) == 1

    def test_the_refusal_never_carries_the_stored_fingerprint(
        self, tmp_path: Path, connector: FakeConnector, clock: Clock
    ) -> None:
        """The message reaches the user, so it may name neither hash nor key."""

        scenario = RotationScenario(
            tmp_path, connector, clock, operation="start", setup_ring=rotated_ring()
        )
        rotated = scenario.instance(rotated_ring())
        scenario.invoke(rotated, key="idem-quiet")
        corrupt = "v2:" + "a" * 40
        rewrite_stored_key_hash(tmp_path, scenario.command, corrupt)

        with pytest.raises(RelayFingerprintUnreadable) as refused:
            scenario.invoke(scenario.instance(rotated_ring()), key="idem-quiet")

        message = str(refused.value)
        assert corrupt not in message
        assert "a" * 40 not in message
        assert "v2" not in message
        assert "idem-quiet" not in message

    @pytest.mark.parametrize("operation", ["start", "reply", "cancel"])
    def test_an_expired_malformed_record_stops_blocking_new_commands(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        operation: str,
    ) -> None:
        """Retention releases an unreadable row exactly as it releases any other."""

        scenario = RotationScenario(
            tmp_path, connector, clock, operation=operation, setup_ring=rotated_ring()
        )
        rotated = scenario.instance(rotated_ring())
        scenario.invoke(rotated, key="idem-corrupt-expiring")
        rewrite_stored_key_hash(tmp_path, scenario.command, "v2")

        clock.advance(IDEMPOTENCY_RETENTION + timedelta(hours=1))
        scenario.invoke_fresh(scenario.instance(rotated_ring()), key="idem-after")

        assert len(scenario.deliveries) == 2
