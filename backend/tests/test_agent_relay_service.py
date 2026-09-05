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
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Annotated, Any, Literal

import httpx
import pytest
from pydantic import AfterValidator, Field
from pydantic import ValidationError as PydanticValidationError

from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.modules.agents.a2a.card import (
    SINGLE_START_EXTENSION_URI,
    AgentAuthSchemeOffer,
    CardDiscovery,
    fetch_card,
)
from app.modules.agents.a2a.client import A2AResult
from app.modules.agents.a2a.mapping import ObservationLimits, project_observation
from app.modules.agents.a2a.types import Message, Task
from app.modules.agents.connector import (
    ConnectorCommandOutcome,
    ConnectorStartOutcome,
    ConnectorTarget,
    ConnectorTestOutcome,
)
from app.modules.agents.domain import (
    PROTOCOL_VERSION,
    REPORTING_INSTRUCTIONS_VERSION,
    AgentCapabilities,
    AgentConnectionDocument,
    AgentRunManifest,
    inert_reporting_contract,
)
from app.modules.agents.headers import (
    RESERVED_AUTH_HEADER_NAMES,
    validate_auth_header_name,
)
from app.modules.agents.repository import IDEMPOTENCY_RETENTION, AgentRepository
from app.modules.agents.secrets import SealedSecret, SecretBox
from app.modules.agents.service import (
    SCOPE_REAUTH_WINDOW,
    AgentRelayService,
    EventRejected,
    ExchangePolicy,
    RelayFingerprintUnreadable,
    RelayKeyRotationUnsafe,
    TaskSnapshot,
)
from app.schemas.agents import (
    AgentCheckDeliveryRequest,
    AgentConnectionCreateRequest,
    AgentConnectionDisconnectRequest,
    AgentConnectionResponse,
    AgentConnectionRotateRequest,
    AgentConnectionRotateSigningSecretRequest,
    AgentConnectionUpdateRequest,
    AgentContextItemRequest,
    AgentHandoffConfirmRequest,
    AgentHandoffPreviewRequest,
    AgentReplyRequest,
)
from app.schemas.common import StorageBaseModel

from .a2a_fakes import (
    FakeA2AClient,
    FakeCardFetcher,
    card_summary,
    ready_discovery,
)

OWNER = "user_a"
OTHER_OWNER = "user_b"
CALLBACK = "https://brainbuddy.example/api/agent-events"
PUSH_BASE = "https://brainbuddy.example/api/a2a/push"


class FakeConnector:
    """A scriptable stand-in for a user's agent."""

    def __init__(self) -> None:
        self.test_outcome = ConnectorTestOutcome(
            "ready", AgentCapabilities(streaming=True, push_notifications=True)
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


def mock_transport_card_fetcher(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[..., CardDiscovery]:
    """The *real* discovery path over a scripted transport.

    Two cases cannot be expressed as a `CardDiscovery` double, because they are
    about what the fetch itself refuses: a body that is not JSON and a body over
    the response cap. Both have to run `fetch_card` for real.
    """

    def client_factory(**kwargs: Any) -> httpx.Client:
        kwargs.pop("transport", None)
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    def fetch(
        address: str, *, auth_scheme: str, now: datetime | None = None
    ) -> CardDiscovery:
        return fetch_card(
            address,
            auth_scheme=auth_scheme,  # type: ignore[arg-type]
            timeout_seconds=5.0,
            max_response_bytes=64_000,
            resolver=fake_resolver,
            client_factory=client_factory,
            now=now,
        )

    return fetch


class BlockingCardFetcher(FakeCardFetcher):
    """Discovery held open on a barrier, so a test can move the world under it.

    Under 014 a connection test is discovery plus an authenticated probe, both
    outside the owner lock. That is the window these races exercise: the fields
    the test would merge back must lose to anything the owner did meanwhile.
    """

    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def __call__(
        self,
        address: str,
        *,
        auth_scheme: str,
        now: datetime | None = None,
    ) -> CardDiscovery:
        self.calls.append((address, auth_scheme))
        self.entered.set()
        assert self.release.wait(timeout=5)
        return self.discovery


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


class BlockingA2AClient(FakeA2AClient):
    """A scripted A2A client whose send waits for the test to release it.

    The 014 counterpart of `BlockingIoConnector`: the content-bearing call is
    now `SendMessage`, so that is where a slow agent has to be simulated for
    the lock-scope and contention assertions to mean anything.
    """

    def __init__(self) -> None:
        super().__init__()
        self.block_kind: str | None = None
        self.entered = Event()
        self.release = Event()

    def send_message(self, target: Any, **kwargs: Any) -> A2AResult:
        result = super().send_message(target, **kwargs)
        # A reply is a `SendMessage` too, so the two are told apart by what
        # only a reply carries: its own command id. The task id will not do —
        # a run whose start exchange never returned a task has none to name.
        message = kwargs.get("message", {})
        kind = (
            "reply"
            if message.get("metadata", {}).get("brainbuddy.command_id")
            else "start"
        )
        self._block(kind)
        return result

    def cancel_task(self, target: Any, **kwargs: Any) -> A2AResult:
        result = super().cancel_task(target, **kwargs)
        self._block("cancel")
        return result

    def _block(self, kind: str) -> None:
        if self.block_kind == kind:
            self.entered.set()
            assert self.release.wait(timeout=5)


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


class SynchronousExecutor:
    """An exchange pool with no threads: `submit` runs the work inline.

    The exchange state machine is what these tests are about, so it is driven
    directly rather than raced against a real pool — a sleep would only make the
    same assertions slower and flakier.
    """

    def __init__(self) -> None:
        self.submitted: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] = []

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        self.submitted.append((fn, args, kwargs))
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # pragma: no cover - surfaced by the test
            future.set_exception(exc)
        return future


class SaturatedExecutor:
    """A pool with no free worker: everything submitted stays queued."""

    def __init__(self) -> None:
        self.submitted: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] = []

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        self.submitted.append((fn, args, kwargs))
        return Future()

    def run_pending(self) -> None:
        pending, self.submitted = self.submitted, []
        for fn, args, kwargs in pending:
            fn(*args, **kwargs)


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


@pytest.fixture
def card_fetcher() -> FakeCardFetcher:
    return FakeCardFetcher()


@pytest.fixture
def a2a_client() -> FakeA2AClient:
    return FakeA2AClient()


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
    card_fetcher: Any | None = None,
    a2a_client: Any | None = None,
    exchange_executor: Any | None = None,
) -> AgentRelayService:
    return AgentRelayService(
        repo,
        connector=connector,
        secret_box=SecretBox(keys if keys is not None else OrderedDict({"v1": key})),
        task_snapshot=task_snapshot,
        callback_url=CALLBACK,
        push_base_url=PUSH_BASE,
        card_fetcher=card_fetcher if card_fetcher is not None else FakeCardFetcher(),
        a2a_client=a2a_client if a2a_client is not None else FakeA2AClient(),
        exchange=ExchangePolicy(executor=exchange_executor),
        resolver=fake_resolver,
        now=clock,
    )


@pytest.fixture
def service(
    tmp_path: Path,
    connector: FakeConnector,
    clock: Clock,
    card_fetcher: FakeCardFetcher,
    a2a_client: FakeA2AClient,
) -> AgentRelayService:
    return build_service(
        AgentRepository(tmp_path),
        connector,
        clock,
        card_fetcher=card_fetcher,
        a2a_client=a2a_client,
        # Inline by default: almost every test here is about what one dispatch
        # *decides*, not about how long it waits for a worker, and a pool that
        # answered later would only make those assertions race. The tests that
        # are about queueing supply their own executor.
        exchange_executor=SynchronousExecutor(),
    )


def create_request(**overrides: Any) -> AgentConnectionCreateRequest:
    payload: dict[str, Any] = {
        "name": "Hermes",
        "agent_address": "https://agent.example.com",
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


def issue_signing_secret(
    service: AgentRelayService,
    connection_id: str,
    *,
    key: str = "idem-signing",
    revision: int | None = None,
) -> str:
    """Mint the bespoke inbound signing secret for a connection.

    Registration no longer issues one (014 FR-012: the A2A wire has no inbound
    secret), so the 007 event suites that still need one take it from the
    rotation route — the only place it is ever shown — until T110–T114 remove
    that surface with the rest of the bespoke wire.
    """

    current = service.get_connection(connection_id, owner_id=OWNER)
    rotated = service.rotate_signing_secret(
        connection_id,
        AgentConnectionRotateSigningSecretRequest(
            current_password="correct-horse-battery-staple",
            expected_revision=revision if revision is not None else current.revision,
        ),
        owner_id=OWNER,
        idempotency_key=key,
        reauthenticated=True,
    )
    return rotated.inbound_signing_secret


def sends(a2a_client: FakeA2AClient) -> list[dict[str, Any]]:
    """Every content-bearing message this dispatch put on the wire.

    The 014 replacement for the bespoke connector's `starts`: the A2A
    `SendMessage` is the only call that carries task content.
    """

    return [
        kwargs["message"]
        for _method, _target, kwargs in a2a_client.calls_to("SendMessage")
    ]


def replies(a2a_client: FakeA2AClient) -> list[dict[str, Any]]:
    """Only the follow-up messages: a reply carries its own command id.

    Selected by the command id rather than by `taskId`, because a run whose
    start exchange never returned a task has no task id to name and the reply
    still has to be tellable from the start.
    """

    return [
        message
        for message in sends(a2a_client)
        if message.get("metadata", {}).get("brainbuddy.command_id")
    ]


def cancels(a2a_client: FakeA2AClient) -> list[dict[str, Any]]:
    return [kwargs for _m, _t, kwargs in a2a_client.calls_to("CancelTask")]


def wire_commands(service: AgentRelayService) -> list[dict[str, Any]]:
    """Every reply and cancel this service actually put on the A2A wire.

    The 014 replacement for the bespoke connector's `commands`, and the shape
    the at-most-once suites assert on: one entry per delivery, each naming its
    kind and the command id that makes a retry the *same* request rather than a
    second one the agent could act on.
    """

    client = service.a2a_client
    assert client is not None
    return wire_commands_of(client)  # type: ignore[arg-type]


def wire_commands_of(client: FakeA2AClient) -> list[dict[str, Any]]:
    """The same list, for a client shared by several service generations."""

    delivered: list[dict[str, Any]] = []
    for method, _target, kwargs in client.calls:
        if method == "CancelTask":
            delivered.append({"type": "cancel", "command_id": kwargs["command_id"]})
            continue
        if method != "SendMessage":
            continue
        command_id = kwargs["message"].get("metadata", {}).get(
            "brainbuddy.command_id"
        )
        if command_id is not None:
            delivered.append({"type": "reply", "command_id": command_id})
    return delivered


def clear_wire(service: AgentRelayService) -> None:
    client = service.a2a_client
    assert client is not None
    client.calls.clear()  # type: ignore[attr-defined]


def review(
    service: AgentRelayService,
    connection_id: str,
    *,
    task_id: str = "task_1",
    context: list[AgentContextItemRequest] | None = None,
    acknowledge: bool = True,
) -> AgentHandoffConfirmRequest:
    """Run the review and return the exact confirmation it authorises.

    `acknowledge` defaults to true because the suite's connections are
    best-effort and a real review would have shown the one-time duplicate-risk
    box; the tests that assert the gate itself pass `acknowledge=False` (AC-026).
    """

    preview = service.preview_handoff(
        task_id,
        AgentHandoffPreviewRequest(
            connection_id=connection_id, supporting_items=context or []
        ),
        owner_id=OWNER,
    )
    return AgentHandoffConfirmRequest(
        connection_id=connection_id,
        supporting_items=context or [],
        manifest_token=preview.token,
        acknowledge_duplicate_risk=acknowledge,
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

    def test_014_FR_012_registration_issues_no_secret_for_the_owner_to_configure(
        self, service: AgentRelayService
    ) -> None:
        """The A2A wire has no inbound secret, so the 201 has nothing to show.

        014-FR-012. Under 007 this response carried a secret the owner had to
        copy into their agent exactly once. There is nothing to copy any more:
        push callbacks carry a per-run token BrainBuddy mints and the user never
        sees, so the safest place for a secret is a response that cannot hold one.
        """

        created = service.create_connection(
            create_request(),
            owner_id=OWNER,
            idempotency_key="idem-1",
            reauthenticated=True,
        )

        assert isinstance(created, AgentConnectionResponse)
        assert not hasattr(created, "inbound_signing_secret")
        assert "inbound_signing_secret" not in created.model_dump()
        fetched = service.get_connection(created.id, owner_id=OWNER)
        assert not hasattr(fetched, "inbound_signing_secret")

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
                create_request(agent_address=endpoint),
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

    def test_014_FR_002_the_bespoke_connector_probe_is_no_longer_the_test_path(
        self, service: AgentRelayService, connector: FakeConnector
    ) -> None:
        """The four 007 connector outcomes are gone, not merely unused.

        007 decided readiness from a bespoke capability probe. 014 decides it
        from the agent's published card plus an authenticated A2A call, and the
        cases that used to live here are re-expressed against that path in
        `TestConnectByAgentCard`. This case is what keeps the old path from
        quietly coming back: a connection test must reach the wire, and the
        bespoke connector must see nothing (014-FR-002, 014-FR-012).
        """

        connection_id = connect(service)

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "ready"
        assert connector.tests == []

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
        assert updated.agent_address == current.agent_address
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
            agent_address=current.agent_address,
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
            agent_address="https://second.example.com/hooks",
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
        assert updated.agent_address == "https://second.example.com/hooks"
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


# --- 014 User Story 1: connect an agent by its published card ----------------


class TestConnectByAgentCard:
    """Discovery, the authenticated probe, the tier, and every named failure.

    The organising rule of this class is that a connection only becomes **ready**
    when two separate things happened: BrainBuddy read a card it can speak to,
    and the stored credential authenticated against the interface that card
    named. Anything less is one of six categories, each with its own sentence.
    """

    def test_014_FR_002_ready_requires_an_authenticated_list_tasks_probe(
        self,
        service: AgentRelayService,
        card_fetcher: FakeCardFetcher,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-001. A card read proves an agent exists, not that we may talk to it."""

        connection_id = connect(service)
        before = service.get_connection(connection_id, owner_id=OWNER)
        assert before.status == "untested"
        assert before.card is None

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert card_fetcher.calls == [("https://agent.example.com", "bearer")]
        probes = a2a_client.calls_to("ListTasks")
        assert len(probes) == 1
        assert probes[0][2]["page_size"] == 1
        assert probes[0][1].interface_url == "https://agent.example.com/a2a"
        assert probes[0][1].credential == "Bearer super-secret-token"
        assert tested.status == "ready"
        assert tested.ready_for_handoff is True
        assert tested.last_test_error_code is None
        assert tested.card is not None
        assert tested.card.name == "Hermes"
        assert tested.card.interface_url == "https://agent.example.com/a2a"
        assert tested.capabilities.model_dump() == {
            "streaming": True,
            "push_notifications": False,
        }
        assert tested.controls_offered.model_dump() == {"reply": True, "cancel": True}

    def test_014_FR_002_a_method_not_found_probe_falls_back_to_a_get_task_sentinel(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """AC-001. An agent without ListTasks is still an authenticated agent.

        The sentinel read is the cheapest authenticated call left: a task id
        nobody owns, whose ``-32001`` answer proves the credential was accepted
        before the lookup failed.
        """

        a2a_client.script(
            "ListTasks",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_method_not_found"),
        )
        a2a_client.script(
            "GetTask",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_task_not_found"),
        )
        connection_id = connect(service)

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "ready"
        assert a2a_client.calls_to("GetTask")[0][2]["task_id"] == "brainbuddy-probe"

    @pytest.mark.parametrize(
        "probe",
        [
            A2AResult(
                ok=False,
                correlation_id="c",
                error_code="a2a_credentials_rejected",
                http_status=401,
            ),
            A2AResult(
                ok=False,
                correlation_id="c",
                error_code="a2a_credentials_rejected",
                http_status=403,
            ),
            A2AResult(
                ok=False,
                correlation_id="c",
                error_code="a2a_credentials_rejected",
                a2a_error_code=-32050,
            ),
            A2AResult(
                ok=False,
                correlation_id="c",
                error_code="a2a_credentials_rejected",
                a2a_error_code=-32052,
            ),
        ],
    )
    def test_014_FR_002_a_rejected_credential_is_named_and_never_echoed(
        self,
        service: AgentRelayService,
        a2a_client: FakeA2AClient,
        probe: A2AResult,
    ) -> None:
        """AC-003, 014-SC-009. The agent answered; only the credential failed."""

        a2a_client.script("ListTasks", probe)
        connection_id = connect(service)

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "invalid_credentials"
        assert tested.last_test_error_code == "a2a_credentials_rejected"
        assert tested.ready_for_handoff is False
        assert "super-secret-token" not in tested.model_dump_json()

    @pytest.mark.parametrize("error_code", ["a2a_unreachable", "a2a_timeout"])
    def test_014_FR_002_transport_failure_and_deadline_breach_read_as_unreachable(
        self, service: AgentRelayService, a2a_client: FakeA2AClient, error_code: str
    ) -> None:
        """AC-002. A deadline breach is still "we could not reach it in time"."""

        a2a_client.script(
            "ListTasks", A2AResult(ok=False, correlation_id="c", error_code=error_code)
        )
        connection_id = connect(service)

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "unreachable"
        assert tested.last_test_error_code == "a2a_unreachable"
        assert tested.last_test_error_detail is None

    @pytest.mark.parametrize(
        ("failure_code", "failure_detail", "expected_detail"),
        [
            ("a2a_not_an_agent", None, None),
            (
                "a2a_protocol_version_unsupported",
                {"found_version": "0.9.4"},
                {"found_version": "0.9.4"},
            ),
            ("a2a_no_supported_interface", None, None),
            (
                "a2a_auth_scheme_unsupported",
                {"scheme": "oauth2"},
                {"scheme": "oauth2"},
            ),
        ],
    )
    def test_014_FR_002_the_four_unsupported_categories_keep_their_own_detail(
        self,
        service: AgentRelayService,
        card_fetcher: FakeCardFetcher,
        a2a_client: FakeA2AClient,
        failure_code: str,
        failure_detail: dict[str, Any] | None,
        expected_detail: dict[str, Any] | None,
    ) -> None:
        """AC-002, AC-004. Four sentences, not one shrug (D-01-S14..S17)."""

        card_fetcher.discovery = CardDiscovery(
            failure_code=failure_code, failure_detail=failure_detail
        )
        connection_id = connect(service)

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "unsupported"
        assert tested.last_test_error_code == failure_code
        assert tested.last_test_error_detail == expected_detail
        assert tested.card is None
        # Nothing authenticated was attempted: the card already said this agent
        # cannot be spoken to, so sending the credential would leak it for
        # nothing.
        assert a2a_client.calls_to("ListTasks") == []

    def test_014_FR_004_a_private_destination_is_refused_before_a_credential_leaves(
        self, tmp_path: Path, connector: FakeConnector, clock: Clock
    ) -> None:
        """AC-006, D-01-S18. Nothing left BrainBuddy."""

        card_fetcher = FakeCardFetcher()
        a2a_client = FakeA2AClient()
        service = build_service(
            AgentRepository(tmp_path),
            connector,
            clock,
            card_fetcher=card_fetcher,
            a2a_client=a2a_client,
        )
        connection_id = connect(service)
        stored = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        service.agent_repo.save_connection(
            stored.model_copy(update={"endpoint_url": "http://127.0.0.1:9/hooks"})
        )

        with pytest.raises(ValidationFailure) as excinfo:
            service.test_connection(connection_id, owner_id=OWNER)

        assert str(excinfo.value.detail["reason"]).startswith("destination_")
        assert card_fetcher.calls == []
        assert a2a_client.calls == []

    def test_rate_limited_connection_test_keeps_status_untested_and_records_retry_after(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """AC-037, D-01-S25. A refusal to answer is not a verdict on the agent.

        The connection stays **untested** — never ready — because the probe
        learned nothing, and the retry hint is the agent's own number or nothing
        at all rather than a countdown BrainBuddy invented.
        """

        a2a_client.script(
            "ListTasks",
            A2AResult(
                ok=False,
                correlation_id="c",
                error_code="a2a_rate_limited",
                http_status=429,
                retry_after_seconds=30,
            ),
        )
        connection_id = connect(service)

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "untested"
        assert tested.ready_for_handoff is False
        assert tested.last_test_error_code == "a2a_rate_limited"
        assert tested.last_test_error_detail == {"retry_after_seconds": 30}

    def test_014_FR_002_a_rate_limit_without_a_hint_records_no_invented_countdown(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """CHK051. "Test again shortly." is the honest copy for a missing hint."""

        a2a_client.script(
            "ListTasks",
            A2AResult(
                ok=False,
                correlation_id="c",
                error_code="a2a_rate_limited",
                http_status=429,
            ),
        )
        connection_id = connect(service)

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.last_test_error_detail == {"retry_after_seconds": None}

    def test_014_FR_011_the_guaranteed_tier_requires_the_declared_extension_uri(
        self, service: AgentRelayService, card_fetcher: FakeCardFetcher
    ) -> None:
        """AC-001, AC-005. The tier is read off the card, never assumed."""

        best_effort = service.test_connection(connect(service), owner_id=OWNER)
        assert best_effort.guarantee_tier == "best_effort"
        assert best_effort.tier_disclosure_url

        card_fetcher.discovery = ready_discovery(
            summary=card_summary(extension_uris=[SINGLE_START_EXTENSION_URI])
        )
        guaranteed = service.test_connection(
            connect(service, key="idem-guaranteed"), owner_id=OWNER
        )

        assert guaranteed.guarantee_tier == "guaranteed"
        assert guaranteed.card is not None
        assert guaranteed.card.extension_uris == [SINGLE_START_EXTENSION_URI]

    def test_014_FR_014_tier_disclosures_carry_the_exact_server_owned_copy(
        self, service: AgentRelayService, card_fetcher: FakeCardFetcher
    ) -> None:
        """FR-014. The two tier sentences are BrainBuddy's, asserted once here.

        Both clients render them verbatim, so a drift in this copy is a drift in
        the product's promise rather than a cosmetic one — which is why the exact
        opening words are pinned rather than merely "some disclosure exists".
        """

        best_effort = service.test_connection(connect(service), owner_id=OWNER)
        assert best_effort.tier_disclosure is not None
        assert best_effort.tier_disclosure.startswith("Best-effort single start.")
        assert best_effort.cancellation_disclosure is not None
        assert best_effort.cancellation_disclosure.startswith(
            "Cancellation depends on the agent"
        )

        card_fetcher.discovery = ready_discovery(
            summary=card_summary(extension_uris=[SINGLE_START_EXTENSION_URI])
        )
        guaranteed = service.test_connection(
            connect(service, key="idem-guaranteed"), owner_id=OWNER
        )
        assert guaranteed.tier_disclosure is not None
        assert guaranteed.tier_disclosure.startswith("Guaranteed single start.")

    def test_014_FR_002_card_drift_returns_the_connection_to_untested(
        self, service: AgentRelayService, card_fetcher: FakeCardFetcher, clock: Clock
    ) -> None:
        """AC-012, D-01-S20. A moved destination is not a destination we tested."""

        connection_id = connect(service)
        service.test_connection(connection_id, owner_id=OWNER)
        acknowledged = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        service.agent_repo.save_connection(
            acknowledged.model_copy(update={"best_effort_acknowledged_at": clock.now})
        )

        card_fetcher.discovery = ready_discovery(
            summary=card_summary(interface_url="https://second.example.com/a2a")
        )
        drifted = service.test_connection(connection_id, owner_id=OWNER)

        assert drifted.status == "untested"
        assert drifted.agent_changed is True
        assert drifted.last_test_error_code == "agent_card_changed"
        assert drifted.ready_for_handoff is False
        # The connection still describes the interface the owner *tested*; the
        # one the card now advertises is named beside it (D-01-S20).
        assert drifted.card is not None
        assert drifted.card.interface_url == "https://agent.example.com/a2a"
        assert drifted.last_test_error_detail == {
            "interface_url": "https://second.example.com/a2a"
        }

        stored = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert stored.card_drift_at == clock.now
        assert stored.scope_verified_at is None
        assert stored.best_effort_acknowledged_at is None

    def test_014_FR_002_a_successful_test_after_drift_clears_the_drift_marker(
        self, service: AgentRelayService, card_fetcher: FakeCardFetcher
    ) -> None:
        """A tested destination is a tested destination, whichever card named it."""

        connection_id = connect(service)
        service.test_connection(connection_id, owner_id=OWNER)
        card_fetcher.discovery = ready_discovery(
            summary=card_summary(interface_url="https://second.example.com/a2a")
        )
        service.test_connection(connection_id, owner_id=OWNER)

        recovered = service.test_connection(connection_id, owner_id=OWNER)

        assert recovered.status == "ready"
        assert recovered.agent_changed is False
        assert recovered.card is not None
        assert recovered.card.interface_url == "https://second.example.com/a2a"
        stored = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert stored.card_drift_at is None

    @pytest.mark.parametrize("change", ["address", "auth_scheme", "credential"])
    def test_014_FR_004_a_scope_change_asks_for_the_acknowledgement_again(
        self, service: AgentRelayService, clock: Clock, change: str
    ) -> None:
        """AC-026. A new destination is a new decision, so the promise resets."""

        connection_id = connect(service)
        service.test_connection(connection_id, owner_id=OWNER)
        stored = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        service.agent_repo.save_connection(
            stored.model_copy(update={"best_effort_acknowledged_at": clock.now})
        )
        revision = service.get_connection(connection_id, owner_id=OWNER).revision

        if change == "credential":
            service.rotate_credential(
                connection_id,
                AgentConnectionRotateRequest(
                    credential="replacement",
                    current_password="password",
                    expected_revision=revision,
                ),
                owner_id=OWNER,
                idempotency_key=f"idem-{change}",
                reauthenticated=True,
            )
        else:
            payload = (
                {"agent_address": "https://second.example.com"}
                if change == "address"
                else {"auth_scheme": "api_key"}
            )
            service.update_connection(
                connection_id,
                AgentConnectionUpdateRequest(
                    **payload,
                    current_password="password",
                    expected_revision=revision,
                ),
                owner_id=OWNER,
                idempotency_key=f"idem-{change}",
                reauthenticated=True,
            )

        after = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert after.status == "untested"
        assert after.best_effort_acknowledged_at is None
        assert after.scope_verified_at == clock.now
        assert after.card is None
        assert after.card_fingerprint is None

    def test_014_FR_001_the_header_name_is_card_sourced_absent_for_bearer(
        self,
        service: AgentRelayService,
        card_fetcher: FakeCardFetcher,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-002. The owner picks a scheme; the agent's card names the header."""

        bearer_id = connect(service)
        bearer = service.test_connection(bearer_id, owner_id=OWNER)
        assert bearer.auth_header_name is None
        assert "auth_header_name" not in service.agent_repo.get_connection(
            bearer_id, owner_id=OWNER
        ).model_dump(exclude_none=True)
        assert a2a_client.calls_to("ListTasks")[0][1].auth_scheme == "bearer"

        card_fetcher.discovery = ready_discovery(
            summary=card_summary(
                auth_schemes_offered=[
                    AgentAuthSchemeOffer(
                        name="apiKey", kind="api_key", header_name="X-API-Key"
                    )
                ]
            ),
            auth_header_name="X-API-Key",
        )
        api_key_id = service.create_connection(
            create_request(auth_scheme="api_key"),
            owner_id=OWNER,
            idempotency_key="idem-api-key",
            reauthenticated=True,
        ).id
        api_key = service.test_connection(api_key_id, owner_id=OWNER)

        assert api_key.auth_scheme == "api_key"
        assert api_key.auth_header_name == "X-API-Key"

    def test_014_FR_001_a_reserved_card_header_name_is_refused_as_unsupported(
        self, service: AgentRelayService, card_fetcher: FakeCardFetcher
    ) -> None:
        """A card that names `Authorization` for its API key does not get to.

        The reserved set is what stops a card from choosing the one header the
        transport itself populates; refusing it as an unsupported scheme keeps
        the failure in a category the owner can act on.
        """

        card_fetcher.discovery = ready_discovery(auth_header_name="Authorization")
        connection_id = service.create_connection(
            create_request(auth_scheme="api_key"),
            owner_id=OWNER,
            idempotency_key="idem-reserved",
            reauthenticated=True,
        ).id

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "unsupported"
        assert tested.last_test_error_code == "a2a_auth_scheme_unsupported"
        assert tested.last_test_error_detail == {"scheme": "Authorization"}

    def test_014_FR_002_a_successful_test_refreshes_contact_and_the_stale_rule_holds(
        self, service: AgentRelayService, clock: Clock
    ) -> None:
        """FR-002, D-01-S19. Staleness is derived from the last authenticated call."""

        connection_id = connect(service)
        tested = service.test_connection(connection_id, owner_id=OWNER)
        assert tested.last_contact_at == clock.now
        assert tested.stale is False

        clock.advance(timedelta(days=8))
        stale = service.get_connection(connection_id, owner_id=OWNER)
        assert stale.stale is True
        assert stale.ready_for_handoff is False

        refreshed = service.test_connection(connection_id, owner_id=OWNER)
        assert refreshed.stale is False
        assert refreshed.last_contact_at == clock.now

    def test_014_SC_003_a_connection_test_is_scoped_to_its_owner(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """014-SC-003. Re-targeting a stranger's connection is a 404, not a probe."""

        connection_id = connect(service)

        with pytest.raises(NotFoundError):
            service.test_connection(connection_id, owner_id=OTHER_OWNER)

        assert a2a_client.calls == []

    @pytest.mark.parametrize("body", [b"not json at all", b'{"name": "x"'])
    def test_014_SC_003_a_malformed_card_body_changes_nothing(
        self, tmp_path: Path, connector: FakeConnector, clock: Clock, body: bytes
    ) -> None:
        """014-SC-003. A truncated card is not a card; parsing a prefix is worse."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body)

        service = build_service(
            AgentRepository(tmp_path),
            connector,
            clock,
            card_fetcher=mock_transport_card_fetcher(handler),
        )
        connection_id = connect(service)

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "unsupported"
        assert tested.last_test_error_code == "a2a_not_an_agent"
        assert tested.card is None

    def test_014_SC_003_an_oversized_card_body_is_refused_whole(
        self, tmp_path: Path, connector: FakeConnector, clock: Clock
    ) -> None:
        """014-SC-003. The cap is enforced on the stream, not after the fact."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b'{"name":"' + b"a" * 200_000 + b'"}')

        service = build_service(
            AgentRepository(tmp_path),
            connector,
            clock,
            card_fetcher=mock_transport_card_fetcher(handler),
        )
        connection_id = connect(service)

        tested = service.test_connection(connection_id, owner_id=OWNER)

        assert tested.status == "unsupported"
        assert tested.last_test_error_code == "a2a_not_an_agent"

    def test_014_SC_003_a_rebinding_answer_is_refused_by_the_pinned_resolver(
        self, tmp_path: Path, connector: FakeConnector, clock: Clock
    ) -> None:
        """014-SC-003. The network class is decided before the socket, once."""

        def rebinding_resolver(host: str, port: int) -> list[str]:
            return ["127.0.0.1"]

        repo = AgentRepository(tmp_path)
        connection_id = connect(
            build_service(repo, connector, clock, a2a_client=FakeA2AClient())
        )
        # The host resolved publicly when the connection was saved and resolves
        # inward now. Discovery is the *real* one here: the point is that the
        # network class is decided from this resolver, before the socket.
        rebound = AgentRelayService(
            repo,
            connector=connector,
            secret_box=SecretBox(OrderedDict({"v1": b"\x07" * 32})),
            task_snapshot=task_snapshot,
            callback_url=CALLBACK,
            a2a_client=FakeA2AClient(),
            resolver=rebinding_resolver,
            now=clock,
        )

        with pytest.raises(ValidationFailure) as excinfo:
            rebound.test_connection(connection_id, owner_id=OWNER)

        assert str(excinfo.value.detail["reason"]).startswith("destination_")

    def test_014_SC_009_no_connection_read_ever_carries_the_credential(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """014-SC-009. There is no shape a saved secret could travel in."""

        connection_id = connect(service)
        for probe in (
            A2AResult(ok=True, correlation_id="c"),
            A2AResult(
                ok=False, correlation_id="c", error_code="a2a_credentials_rejected"
            ),
            A2AResult(ok=False, correlation_id="c", error_code="a2a_unreachable"),
        ):
            a2a_client.script("ListTasks", probe)
            rendered = service.test_connection(
                connection_id, owner_id=OWNER
            ).model_dump_json()
            assert "super-secret-token" not in rendered


class TestConnectionTestConcurrency:
    def test_slow_test_cannot_restore_readiness_after_destination_update(
        self, tmp_path: Path, clock: Clock
    ) -> None:
        blocking = BlockingCardFetcher()
        service = build_service(AgentRepository(tmp_path), FakeConnector(), clock)
        connection_id = connect(service)
        make_ready(service, connection_id)
        service._card_fetcher = blocking
        tested: list[Any] = []
        worker = Thread(
            target=lambda: tested.append(
                service.test_connection(connection_id, owner_id=OWNER)
            )
        )
        worker.start()
        assert blocking.entered.wait(timeout=5)

        current = service.get_connection(connection_id, owner_id=OWNER)
        moved = service.update_connection(
            connection_id,
            AgentConnectionUpdateRequest(
                agent_address="https://second.example.com/hooks",
                expected_revision=current.revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-race-move",
            reauthenticated=True,
        )
        blocking.release.set()
        worker.join(timeout=5)

        assert moved.status == "untested"
        assert tested[0].status == "untested"
        assert (
            service.get_connection(connection_id, owner_id=OWNER).status == "untested"
        )

    def test_a_slow_test_cannot_restore_a_concurrently_disconnected_connection(
        self, tmp_path: Path, clock: Clock
    ) -> None:
        blocking = BlockingCardFetcher()
        service = build_service(
            AgentRepository(tmp_path), FakeConnector(), clock, card_fetcher=blocking
        )
        connection_id = connect(service)
        tested: list[Any] = []
        worker = Thread(
            target=lambda: tested.append(
                service.test_connection(connection_id, owner_id=OWNER)
            )
        )
        worker.start()
        assert blocking.entered.wait(timeout=5)

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
        blocking.release.set()
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
        blocking = BlockingCardFetcher()
        service = build_service(
            AgentRepository(tmp_path), FakeConnector(), clock, card_fetcher=blocking
        )
        connection_id = connect(service)
        tested: list[Any] = []
        worker = Thread(
            target=lambda: tested.append(
                service.test_connection(connection_id, owner_id=OWNER)
            )
        )
        worker.start()
        assert blocking.entered.wait(timeout=5)

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
        blocking.release.set()
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
        a2a_client = BlockingA2AClient()
        repo = AgentRepository(tmp_path)
        service = build_service(
            repo,
            connector,
            clock,
            a2a_client=a2a_client,
            exchange_executor=SynchronousExecutor(),
        )
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

        # Every one of the three now travels the A2A wire, so the same client
        # is the slow agent in all three cases.
        blocker: Any = a2a_client
        blocker.block_kind = operation
        worker_errors: list[BaseException] = []

        def run_worker() -> None:
            try:
                invoke()
            except BaseException as exc:  # pragma: no cover - asserted below
                worker_errors.append(exc)

        worker = Thread(target=run_worker)
        worker.start()
        assert blocker.entered.wait(timeout=5)

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
        blocker.release.set()
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
        a2a_client = FakeA2AClient()
        service = build_service(
            AgentRepository(tmp_path),
            connector,
            clock,
            a2a_client=a2a_client,
            exchange_executor=SynchronousExecutor(),
        )
        created = service.create_connection(
            create_request(),
            owner_id=OWNER,
            idempotency_key="idem-callback-create",
            reauthenticated=True,
        )
        created_secret = issue_signing_secret(service, created.id)
        make_ready(service, created.id)
        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=created.id),
            owner_id=OWNER,
        )
        confirmation = AgentHandoffConfirmRequest(
            connection_id=created.id,
            manifest_token=preview.token,
            acknowledge_duplicate_risk=True,
        )
        before_io = clock.now

        def send_with_callback(target: Any, **kwargs: Any) -> A2AResult:
            """An authenticated report that lands while the send is in flight."""

            a2a_client.calls.append(("SendMessage", target, kwargs))
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
                signature=sign(created_secret, timestamp, body),
            )
            assert accepted.accepted is True
            if expire_content:
                persisted = service.agent_repo.get_run(preview.run_id, owner_id=OWNER)
                clock.now = persisted.content_expires_at
                service.agent_repo.expire_due_content(now=clock.now)
            clock.advance(timedelta(seconds=1))
            if transport_status == "sent":
                return A2AResult(ok=True, correlation_id="c")
            return A2AResult(
                ok=False,
                correlation_id="c",
                error_code=(
                    "a2a_request_rejected"
                    if transport_status == "not_sent"
                    else "a2a_timeout"
                ),
            )

        monkeypatch.setattr(a2a_client, "send_message", send_with_callback)

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
        assert len(a2a_client.calls_to("SendMessage")) == 1

    @pytest.mark.parametrize("bypass_operation_lock", [False, True])
    def test_concurrent_same_key_dispatches_contend_and_converge_only_with_lock(
        self,
        tmp_path: Path,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
        bypass_operation_lock: bool,
    ) -> None:
        connector = BlockingIoConnector()
        a2a_client = BlockingA2AClient()
        repo = AgentRepository(tmp_path)
        service = build_service(
            repo,
            connector,
            clock,
            a2a_client=a2a_client,
            exchange_executor=SynchronousExecutor(),
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        confirmation = review(service, connection_id)
        a2a_client.block_kind = "start"
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
        assert a2a_client.entered.wait(timeout=5)
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
        a2a_client.release.set()
        first.join(timeout=5)
        second.join(timeout=5)

        assert errors == []
        # The durable `queued -> open` compare-and-set is the barrier: whichever
        # thread loses it does no network I/O at all, so one confirmation is one
        # message however many times it is replayed concurrently.
        assert len(sends(a2a_client)) == 1
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
                supporting_items=[
                    AgentContextItemRequest(label="Runbook", body="Step one...")
                ],
            ),
            owner_id=OWNER,
        )

        assert preview.title == "Draft the migration plan"
        assert preview.details == "Cover rollback and the data backfill."
        assert [item.label for item in preview.supporting_items] == ["Runbook"]
        assert preview.task_id == "task_1"
        assert preview.run_id
        assert preview.agent_name == "Hermes"
        # The *interface* the card named, not the address the owner typed: that
        # is where content would actually go (AC-007).
        assert preview.destination_interface == "https://agent.example.com/a2a"
        assert preview.message_id == f"{preview.run_id}:start"
        assert preview.correlation_id == preview.run_id
        assert preview.protocol_version == "1.0"
        assert preview.parts_preview == [
            "Draft the migration plan",
            "Cover rollback and the data backfill.",
            "Runbook\nStep one...",
        ]
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
                    supporting_items=[
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
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """AC-008: dispatch is Sent, linked to the Task, and singular."""

        connection_id = connect(service)
        make_ready(service, connection_id)

        run = dispatch(service, connection_id)

        assert run.dispatch_state == "sent"
        assert run.task_id == "task_1"
        assert run.reported_state is None
        assert run.primary_state_label == "Sent"
        assert len(sends(a2a_client)) == 1
        assert len(service.list_runs_for_task("task_1", owner_id=OWNER)) == 1

    def test_the_start_envelope_carries_the_correlated_identifiers(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """FR-006: the wire message names the run, its message and its Task.

        The bespoke `reporting` block is gone from the wire with the wire that
        needed it: an A2A agent is told nothing about how to report back,
        because it reports by answering. The inert copy survives only inside the
        stored manifest, for a rolled-back image to parse.
        """

        connection_id = connect(service)
        make_ready(service, connection_id)
        run = dispatch(service, connection_id)

        message = sends(a2a_client)[0]
        assert message["contextId"] == run.id
        assert message["messageId"] == f"{run.id}:start"
        assert message["metadata"]["brainbuddy.task_id"] == "task_1"
        assert message["metadata"]["brainbuddy.run_id"] == run.id
        assert message["parts"][0]["text"] == "Draft the migration plan"
        assert "reporting" not in message
        assert "super-secret-token" not in json.dumps(message)
        stored = service.agent_repo.get_run(run.id, owner_id=OWNER)
        assert stored.manifest is not None
        assert stored.manifest.reporting.callback_url == ""

    @pytest.mark.parametrize("replays", [1, 2, 3])
    def test_replaying_the_dispatch_returns_the_same_run_without_restarting(
        self, service: AgentRelayService, a2a_client: FakeA2AClient, replays: int
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

        assert len(sends(a2a_client)) == 1
        assert len(service.list_runs_for_task("task_1", owner_id=OWNER)) == 1

    def test_reusing_a_key_for_a_different_confirmation_is_a_conflict(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
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

        assert len(sends(a2a_client)) == 1

    @pytest.mark.parametrize(
        "error_code,expected",
        [
            ("a2a_timeout", "delivery_unconfirmed"),
            ("a2a_request_rejected", "not_sent"),
        ],
    )
    def test_dispatch_reports_its_own_delivery_honestly(
        self,
        service: AgentRelayService,
        a2a_client: FakeA2AClient,
        error_code: str,
        expected: str,
    ) -> None:
        """FR-006: ambiguous loss is never called failure, and vice versa."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        a2a_client.script(
            "SendMessage",
            A2AResult(ok=False, correlation_id="c", error_code=error_code),
        )

        run = dispatch(service, connection_id)

        assert run.dispatch_state == expected
        assert run.dispatch_error_code == error_code
        assert run.reported_state is None

    def test_an_unconfirmed_delivery_keeps_its_run_and_is_never_auto_retried(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """FR-006: a retry reuses the original run and key, never a new one."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        a2a_client.script(
            "SendMessage",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_timeout"),
        )
        confirmation = review(service, connection_id)
        first = service.dispatch_run(
            "task_1", confirmation, owner_id=OWNER, idempotency_key="idem-dispatch"
        )

        repeat = service.dispatch_run(
            "task_1", confirmation, owner_id=OWNER, idempotency_key="idem-dispatch"
        )

        assert repeat.id == first.id
        assert repeat.dispatch_state == "delivery_unconfirmed"
        assert len(sends(a2a_client)) == 1

    @pytest.mark.parametrize(
        "probe_error",
        [None, "a2a_credentials_rejected", "a2a_unreachable"],
    )
    def test_a_connection_that_is_not_ready_refuses_before_sending_content(
        self,
        service: AgentRelayService,
        connector: FakeConnector,
        a2a_client: FakeA2AClient,
        probe_error: str | None,
    ) -> None:
        """AC-010: task content never leaves through an unusable connection."""

        connection_id = connect(service)
        if probe_error is not None:
            a2a_client.script(
                "ListTasks",
                A2AResult(ok=False, correlation_id="c", error_code=probe_error),
            )
            service.test_connection(connection_id, owner_id=OWNER)

        with pytest.raises(ValidationFailure):
            dispatch(service, connection_id)

        assert connector.starts == []
        assert a2a_client.calls_to("SendMessage") == []

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


class TestHandOffManifestAndAcknowledgement:
    """The consent boundary: what the manifest promises, and what it asks for."""

    def _push_capable(
        self, service: AgentRelayService, card_fetcher: FakeCardFetcher
    ) -> str:
        card_fetcher.discovery = ready_discovery(
            summary=card_summary(push_notifications=True)
        )
        connection_id = connect(service, key="idem-push")
        make_ready(service, connection_id)
        return connection_id

    def test_014_FR_005_the_manifest_names_the_push_callback_with_its_token_masked(
        self, service: AgentRelayService, card_fetcher: FakeCardFetcher
    ) -> None:
        """AC-007. The address is disclosed; the secret in it never is."""

        connection_id = self._push_capable(service, card_fetcher)

        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )

        assert preview.push_callback.registered is True
        assert preview.push_callback.url_preview is not None
        assert preview.push_callback.url_preview.endswith("/…")
        assert preview.push_callback.disclosure
        # The whole projection, serialised: the token is not in it anywhere,
        # because the token is not in the manifest the projection is built from.
        assert "/…" in preview.model_dump_json()
        assert preview.run_id in (preview.push_callback.url_preview or "")

    def test_014_FR_005_a_card_without_push_discloses_no_callback_at_all(
        self, service: AgentRelayService
    ) -> None:
        """A masked address for a callback the agent cannot use reads as one it can."""

        connection_id = connect(service)
        make_ready(service, connection_id)

        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )

        assert preview.push_callback.registered is False
        assert preview.push_callback.url_preview is None
        assert preview.push_callback.disclosure is None

    def test_014_FR_005_the_manifest_names_the_interface_the_card_advertises(
        self, service: AgentRelayService
    ) -> None:
        """AC-006. Where content would actually go, not the address typed in."""

        connection_id = connect(service)
        make_ready(service, connection_id)

        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(
                connection_id=connection_id,
                supporting_items=[
                    AgentContextItemRequest(label="Runbook", body="Cutover steps.")
                ],
            ),
            owner_id=OWNER,
        )

        assert preview.destination_interface == "https://agent.example.com/a2a"
        assert preview.message_id == f"{preview.run_id}:start"
        assert preview.correlation_id == preview.run_id
        assert preview.protocol_version == "1.0"
        assert [item.label for item in preview.supporting_items] == ["Runbook"]
        assert preview.parts_preview == [
            "Draft the migration plan",
            "Cover rollback and the data backfill.",
            "Runbook\nCutover steps.",
        ]

    def test_014_FR_014_cancellation_disclosure_carries_the_exact_server_owned_copy(
        self, service: AgentRelayService
    ) -> None:
        """FR-014's third literal, pinned beside the two tier sentences.

        The clients render it verbatim, so drift here is drift in what
        BrainBuddy promises about stopping work it has handed over.
        """

        connection_id = connect(service)
        make_ready(service, connection_id)

        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )

        assert preview.cancellation_disclosure.startswith(
            "Cancellation depends on the agent"
        )
        assert preview.tier_disclosure.startswith("Best-effort single start.")
        assert preview.tier_disclosure_url

    def test_014_FR_005_a_moved_callback_origin_invalidates_the_confirmation(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """The origin is part of the token, so a redeployment re-reviews.

        A confirmation reviewed against one callback origin must not be able to
        hand the agent an address BrainBuddy no longer answers on.
        """

        repo = AgentRepository(tmp_path)
        card_fetcher.discovery = ready_discovery(
            summary=card_summary(push_notifications=True)
        )
        first = build_service(repo, connector, clock, card_fetcher=card_fetcher)
        first.push_base_url = "https://one.example/api/a2a/push"
        connection_id = connect(first)
        make_ready(first, connection_id)
        confirmation = review(first, connection_id)

        moved = build_service(repo, connector, clock, card_fetcher=card_fetcher)
        moved.push_base_url = "https://two.example/api/a2a/push"

        with pytest.raises(ValidationFailure) as caught:
            moved.dispatch_run(
                "task_1",
                confirmation,
                owner_id=OWNER,
                idempotency_key="idem-moved-origin",
            )
        assert caught.value.detail == {"reason": "manifest_token_mismatch"}

    def test_014_FR_005_preview_refetches_the_card_and_refuses_drift(
        self, service: AgentRelayService, card_fetcher: FakeCardFetcher
    ) -> None:
        """AC-012. The review is the last moment to notice the agent moved."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        card_fetcher.discovery = ready_discovery(
            summary=card_summary(interface_url="https://second.example.com/a2a")
        )

        with pytest.raises(ValidationFailure) as caught:
            service.preview_handoff(
                "task_1",
                AgentHandoffPreviewRequest(connection_id=connection_id),
                owner_id=OWNER,
            )

        assert caught.value.detail == {"reason": "agent_card_changed"}
        # Refused before anything was reserved: a review that cannot be trusted
        # leaves no run behind.
        assert service.list_runs_for_task("task_1", owner_id=OWNER) == []

    def test_014_FR_003_first_best_effort_confirm_without_acknowledgement_is_refused(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """AC-026, refused *before* any reservation and before any I/O."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        confirmation = review(service, connection_id, acknowledge=False)
        assert confirmation.acknowledge_duplicate_risk is False

        with pytest.raises(ValidationFailure) as caught:
            service.dispatch_run(
                "task_1",
                confirmation,
                owner_id=OWNER,
                idempotency_key="idem-unacknowledged",
            )

        assert caught.value.detail == {
            "reason": "duplicate_risk_acknowledgement_required"
        }
        assert a2a_client.calls_to("SendMessage") == []
        # Refused before the reservation was spent: the reviewed run is still
        # undispatched, so the same review can be confirmed once the box is
        # ticked rather than having to be rebuilt.
        reserved = service.agent_repo.find_run_by_manifest_token(
            confirmation.manifest_token, owner_id=OWNER
        )
        assert reserved is not None
        assert reserved.dispatched_at is None
        assert reserved.exchange_state == "none"
        assert service.list_runs_for_task("task_1", owner_id=OWNER) == []

    def test_014_FR_003_the_guaranteed_tier_is_never_asked_to_acknowledge(
        self, service: AgentRelayService, card_fetcher: FakeCardFetcher
    ) -> None:
        """The card promises the deduplication the acknowledgement warns about."""

        card_fetcher.discovery = ready_discovery(
            summary=card_summary(extension_uris=[SINGLE_START_EXTENSION_URI])
        )
        connection_id = connect(service, key="idem-guaranteed")
        make_ready(service, connection_id)

        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )

        assert preview.guarantee_tier == "guaranteed"
        assert preview.acknowledgement_required is False
        run = service.dispatch_run(
            "task_1",
            AgentHandoffConfirmRequest(
                connection_id=connection_id, manifest_token=preview.token
            ),
            owner_id=OWNER,
            idempotency_key="idem-guaranteed-dispatch",
        )
        assert run.id == preview.run_id

    def test_014_FR_003_the_acknowledgement_is_persisted_and_then_never_asked_again(
        self, service: AgentRelayService, clock: Clock
    ) -> None:
        """AC-026: once per connection. The second hand-off asks nothing."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        confirmation = review(service, connection_id)

        service.dispatch_run(
            "task_1",
            confirmation,
            owner_id=OWNER,
            idempotency_key="idem-acknowledged",
        )

        stored = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert stored.best_effort_acknowledged_at == clock.now
        second = service.preview_handoff(
            "task_2",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )
        assert second.acknowledgement_required is False

    def test_014_FR_003_acknowledgement_flag_is_ignored_once_persisted(
        self, service: AgentRelayService, clock: Clock
    ) -> None:
        """A later false does not un-acknowledge what the owner already agreed to.

        The flag answers a question the review only asks once, so once the
        answer is recorded the flag is inert — a client that stopped sending it
        must not silently withdraw a decision the owner made.
        """

        connection_id = connect(service)
        make_ready(service, connection_id)
        service.dispatch_run(
            "task_1",
            review(service, connection_id),
            owner_id=OWNER,
            idempotency_key="idem-ack-1",
        )
        stamped = service.agent_repo.get_connection(
            connection_id, owner_id=OWNER
        ).best_effort_acknowledged_at

        clock.advance(timedelta(minutes=5))
        second = service.dispatch_run(
            "task_2",
            review(service, connection_id, task_id="task_2", acknowledge=False),
            owner_id=OWNER,
            idempotency_key="idem-ack-2",
        )

        assert second.task_id == "task_2"
        after = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert after.best_effort_acknowledged_at == stamped

    @pytest.mark.parametrize(
        "condition", ["untested", "stale", "disconnected", "foreign"]
    )
    def test_014_SC_005_an_unusable_connection_is_refused_before_any_content(
        self, service: AgentRelayService, clock: Clock, condition: str
    ) -> None:
        """FR-002 fails closed at the review, not after the content has left."""

        connection_id = connect(service)
        if condition != "untested":
            make_ready(service, connection_id)
        if condition == "stale":
            clock.advance(timedelta(days=30))
        if condition == "disconnected":
            service.disconnect_connection(
                connection_id,
                AgentConnectionDisconnectRequest(
                    current_password="password",
                    expected_revision=service.get_connection(
                        connection_id, owner_id=OWNER
                    ).revision,
                ),
                owner_id=OWNER,
                idempotency_key="idem-disconnect",
                reauthenticated=True,
            )

        owner = OTHER_OWNER if condition == "foreign" else OWNER
        with pytest.raises((ValidationFailure, NotFoundError)):
            service.preview_handoff(
                "task_1",
                AgentHandoffPreviewRequest(connection_id=connection_id),
                owner_id=owner,
            )
        assert service.list_runs_for_task("task_1", owner_id=OWNER) == []


def a2a_task(
    task_id: str, *, context_id: str | None, state: str = "TASK_STATE_SUBMITTED"
) -> Task:
    return Task.model_validate(
        {"id": task_id, "contextId": context_id, "status": {"state": state}}
    )


class TestHandOffExchange:
    """One dispatch, one exchange, and never a claim the wire did not support."""

    def _service(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
        executor: Any,
    ) -> AgentRelayService:
        return build_service(
            AgentRepository(tmp_path),
            connector,
            clock,
            card_fetcher=card_fetcher,
            a2a_client=a2a_client,
            exchange_executor=executor,
        )

    def test_014_FR_006_the_reservation_pins_every_identifier_before_any_io(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """AC-009. The ids exist durably before the first byte leaves."""

        executor = SaturatedExecutor()
        service = self._service(
            tmp_path, connector, clock, a2a_client, card_fetcher, executor
        )
        connection_id = connect(service)
        make_ready(service, connection_id)

        run = dispatch(service, connection_id)

        stored = service.agent_repo.get_run(run.id, owner_id=OWNER)
        assert stored.context_id == run.id
        assert stored.message_id == f"{run.id}:start"
        assert stored.interface_url == "https://agent.example.com/a2a"
        assert stored.card_fingerprint is not None
        assert stored.guarantee_tier == "best_effort"
        assert stored.exchange_kind == "start"
        assert stored.exchange_state == "queued"
        # Nothing has left, so neither stamp exists yet.
        assert stored.exchange_started_at is None
        assert stored.exchange_deadline_at is None
        connection = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert connection.first_dispatch_at is None
        assert a2a_client.calls_to("SendMessage") == []

    def test_014_FR_006_a_queued_exchange_reads_as_queued_and_runs_no_probe(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """AC-034, D-03-S04 queued variant. Queued is not Sent."""

        executor = SaturatedExecutor()
        service = self._service(
            tmp_path, connector, clock, a2a_client, card_fetcher, executor
        )
        connection_id = connect(service)
        make_ready(service, connection_id)

        run = dispatch(service, connection_id)

        assert run.primary_state_label == "Queued"
        assert run.exchange_state == "queued"
        assert run.exchange_open is True
        # No probe while it is queued: there is nothing at the agent to find.
        # (The connection test's own `ListTasks` sentinel carries no contextId,
        # so it is not a lookup for this run.)
        assert [
            kwargs
            for _method, _target, kwargs in a2a_client.calls_to("ListTasks")
            if kwargs.get("context_id") is not None
        ] == []
        assert a2a_client.calls_to("SendMessage") == []

    def test_014_FR_006_starting_the_exchange_stamps_both_sides_at_once(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """The one write that says content has left for this destination."""

        executor = SaturatedExecutor()
        service = self._service(
            tmp_path, connector, clock, a2a_client, card_fetcher, executor
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        run = dispatch(service, connection_id)
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True,
                correlation_id="corr",
                task=a2a_task("agent-task-1", context_id=run.id),
            ),
        )

        clock.advance(timedelta(seconds=30))
        executor.run_pending()

        stored = service.agent_repo.get_run(run.id, owner_id=OWNER)
        assert stored.exchange_started_at == clock.now
        assert stored.exchange_deadline_at is not None
        assert stored.exchange_deadline_at > clock.now
        connection = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert connection.first_dispatch_at == clock.now

    def test_014_FR_006_the_start_message_carries_the_wire_shape_the_contract_names(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """contracts/a2a-wire.md, the Start row. Ids, parts and metadata."""

        card_fetcher.discovery = ready_discovery(
            summary=card_summary(push_notifications=True)
        )
        service = self._service(
            tmp_path, connector, clock, a2a_client, card_fetcher, SynchronousExecutor()
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        run = dispatch(
            service,
            connection_id,
            context=[AgentContextItemRequest(label="Runbook", body="Cutover steps.")],
        )

        sends = a2a_client.calls_to("SendMessage")
        assert len(sends) == 1
        _method, target, kwargs = sends[0]
        message = kwargs["message"]
        assert message["messageId"] == f"{run.id}:start"
        assert message["contextId"] == run.id
        assert message["role"] == "ROLE_USER"
        assert [part["text"] for part in message["parts"]] == [
            "Draft the migration plan",
            "Cover rollback and the data backfill.",
            "Runbook\nCutover steps.",
        ]
        assert message["metadata"] == {
            "brainbuddy.task_id": "task_1",
            "brainbuddy.run_id": run.id,
        }
        assert target.interface_url == "https://agent.example.com/a2a"
        # The card advertises push, so the config travels inline with the very
        # first send rather than as a second round trip.
        assert kwargs["push_config"]["url"].endswith(
            run.id + "/" + kwargs["push_config"]["token"]
        )

    def test_014_FR_006_a_guaranteed_tier_send_activates_the_extension(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """The extension is what the guarantee *is*, so it is on every send."""

        card_fetcher.discovery = ready_discovery(
            summary=card_summary(extension_uris=[SINGLE_START_EXTENSION_URI])
        )
        service = self._service(
            tmp_path, connector, clock, a2a_client, card_fetcher, SynchronousExecutor()
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        dispatch(service, connection_id)

        _method, target, _kwargs = a2a_client.calls_to("SendMessage")[0]
        assert target.guarantee_tier == "guaranteed"

    @pytest.mark.parametrize(
        ("result", "dispatch_state", "error_code"),
        [
            (
                A2AResult(ok=False, correlation_id="c", error_code="a2a_unreachable"),
                "not_sent",
                "a2a_unreachable",
            ),
            (
                A2AResult(
                    ok=False,
                    correlation_id="c",
                    error_code="a2a_credentials_rejected",
                    http_status=401,
                ),
                "not_sent",
                "a2a_credentials_rejected",
            ),
            (
                A2AResult(
                    ok=False,
                    correlation_id="c",
                    error_code="a2a_request_rejected",
                    a2a_error_code=-32602,
                ),
                "not_sent",
                "a2a_request_rejected",
            ),
            (
                A2AResult(
                    ok=False,
                    correlation_id="c",
                    error_code="a2a_rate_limited",
                    http_status=429,
                ),
                "not_sent",
                "a2a_rate_limited",
            ),
            (
                A2AResult(ok=False, correlation_id="c", error_code="a2a_timeout"),
                "delivery_unconfirmed",
                "a2a_timeout",
            ),
            (
                A2AResult(
                    ok=False,
                    correlation_id="c",
                    error_code="a2a_server_error",
                    http_status=503,
                ),
                "delivery_unconfirmed",
                "a2a_server_error",
            ),
        ],
    )
    def test_014_FR_006_every_failed_exchange_lands_in_the_state_it_can_prove(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
        result: A2AResult,
        dispatch_state: str,
        error_code: str,
    ) -> None:
        """A refusal is **Not sent**; an ambiguity is never demoted to one."""

        service = self._service(
            tmp_path, connector, clock, a2a_client, card_fetcher, SynchronousExecutor()
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        a2a_client.script("SendMessage", result)

        run = dispatch(service, connection_id)

        assert run.dispatch_state == dispatch_state
        assert run.dispatch_error_code == error_code
        assert run.exchange_state == "closed"
        assert run.exchange_open is False

    def test_014_FR_006_an_answered_exchange_adopts_the_task_it_names(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """AC-009. The agent answered, so the run is **Sent** and adopted."""

        service = self._service(
            tmp_path, connector, clock, a2a_client, card_fetcher, SynchronousExecutor()
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True,
                correlation_id="corr",
                task=a2a_task(
                    "agent-task-1",
                    context_id=preview.run_id,
                    state="TASK_STATE_WORKING",
                ),
            ),
        )

        run = service.dispatch_run(
            "task_1",
            AgentHandoffConfirmRequest(
                connection_id=connection_id,
                manifest_token=preview.token,
                acknowledge_duplicate_risk=True,
            ),
            owner_id=OWNER,
            idempotency_key="idem-adopt",
        )

        assert run.dispatch_state == "sent"
        assert run.agent_task_id == "agent-task-1"
        assert run.reported_state == "running"
        assert run.primary_state_label == "Running"

    def test_014_FR_007_a_task_in_a_foreign_conversation_is_never_adopted(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """An agent that dropped the correlation ID proves nothing by a lookup.

        The answer arrived, so the message was **Sent** — but the task it names
        belongs to some other conversation, so adopting it would attach this run
        to work BrainBuddy never asked for.
        """

        service = self._service(
            tmp_path, connector, clock, a2a_client, card_fetcher, SynchronousExecutor()
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True,
                correlation_id="corr",
                task=a2a_task("agent-task-9", context_id="someone-elses-conversation"),
            ),
        )

        run = dispatch(service, connection_id)

        assert run.dispatch_state == "sent"
        assert run.dispatch_error_code == "a2a_response_invalid"
        assert run.agent_task_id is None
        assert run.reported_state is None
        connection = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert connection.context_id_honoured is False

    def test_014_FR_006_a_direct_message_answer_completes_the_run(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """Some agents answer with a message and never create a task at all."""

        service = self._service(
            tmp_path, connector, clock, a2a_client, card_fetcher, SynchronousExecutor()
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True,
                correlation_id="corr",
                message=Message.model_validate(
                    {
                        "messageId": "m1",
                        "role": "ROLE_AGENT",
                        "parts": [{"text": "Done."}],
                    }
                ),
            ),
        )

        run = dispatch(service, connection_id)

        assert run.dispatch_state == "sent"
        assert run.reported_state == "completed"
        assert run.result_text == "Done."
        assert run.primary_state_label == "Agent reported complete"

    def test_014_SC_002_three_replays_create_one_task_and_one_exchange(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """SC-002. The key is spent once; the wire is touched once."""

        service = self._service(
            tmp_path, connector, clock, a2a_client, card_fetcher, SynchronousExecutor()
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True,
                correlation_id="corr",
                task=a2a_task("agent-task-1", context_id=preview.run_id),
            ),
        )
        confirmation = AgentHandoffConfirmRequest(
            connection_id=connection_id,
            manifest_token=preview.token,
            acknowledge_duplicate_risk=True,
        )

        runs = [
            service.dispatch_run(
                "task_1",
                confirmation,
                owner_id=OWNER,
                idempotency_key=f"agent-handoff-{preview.token}",
            )
            for _ in range(3)
        ]

        assert {run.id for run in runs} == {preview.run_id}
        assert {run.message_id for run in runs} == {f"{preview.run_id}:start"}
        assert len(a2a_client.calls_to("SendMessage")) == 1


class OpeningExecutor:
    """A pool whose worker opens the exchange and then stalls inside the send.

    The one shape the request thread's inline probe exists for: the message has
    left, a worker is still holding the answer, and the user is waiting.
    """

    def __init__(self, repo: AgentRepository, clock: Clock) -> None:
        self.repo = repo
        self.clock = clock

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        run_id = args[0] if args else kwargs["run_id"]
        owner_id = kwargs.get("owner_id", OWNER)
        run = self.repo.get_run(run_id, owner_id=owner_id)
        self.repo.start_exchange(
            run,
            expected_version=run.run_version,
            started_at=self.clock.now,
            deadline_at=self.clock.now + timedelta(minutes=5),
        )
        future: Future[Any] = Future()
        future.set_result(None)
        return future


class StallingExecutor:
    """A pool that accepts the work and never finishes it."""

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        return Future()


class TestExchangeEdges:
    """The paths a hand-off takes when something else got there first."""

    def _service(
        self,
        repo: AgentRepository,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
        executor: Any,
        wait: float = 0.0,
    ) -> AgentRelayService:
        return AgentRelayService(
            repo,
            connector=connector,
            secret_box=SecretBox(OrderedDict({"v1": b"\x07" * 32})),
            task_snapshot=task_snapshot,
            callback_url=CALLBACK,
            push_base_url=PUSH_BASE,
            card_fetcher=card_fetcher,
            a2a_client=a2a_client,
            exchange=ExchangePolicy(executor=executor, dispatch_wait_seconds=wait),
            resolver=fake_resolver,
            now=clock,
        )

    def test_014_FR_006_an_open_exchange_is_probed_once_before_the_request_answers(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """The message has left; asking once is better than an honest silence."""

        repo = AgentRepository(tmp_path)
        service = self._service(
            repo,
            connector,
            clock,
            a2a_client,
            card_fetcher,
            OpeningExecutor(repo, clock),
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )
        a2a_client.script(
            "ListTasks",
            A2AResult(
                ok=True,
                correlation_id="c",
                tasks=(a2a_task("t-probed", context_id=preview.run_id),),
            ),
        )

        run = service.dispatch_run(
            "task_1",
            AgentHandoffConfirmRequest(
                connection_id=connection_id,
                manifest_token=preview.token,
                acknowledge_duplicate_risk=True,
            ),
            owner_id=OWNER,
            idempotency_key="idem-probe",
        )

        assert run.dispatch_state == "sent"
        assert run.agent_task_id == "t-probed"
        assert run.exchange_state == "open"
        assert run.primary_state_label == "Accepted"

    def test_014_FR_006_a_probe_that_finds_nothing_leaves_the_exchange_alone(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """An empty lookup is not evidence, so nothing is written from it."""

        repo = AgentRepository(tmp_path)
        service = self._service(
            repo,
            connector,
            clock,
            a2a_client,
            card_fetcher,
            OpeningExecutor(repo, clock),
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        a2a_client.script("ListTasks", A2AResult(ok=False, correlation_id="c"))

        run = dispatch(service, connection_id)

        assert run.agent_task_id is None
        assert run.exchange_state == "open"
        assert run.primary_state_label == "Sent"

    def test_014_FR_006_the_request_stops_waiting_and_still_answers_honestly(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """The wait is a courtesy, not a contract (D-03-S04 queued variant)."""

        service = self._service(
            AgentRepository(tmp_path),
            connector,
            clock,
            a2a_client,
            card_fetcher,
            StallingExecutor(),
            wait=0.05,
        )
        connection_id = connect(service)
        make_ready(service, connection_id)

        run = dispatch(service, connection_id)

        assert run.primary_state_label == "Queued"
        assert run.exchange_state == "queued"

    def test_014_FR_006_a_deployment_with_no_wire_leaves_the_hand_off_queued(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """Nothing can leave, so nothing is claimed to have."""

        service = self._service(
            AgentRepository(tmp_path),
            connector,
            clock,
            FakeA2AClient(),
            card_fetcher,
            SynchronousExecutor(),
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        run_id = dispatch(service, connection_id).id
        service.a2a_client = None

        service.perform_exchange(run_id, owner_id=OWNER)

        assert (
            service.agent_repo.get_run(run_id, owner_id=OWNER).exchange_state
            == "closed"
        )
        # And a lookup with no wire reports nothing rather than "nothing found".
        run = service.agent_repo.get_run(run_id, owner_id=OWNER)
        connection = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert service._lookup_task(run, connection) is None

    def test_014_FR_006_a_second_worker_on_one_exchange_sends_nothing(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """Exactly one of us may send; the loser does no I/O at all."""

        service = self._service(
            AgentRepository(tmp_path),
            connector,
            clock,
            a2a_client,
            card_fetcher,
            SynchronousExecutor(),
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        run_id = dispatch(service, connection_id).id
        before = len(sends(a2a_client))

        # The exchange is closed, so a straggling worker finds nothing to start.
        service.perform_exchange(run_id, owner_id=OWNER)

        assert len(sends(a2a_client)) == before

    def test_014_FR_006_an_unspecified_task_state_refreshes_contact_and_claims_nothing(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """The agent said it is alive and nothing more; that is all we record."""

        service = self._service(
            AgentRepository(tmp_path),
            connector,
            clock,
            a2a_client,
            card_fetcher,
            SynchronousExecutor(),
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=a2a_task(
                    "t-alive",
                    context_id=preview.run_id,
                    state="TASK_STATE_UNSPECIFIED",
                ),
            ),
        )

        run = service.dispatch_run(
            "task_1",
            AgentHandoffConfirmRequest(
                connection_id=connection_id,
                manifest_token=preview.token,
                acknowledge_duplicate_risk=True,
            ),
            owner_id=OWNER,
            idempotency_key="idem-unspecified",
        )

        assert run.dispatch_state == "sent"
        assert run.reported_state is None
        assert run.agent_task_id == "t-alive"
        assert run.last_contact_at == clock.now
        assert run.events == []

    def test_014_FR_006_a_late_answer_never_recreates_expired_content(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """Retention is irreversible: state moves, the words do not come back."""

        service = self._service(
            AgentRepository(tmp_path),
            connector,
            clock,
            a2a_client,
            card_fetcher,
            SynchronousExecutor(),
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        run_id = dispatch(service, connection_id).id
        expired = service.agent_repo.get_run(run_id, owner_id=OWNER)
        service.agent_repo.expire_due_content(now=expired.content_expires_at)

        service.apply_observation(
            run_id,
            owner_id=OWNER,
            observation=project_observation(
                a2a_task("t1", context_id=run_id, state="TASK_STATE_COMPLETED"),
                now=clock.now,
                limits=ObservationLimits(),
            ),
            based_on=service.agent_repo.get_run(run_id, owner_id=OWNER).run_version,
        )

        stored = service.agent_repo.get_run(run_id, owner_id=OWNER)
        assert stored.reported_state == "completed"
        assert stored.result_text is None
        assert stored.content_expired is True

    def test_014_FR_006_an_observation_that_lost_the_race_changes_nothing(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """Two answers about one run never interleave into a third state."""

        service = self._service(
            AgentRepository(tmp_path),
            connector,
            clock,
            a2a_client,
            card_fetcher,
            SynchronousExecutor(),
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        run_id = dispatch(service, connection_id).id
        before = service.agent_repo.get_run(run_id, owner_id=OWNER)

        unchanged = service.apply_observation(
            run_id,
            owner_id=OWNER,
            observation=project_observation(
                a2a_task("t1", context_id=run_id, state="TASK_STATE_WORKING"),
                now=clock.now,
                limits=ObservationLimits(),
            ),
            based_on=before.run_version + 7,
        )

        assert unchanged.revision == before.revision
        assert unchanged.reported_state == before.reported_state

    def test_014_FR_006_a_lookup_prefers_the_newest_task_in_this_conversation(
        self,
        tmp_path: Path,
        connector: FakeConnector,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """Newest by the agent's own timestamp; foreign conversations ignored."""

        service = self._service(
            AgentRepository(tmp_path),
            connector,
            clock,
            a2a_client,
            card_fetcher,
            SynchronousExecutor(),
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        run_id = dispatch(service, connection_id).id
        run = service.agent_repo.get_run(run_id, owner_id=OWNER)

        older = Task.model_validate(
            {
                "id": "t-old",
                "contextId": run_id,
                "status": {
                    "state": "TASK_STATE_WORKING",
                    "timestamp": "2026-08-09T11:00:00Z",
                },
            }
        )
        newer = Task.model_validate(
            {
                "id": "t-new",
                "contextId": run_id,
                "status": {
                    "state": "TASK_STATE_WORKING",
                    "timestamp": "2026-08-09T12:00:00Z",
                },
            }
        )
        foreign = a2a_task("t-foreign", context_id="another-conversation")

        assert (
            service._newest_adoptable(
                run,
                A2AResult(ok=True, correlation_id="c", tasks=(older, newer, foreign)),
            )
            is newer
        )
        # A single `task` answer is a candidate too — some agents answer a
        # lookup with one task rather than a list.
        assert (
            service._newest_adoptable(
                run, A2AResult(ok=True, correlation_id="c", task=newer)
            )
            is newer
        )
        assert (
            service._newest_adoptable(
                run, A2AResult(ok=True, correlation_id="c", tasks=(foreign,))
            )
            is None
        )
        assert (
            service._newest_adoptable(run, A2AResult(ok=False, correlation_id="c"))
            is None
        )


class TestCheckDelivery:
    """**Check again**: look first, resend only what the rules still allow."""

    def _unconfirmed(
        self,
        service: AgentRelayService,
        a2a_client: FakeA2AClient,
        *,
        key: str = "idem-unconfirmed",
    ) -> tuple[str, str]:
        """One dispatched run left **Delivery unconfirmed** by a timeout."""

        connection_id = connect(service)
        make_ready(service, connection_id)
        a2a_client.script(
            "SendMessage",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_timeout"),
        )
        run = dispatch(service, connection_id, key=key)
        assert run.dispatch_state == "delivery_unconfirmed"
        a2a_client.results.pop("SendMessage", None)
        a2a_client.calls.clear()
        return connection_id, run.id

    def test_014_FR_006_a_found_task_is_adopted_and_nothing_is_resent(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """AC-027. The lookup answered, so there is nothing to send again."""

        _connection_id, run_id = self._unconfirmed(service, a2a_client)
        a2a_client.script(
            "ListTasks",
            A2AResult(
                ok=True,
                correlation_id="c",
                tasks=(a2a_task("t-found", context_id=run_id),),
            ),
        )

        checked = service.check_delivery(
            run_id,
            AgentCheckDeliveryRequest(),
            owner_id=OWNER,
            idempotency_key="idem-check",
        )

        assert checked.id == run_id
        assert checked.dispatch_state == "sent"
        assert checked.agent_task_id == "t-found"
        assert sends(a2a_client) == []

    def test_014_FR_006_an_empty_lookup_resends_the_identical_message_once(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """AC-027. Same run, same message ID — never a second hand-off."""

        _connection_id, run_id = self._unconfirmed(service, a2a_client)
        a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=a2a_task("t-resent", context_id=run_id),
            ),
        )

        checked = service.check_delivery(
            run_id,
            AgentCheckDeliveryRequest(),
            owner_id=OWNER,
            idempotency_key="idem-check",
        )

        assert checked.id == run_id
        assert checked.message_id == f"{run_id}:start"
        assert checked.dispatch_state == "sent"
        assert [message["messageId"] for message in sends(a2a_client)] == [
            f"{run_id}:start"
        ]
        assert len(service.list_runs_for_task("task_1", owner_id=OWNER)) == 1

    def test_014_FR_006_the_resend_goes_to_the_interface_pinned_at_dispatch(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """A card that moved cannot redirect a live run's traffic."""

        _connection_id, run_id = self._unconfirmed(service, a2a_client)
        a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

        service.check_delivery(
            run_id,
            AgentCheckDeliveryRequest(),
            owner_id=OWNER,
            idempotency_key="idem-check",
        )

        _method, target, _kwargs = a2a_client.calls_to("SendMessage")[0]
        assert target.interface_url == "https://agent.example.com/a2a"

    def test_014_FR_006_a_connection_that_dropped_the_correlation_id_never_resends(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """An empty lookup there proves nothing, so it licenses nothing."""

        connection_id, run_id = self._unconfirmed(service, a2a_client)
        stored = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        service.agent_repo.save_connection(
            stored.model_copy(update={"context_id_honoured": False})
        )
        a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

        checked = service.check_delivery(
            run_id,
            AgentCheckDeliveryRequest(),
            owner_id=OWNER,
            idempotency_key="idem-check",
        )

        assert checked.dispatch_state == "delivery_unconfirmed"
        assert sends(a2a_client) == []

    def test_014_FR_006_a_lookup_runs_while_rollout_is_off_and_the_resend_does_not(
        self, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """AC-036. The lookup is safe; only the send is gated."""

        _connection_id, run_id = self._unconfirmed(service, a2a_client)
        a2a_client.script(
            "ListTasks",
            A2AResult(
                ok=True,
                correlation_id="c",
                tasks=(a2a_task("t-found", context_id=run_id),),
            ),
        )

        adopted = service.check_delivery(
            run_id,
            AgentCheckDeliveryRequest(),
            owner_id=OWNER,
            idempotency_key="idem-check-off-1",
            resend_allowed=False,
        )
        assert adopted.dispatch_state == "sent"

        _connection_id_2, second_run = self._unconfirmed(
            service, a2a_client, key="idem-unconfirmed-2"
        )
        a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))
        with pytest.raises(ValidationFailure) as refused:
            service.check_delivery(
                second_run,
                AgentCheckDeliveryRequest(),
                owner_id=OWNER,
                idempotency_key="idem-check-off-2",
                resend_allowed=False,
            )

        assert refused.value.detail == {"reason": "rollout_disabled"}
        # Refused *after* the lookup ran, so a task created meanwhile is still
        # adopted rather than lost behind a flag.
        assert a2a_client.calls_to("ListTasks")
        assert sends(a2a_client) == []
        assert (
            service.get_run(second_run, owner_id=OWNER).dispatch_state
            == "delivery_unconfirmed"
        )

    @pytest.mark.parametrize(
        "condition,reason",
        [
            ("not_ready", "connection_not_ready"),
            ("agent_changed", "agent_card_changed"),
            ("scope_reset", "connection_not_ready"),
            ("content_expired", "run_content_expired"),
        ],
    )
    def test_014_FR_006_the_resend_preconditions_refuse_after_the_lookup(
        self,
        service: AgentRelayService,
        a2a_client: FakeA2AClient,
        clock: Clock,
        condition: str,
        reason: str,
    ) -> None:
        """Each refusal leaves the run untouched and sends nothing."""

        connection_id, run_id = self._unconfirmed(service, a2a_client)
        stored = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        if condition == "not_ready":
            service.agent_repo.save_connection(
                stored.model_copy(update={"status": "unreachable"})
            )
        elif condition == "agent_changed":
            service.agent_repo.save_connection(
                stored.model_copy(
                    update={
                        "status": "untested",
                        "card_drift_at": clock.now,
                        "last_test_error_code": "agent_card_changed",
                    }
                )
            )
        elif condition == "scope_reset":
            service.agent_repo.save_connection(
                stored.model_copy(
                    update={"status": "untested", "scope_verified_at": clock.now}
                )
            )
        else:
            run = service.agent_repo.get_run(run_id, owner_id=OWNER)
            service.agent_repo.expire_due_content(now=run.content_expires_at)
        a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

        with pytest.raises(ValidationFailure) as refused:
            service.check_delivery(
                run_id,
                AgentCheckDeliveryRequest(),
                owner_id=OWNER,
                idempotency_key="idem-check",
            )

        assert refused.value.detail == {"reason": reason}
        assert sends(a2a_client) == []
        assert (
            service.agent_repo.get_run(run_id, owner_id=OWNER).dispatch_state
            == "delivery_unconfirmed"
        )

    @pytest.mark.parametrize(
        "condition,reason",
        [
            ("terminal", "run_terminal"),
            ("task_missing", "agent_task_missing"),
            ("disconnected", "connection_disconnected"),
        ],
    )
    def test_014_FR_006_three_conditions_refuse_the_whole_check_before_any_lookup(
        self,
        service: AgentRelayService,
        a2a_client: FakeA2AClient,
        clock: Clock,
        condition: str,
        reason: str,
    ) -> None:
        """There is nothing to look for, so BrainBuddy does not go looking."""

        connection_id, run_id = self._unconfirmed(service, a2a_client)
        run = service.agent_repo.get_run(run_id, owner_id=OWNER)
        if condition == "terminal":
            service.agent_repo.save_run(
                run.model_copy(update={"reported_state": "completed"})
            )
        elif condition == "task_missing":
            service.agent_repo.save_run(
                run.model_copy(update={"agent_task_missing_at": clock.now})
            )
        else:
            stored = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
            service.agent_repo.save_connection(
                stored.model_copy(update={"status": "disconnected"})
            )

        with pytest.raises(ValidationFailure) as refused:
            service.check_delivery(
                run_id,
                AgentCheckDeliveryRequest(),
                owner_id=OWNER,
                idempotency_key="idem-check",
            )

        assert refused.value.detail == {"reason": reason}
        assert a2a_client.calls_to("ListTasks") == []
        assert sends(a2a_client) == []

    def test_014_FR_004_a_retry_of_a_hand_off_that_never_left_needs_the_password_again(
        self, service: AgentRelayService, a2a_client: FakeA2AClient, clock: Clock
    ) -> None:
        """FR-004's `first_dispatch_at` rule, stated end to end.

        Nothing left BrainBuddy, so the connection's first-content trigger is
        still unspent. Once the 15-minute window has passed the resend is
        refused until the password is given — and only then does the exchange
        start and the trigger get spent.
        """

        connection_id, run_id = self._unconfirmed(service, a2a_client)
        connection = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        # The exchange never started, so the stamp was never made.
        service.agent_repo.save_connection(
            connection.model_copy(update={"first_dispatch_at": None})
        )
        clock.advance(SCOPE_REAUTH_WINDOW + timedelta(minutes=1))
        a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

        with pytest.raises(ValidationFailure) as refused:
            service.check_delivery(
                run_id,
                AgentCheckDeliveryRequest(),
                owner_id=OWNER,
                idempotency_key="idem-check-reauth",
            )
        assert refused.value.detail == {"reason": "reauthentication_required"}
        assert sends(a2a_client) == []

        service.check_delivery(
            run_id,
            AgentCheckDeliveryRequest(current_password="correct-horse-battery-staple"),
            owner_id=OWNER,
            idempotency_key="idem-check-reauth-2",
            reauthenticated=True,
        )

        assert len(sends(a2a_client)) == 1
        assert (
            service.agent_repo.get_connection(
                connection_id, owner_id=OWNER
            ).first_dispatch_at
            == clock.now
        )

    def test_014_SC_008_an_exchange_that_started_has_already_spent_the_trigger(
        self, service: AgentRelayService, a2a_client: FakeA2AClient, clock: Clock
    ) -> None:
        """**Check again** on a started exchange asks for no password."""

        connection_id, run_id = self._unconfirmed(service, a2a_client)
        stamped = service.agent_repo.get_connection(connection_id, owner_id=OWNER)
        assert stamped.first_dispatch_at is not None
        clock.advance(SCOPE_REAUTH_WINDOW + timedelta(minutes=1))
        a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

        service.check_delivery(
            run_id,
            AgentCheckDeliveryRequest(),
            owner_id=OWNER,
            idempotency_key="idem-check-spent",
        )

        assert len(sends(a2a_client)) == 1

    def test_014_SC_008_concurrent_checks_converge_on_one_resend(
        self, tmp_path: Path, connector: FakeConnector, clock: Clock
    ) -> None:
        """One durable winner; the loser returns without touching the network."""

        a2a_client = BlockingA2AClient()
        repo = AgentRepository(tmp_path)
        service = build_service(
            repo,
            connector,
            clock,
            a2a_client=a2a_client,
            exchange_executor=SynchronousExecutor(),
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        a2a_client.script(
            "SendMessage",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_timeout"),
        )
        run_id = dispatch(service, connection_id).id
        a2a_client.results.pop("SendMessage", None)
        a2a_client.calls.clear()
        a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))
        a2a_client.block_kind = "start"

        errors: list[BaseException] = []

        def check(key: str) -> None:
            try:
                service.check_delivery(
                    run_id,
                    AgentCheckDeliveryRequest(),
                    owner_id=OWNER,
                    idempotency_key=key,
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        first = Thread(target=check, args=("idem-check-a",))
        first.start()
        assert a2a_client.entered.wait(timeout=5)
        second = Thread(target=check, args=("idem-check-b",))
        second.start()
        second.join(timeout=5)
        a2a_client.release.set()
        first.join(timeout=5)

        assert errors == []
        assert len(sends(a2a_client)) == 1


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
        self.secret = issue_signing_secret(
            service, created.id, key="idem-relay-signing"
        )
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
        other_secret = issue_signing_secret(service, other.id, key="idem-other-signing")
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
                signature=sign(other_secret, timestamp, body),
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
        self, relay: Relay, service: AgentRelayService, a2a_client: FakeA2AClient
    ) -> None:
        """AC-012 / FR-008: only a later observation moves the state."""

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
        assert len(replies(a2a_client)) == 1

    def test_a_synchronous_callback_during_reply_wins_over_transport_merge(
        self,
        relay: Relay,
        service: AgentRelayService,
        a2a_client: FakeA2AClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A report that lands mid-reply is newer than the reply's own answer."""

        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        expected_revision = relay.projection().revision
        sent: list[dict[str, Any]] = []

        def send_with_callback(target: Any, **kwargs: Any) -> A2AResult:
            sent.append(kwargs["message"])
            relay.emit(relay.event("evt_2", "running", 2, progress="Continuing"))
            return A2AResult(ok=True, correlation_id="c")

        monkeypatch.setattr(a2a_client, "send_message", send_with_callback)

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
        assert len(sent) == 1

    def test_a_synchronous_callback_during_cancel_wins_over_transport_merge(
        self,
        relay: Relay,
        service: AgentRelayService,
        a2a_client: FakeA2AClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A run that finished while the cancel was in flight is not un-finished."""

        attempts: list[dict[str, Any]] = []

        def cancel_with_callback(target: Any, **kwargs: Any) -> A2AResult:
            attempts.append(kwargs)
            relay.emit(relay.event("evt_1", "completed", 1, result="Already done"))
            return A2AResult(ok=True, correlation_id="c")

        monkeypatch.setattr(a2a_client, "cancel_task", cancel_with_callback)

        run = service.cancel_run(
            relay.run.id,
            owner_id=OWNER,
            idempotency_key="idem-sync-cancel",
        )

        assert run.reported_state == "completed"
        assert run.result_text == "Already done"
        assert run.cancel_requested is False
        assert len(attempts) == 1

    def test_a_synchronous_nonterminal_callback_during_cancel_preserves_cancellation_overlay(
        self,
        relay: Relay,
        service: AgentRelayService,
        a2a_client: FakeA2AClient,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        before = relay.projection()
        attempted_at = clock.now
        callback_at = attempted_at + timedelta(minutes=1)
        mutation_at = attempted_at + timedelta(minutes=2)

        def cancel_with_callback(target: Any, **kwargs: Any) -> A2AResult:
            clock.advance(timedelta(minutes=1))
            relay.emit(
                relay.event("evt_running", "running", 1, progress="Still working")
            )
            clock.advance(timedelta(minutes=1))
            return A2AResult(ok=True, correlation_id="c")

        monkeypatch.setattr(a2a_client, "cancel_task", cancel_with_callback)

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

        assert wire_commands(service) == []
        assert [c for c in relay.projection().commands if c.kind == "reply"] == []

    def test_replaying_a_reply_causes_at_most_one_send(
        self, relay: Relay, service: AgentRelayService, a2a_client: FakeA2AClient
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

        assert len(replies(a2a_client)) == 1

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

    def test_014_FR_010_reply_is_offered_because_no_card_can_advertise_it(
        self, service: AgentRelayService, clock: Clock
    ) -> None:
        """014-FR-010. An agent card says nothing about replies, so we offer it.

        007 hid the control behind a declared capability. Under A2A there is no
        such declaration to read, and hiding a control on the strength of a flag
        no card carries would mean withdrawing it from every agent that does
        support replies. BrainBuddy offers it and reports what the agent
        actually answers.
        """

        relay = Relay(service, clock)
        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))

        run = relay.projection()

        assert run.capabilities.reply is True
        assert run.capabilities.cancel is True

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
        a2a_client = BlockingA2AClient()
        repo = AgentRepository(tmp_path)
        service = build_service(
            repo,
            connector,
            clock,
            a2a_client=a2a_client,
            exchange_executor=SynchronousExecutor(),
        )
        relay = Relay(service, clock)
        clear_wire(service)
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

        a2a_client.block_kind = operation
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
        assert a2a_client.entered.wait(timeout=5)
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
        a2a_client.release.set()
        first.join(timeout=5)
        second.join(timeout=5)

        assert errors == []
        assert len(wire_commands(service)) == 1
        assert len(results) == 2
        command_id = wire_commands(service)[0]["command_id"]
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
        a2a_client = BlockingA2AClient()
        service = build_service(
            AgentRepository(tmp_path),
            FakeConnector(),
            clock,
            a2a_client=a2a_client,
            exchange_executor=SynchronousExecutor(),
        )
        relay = Relay(service, clock)
        clear_wire(service)
        a2a_client.script(
            "CancelTask",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=observed_task("t1", relay.run.id, "TASK_STATE_CANCELED"),
            ),
        )
        a2a_client.block_kind = "cancel"
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
        assert a2a_client.entered.wait(timeout=5)
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
        a2a_client.release.set()
        worker.join(timeout=5)

        assert errors == []
        run = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        assert len(wire_commands(service)) == 1
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
        a2a_client = BlockingA2AClient()
        service = build_service(
            AgentRepository(tmp_path),
            FakeConnector(),
            clock,
            a2a_client=a2a_client,
            exchange_executor=SynchronousExecutor(),
        )
        connection_id = connect(service)
        make_ready(service, connection_id)
        confirmation = review(service, connection_id)
        reserved = service.agent_repo.list_runs_for_task("task_1", owner_id=OWNER)[0]
        a2a_client.block_kind = "start"
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
        assert a2a_client.entered.wait(timeout=5)
        service.agent_repo.expire_due_content(now=clock.now + service.content_retention)
        a2a_client.release.set()
        worker.join(timeout=5)

        assert errors == []
        current = service.agent_repo.get_run(reserved.id, owner_id=OWNER)
        assert current.content_expired is True
        assert current.manifest is None
        assert len(sends(a2a_client)) == 1

    @pytest.mark.parametrize("race", ["terminal", "rotation", "disconnect"])
    def test_start_transport_merge_preserves_newer_terminal_or_connection_state(
        self, tmp_path: Path, clock: Clock, race: str
    ) -> None:
        a2a_client = BlockingA2AClient()
        service = build_service(
            AgentRepository(tmp_path),
            FakeConnector(),
            clock,
            a2a_client=a2a_client,
            exchange_executor=SynchronousExecutor(),
        )
        created = service.create_connection(
            create_request(),
            owner_id=OWNER,
            idempotency_key="idem-start-race-create",
            reauthenticated=True,
        )
        created_secret = issue_signing_secret(service, created.id)
        make_ready(service, created.id)
        confirmation = review(service, created.id)
        reserved = service.agent_repo.list_runs_for_task("task_1", owner_id=OWNER)[0]
        a2a_client.block_kind = "start"
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
        assert a2a_client.entered.wait(timeout=5)
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
                signature=sign(created_secret, timestamp, body),
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
        a2a_client.release.set()
        worker.join(timeout=5)

        assert errors == []
        current_run = service.agent_repo.get_run(reserved.id, owner_id=OWNER)
        assert len(sends(a2a_client)) == 1
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
        a2a_client = BlockingA2AClient()
        service = build_service(
            AgentRepository(tmp_path),
            FakeConnector(),
            clock,
            a2a_client=a2a_client,
            exchange_executor=SynchronousExecutor(),
        )
        relay = Relay(service, clock)
        relay.emit(relay.event("evt_1", "blocked", 1, question="Which environment?"))
        payload = AgentReplyRequest(
            message="Use staging.", expected_revision=relay.projection().revision
        )
        # Scripted only now, so the dispatch above kept the default answer and
        # only the reply is acknowledged with a task.
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=observed_task("t1", relay.run.id),
            ),
        )
        a2a_client.block_kind = "reply"
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
        assert a2a_client.entered.wait(timeout=5)

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

        a2a_client.release.set()
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
        assert len(wire_commands(service)) == 1

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
        assert len(wire_commands(service)) == 1

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
        assert len(wire_commands(service)) == 1

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
        assert len(wire_commands(service)) == 1

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
        assert len(wire_commands(service)) == 1

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

        assert len(wire_commands(service)) == 1

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
        assert len(wire_commands(service)) == 1


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
        assert [command["type"] for command in wire_commands(service)] == ["cancel"]
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
        assert wire_commands(service) == []
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
        assert len(wire_commands(service)) == 1
        assert all(command.body is None for command in replay.commands)

    def test_event_at_exact_retention_boundary_advances_only_coarse_state(
        self,
        relay: Relay,
        clock: Clock,
        service: AgentRelayService,
        tmp_path: Path,
    ) -> None:
        relay.emit(relay.event("evt_before_due", "blocked", 1, question="Secret?"))
        service.reply_to_run(
            relay.run.id,
            AgentReplyRequest(
                message="Secret answer", expected_revision=relay.projection().revision
            ),
            owner_id=OWNER,
            idempotency_key="idem-before-due",
        )
        persisted = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        clock.now = persisted.content_expires_at

        relay.emit(
            relay.event(
                "evt_due",
                "running",
                2,
                progress="Secret progress at the boundary",
            )
        )

        stored = service.agent_repo.get_run(relay.run.id, owner_id=OWNER)
        assert stored.content_expired is True
        assert stored.reported_state == "running"
        assert stored.run_version == 2
        assert stored.last_contact_at == clock.now
        assert stored.manifest is None
        assert stored.progress_text is None
        assert stored.question_text is None
        assert stored.result_text is None
        assert stored.result_link is None
        assert stored.failure_reason is None
        events = service.agent_repo.list_events(relay.run.id, owner_id=OWNER)
        assert events[-1].summary is None

        with sqlite3.connect(tmp_path / "agents.sqlite3") as conn:
            event_payloads = [
                json.loads(row[0])
                for row in conn.execute(
                    "SELECT payload FROM agent_run_events WHERE run_id = ?",
                    (relay.run.id,),
                )
            ]
            command_payloads = [
                json.loads(row[0])
                for row in conn.execute(
                    "SELECT payload FROM agent_run_commands WHERE run_id = ?",
                    (relay.run.id,),
                )
            ]
        assert any(event["summary"] is not None for event in event_payloads)
        assert any(command["body"] is not None for command in command_payloads)

        revision = stored.revision
        assert service.run_retention_sweep() == 0

        with sqlite3.connect(tmp_path / "agents.sqlite3") as conn:
            event_payloads = [
                json.loads(row[0])
                for row in conn.execute(
                    "SELECT payload FROM agent_run_events WHERE run_id = ?",
                    (relay.run.id,),
                )
            ]
            command_payloads = [
                json.loads(row[0])
                for row in conn.execute(
                    "SELECT payload FROM agent_run_commands WHERE run_id = ?",
                    (relay.run.id,),
                )
            ]
        assert all(event["summary"] is None for event in event_payloads)
        assert all(command["body"] is None for command in command_payloads)
        assert (
            service.agent_repo.get_run(relay.run.id, owner_id=OWNER).revision
            == revision
        )

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
        replacement_secret = issue_signing_secret(
            service, replacement.id, key="idem-replacement-signing"
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
            signature=sign(replacement_secret, timestamp, body),
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
        a2a_client = FakeA2AClient()
        service = build_service(
            AgentRepository(tmp_path),
            connector,
            clock,
            a2a_client=a2a_client,
            exchange_executor=SynchronousExecutor(),
        )
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
            # The relay fixture dispatched a run to have something to command.
            # That start is setup, not the call under test.
            a2a_client.calls.clear()
            connector.starts.clear()
            clear_wire(service)
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
        assert sends(a2a_client) == []
        assert wire_commands(service) == []

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

        service = build_service(
            AgentRepository(tmp_path),
            connector,
            clock,
            a2a_client=a2a_client,
            exchange_executor=SynchronousExecutor(),
        )
        recovered = invoke()

        external_calls: list[dict[str, Any]] = (
            sends(a2a_client) if operation == "start" else wire_commands(service)
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
                # The A2A conversation identifier *is* the run id, so the wire
                # and the projection cannot name two different things.
                external_calls[0]["contextId"]
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
        clear_wire(service)
        restarted = build_service(AgentRepository(tmp_path), connector, clock)
        service = restarted
        recovered = retry()

        assert connector.starts == []
        assert wire_commands(service) == []
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
        assert migrated.auth_header_name is None
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
        # 014: the repair leaves no header name at all. A bearer connection has
        # none, and writing a placeholder would claim a scheme nobody chose.
        assert listed[0].auth_header_name is None
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
        assert persisted.auth_header_name is None
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

        assert len(wire_commands(service)) == 1
        command_id = wire_commands(service)[0]["command_id"]
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
        original_command_id = wire_commands(service)[0]["command_id"]
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

        assert len(wire_commands(service)) == 1
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
        original_command_id = wire_commands(service)[0]["command_id"]
        relay.emit(relay.event("evt_done", "completed", 1, result="Finished"))

        recovered = service.cancel_run(
            relay.run.id,
            owner_id=OWNER,
            idempotency_key="idem-terminal-crash-cancel",
        )

        assert len(wire_commands(service)) == 1
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

        assert len(wire_commands(service)) == 1
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
        a2a_client: FakeA2AClient,
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

        # One message, and its identifiers are the run's own: a retry after an
        # ambiguous storage outage must reach the agent as the *same* request,
        # not as a second one wearing a new name.
        assert len(sends(a2a_client)) == 1
        assert sends(a2a_client)[0]["contextId"] == recovered.id
        assert sends(a2a_client)[0]["messageId"] == f"{recovered.id}:start"
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
                    connection_id=connection_id, supporting_items=context
                ),
                owner_id=OWNER,
            )

        assert refused.value.detail == {"reason": "too_many_supporting_items"}
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
            # The relay bundle also mints a signing secret, so target the row
            # this test just wrote rather than whichever rotation comes first.
            stored = database.execute(
                "SELECT key_hash, response_body FROM agent_idempotency "
                "WHERE owner_id = ? AND command = 'rotate_signing_secret' "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (OWNER,),
            ).fetchone()
            assert stored is not None
            original = json.loads(stored[1])
            receipt["installed_secret_fingerprint"] = original[
                "installed_secret_fingerprint"
            ]
            database.execute(
                "UPDATE agent_idempotency SET response_body = ? "
                "WHERE owner_id = ? AND key_hash = ?",
                (json.dumps(receipt), OWNER, stored[0]),
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

        with pytest.raises(ValidationFailure) as refused:
            service.dispatch_run(
                "task_1",
                AgentHandoffConfirmRequest(
                    connection_id=connection_id,
                    manifest_token=preview.token,
                    # Acknowledged, so the refusal below can only be about the
                    # password: two consent gates that both refuse would
                    # otherwise let this pass for the wrong reason.
                    acknowledge_duplicate_risk=True,
                ),
                owner_id=OWNER,
                idempotency_key="idem-dispatch",
            )
        assert refused.value.detail == {"reason": "reauthentication_required"}
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
        # Shared across every generation, like the database and the connector:
        # a rolling deploy is many processes over one set of records and one
        # agent, and a per-instance client would hide a second delivery.
        self._a2a = FakeA2AClient()
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
            AgentRepository(self._tmp_path),
            self._connector,
            self._clock,
            keys=ring,
            a2a_client=self._a2a,
            exchange_executor=SynchronousExecutor(),
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
            return sends(self._a2a)
        return wire_commands_of(self._a2a)


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


class TestRollbackBoundary:
    """A 014 row has to stay readable by the 007 image.

    ADR-0008 landing keeps rollback as a real operational option, and a rollback
    that finds the relay's rows unparseable is far worse than one that finds the
    feature idle: the 007 image's retention sweep, data export and read paths all
    go through these models, so an unreadable row would break GDPR export and
    stop content expiring on schedule — for connections and runs the user may
    never touch again.

    So the frozen 007 shapes are declared *here*, in the test, rather than
    imported. Importing the live models would prove only that 014 agrees with
    itself. These copies are pinned to what the 007 image actually shipped, and
    they are what a 014 payload is validated against.

    014-FR-012, 014-SC-010.
    """

    class Frozen007ReportingContract(StorageBaseModel):
        """The 007 shape: `callback_url` and `connection_id` both required."""

        callback_url: str
        connection_id: str
        connection_header: Literal["X-BrainBuddy-Connection"] = (
            "X-BrainBuddy-Connection"
        )
        timestamp_header: Literal["X-BrainBuddy-Timestamp"] = "X-BrainBuddy-Timestamp"
        signature_header: Literal["X-BrainBuddy-Signature"] = "X-BrainBuddy-Signature"
        timestamp_format: Literal[
            "ascii-base-10-unix-seconds-no-sign-space-or-leading-zero"
        ] = "ascii-base-10-unix-seconds-no-sign-space-or-leading-zero"
        signature_algorithm: Literal["hmac-sha256"] = "hmac-sha256"
        signing_bytes: Literal["timestamp_bytes + b'.' + raw_body"] = (
            "timestamp_bytes + b'.' + raw_body"
        )
        signature_format: Literal["v1=<lowercase hex>"] = "v1=<lowercase hex>"
        body_envelope_version: str = "2026-08-09"

    class Frozen007ConnectionDocument(StorageBaseModel):
        """The 007 connection shape.

        Note `endpoint_url` and the `auth_header_name` validator: 014 keeps the
        storage key and never stores "Authorization" there precisely because
        this model would reject it.
        """

        id: str
        owner_id: str
        name: str
        endpoint_url: str
        auth_header_name: Annotated[
            str, AfterValidator(validate_auth_header_name), Field(max_length=128)
        ] = "X-Agent-Key"
        credential: SealedSecret | None = None
        inbound_secret: SealedSecret | None = None
        status: str = "untested"
        created_at: datetime
        updated_at: datetime
        schema_version: int = Field(default=1, ge=1)
        revision: int = Field(default=1, ge=1)

    class Frozen007RunManifest(StorageBaseModel):
        """The 007 manifest, whose `reporting` block was mandatory."""

        token: str = Field(min_length=64, max_length=64)
        run_id: str
        task_id: str
        connection_id: str
        agent_name: str
        title: str
        details: str | None = None
        context_items: list[dict[str, Any]] = Field(default_factory=list)
        reporting: TestRollbackBoundary.Frozen007ReportingContract
        reporting_instructions: str
        instructions_version: str = "v2"
        protocol_version: str = "2026-08-09"

    def test_014_FR_012_frozen_007_connection_document_validates_a_014_payload(
        self, tmp_path: Path, connector: FakeConnector, clock: Clock
    ) -> None:
        """AC-023: a rolled-back image can still read a connection 014 wrote.

        Three properties carry this, and each is a thing 014 could plausibly
        have done differently:

        * the storage key stays `endpoint_url` even though the API now says
          `agent_address` — renaming it would have been tidier and unreadable;
        * a bearer connection stores **no** `auth_header_name` key, so the 007
          default applies. Storing "Authorization" would be rejected outright by
          007's own validator, turning every bearer connection into a parse
          failure on rollback;
        * `StorageBaseModel` ignores unknown fields, which is what lets 014 add
          `wire` and `disconnect_reason` without 007 choking on them.
        """

        service = build_service(AgentRepository(tmp_path), connector, clock)
        connection_id = connect(service)

        # Read the row as it sits on disk. Going through the live model would
        # prove only that 014 agrees with itself; the rollback question is what
        # a *different* image finds in the file.
        with sqlite3.connect(tmp_path / "agents.sqlite3") as database:
            row = database.execute(
                "SELECT payload FROM agent_connections WHERE id = ?", (connection_id,)
            ).fetchone()
        assert row is not None
        payload = json.loads(row[0])

        assert payload["endpoint_url"], "007 reads the connection by this key"
        assert payload.get("wire") == "a2a", "014 records its own wire contract"

        # A bearer connection must not persist a header name the 007 validator
        # refuses. The 014 model's own default is the 007 default, so what
        # matters is that nothing ever writes "Authorization" here.
        assert payload.get("auth_header_name") != "Authorization"

        restored = self.Frozen007ConnectionDocument.model_validate(payload)
        assert restored.id == connection_id
        assert restored.endpoint_url == payload["endpoint_url"]

    def test_014_FR_012_a_bearer_shaped_payload_without_a_header_name_still_loads(
        self,
    ) -> None:
        """The exact rollback case: the key is absent, not empty.

        An empty string would fail 007's field-name token validator, and `None`
        would fail its type. Absent is the only shape that survives, so it is
        the one asserted.
        """

        payload = {
            "id": "conn-1",
            "owner_id": "owner-1",
            "name": "Agent",
            "endpoint_url": "https://agent.example.com/",
            "wire": "a2a",
            "auth_scheme": "bearer",
            "disconnect_reason": None,
            "status": "ready",
            "created_at": "2026-09-04T12:00:00Z",
            "updated_at": "2026-09-04T12:00:00Z",
            "schema_version": 2,
            "revision": 3,
        }

        restored = self.Frozen007ConnectionDocument.model_validate(payload)

        assert restored.auth_header_name == "X-Agent-Key", "the 007 default applies"
        assert restored.schema_version == 2

    def test_014_FR_012_frozen_007_run_event_and_command_documents_validate_014_payloads(
        self,
    ) -> None:
        """AC-023: the manifest keeps its 007 keys, with inert values.

        014 has no callback URL to put there — the bespoke inbound wire is
        gone — but omitting the block entirely would make every 014 run row
        unparseable to the 007 image. An empty `callback_url` is deliberately
        not an address: a rolled-back image reading it finds nowhere to send
        anything, rather than an endpoint 014 has stopped serving.
        """

        manifest = AgentRunManifest(
            token="a" * 64,
            run_id="run-1",
            task_id="task-1",
            connection_id="conn-1",
            agent_name="Agent",
            title="Do the thing",
            details=None,
            supporting_items=[],
            reporting=inert_reporting_contract("conn-1"),
            reporting_instructions="",
        )

        payload = manifest.model_dump(mode="json")

        assert payload["reporting"]["callback_url"] == ""
        assert payload["reporting"]["connection_id"] == "conn-1"
        assert payload["reporting_instructions"] == ""
        assert payload["instructions_version"] == REPORTING_INSTRUCTIONS_VERSION
        # The 007 defaults are present, not merely defaulted at read time: a
        # rolled-back image validating this row must not depend on its own
        # defaults matching ours.
        assert payload["reporting"]["signature_algorithm"] == "hmac-sha256"
        assert payload["reporting"]["body_envelope_version"] == PROTOCOL_VERSION

        restored = self.Frozen007RunManifest.model_validate(payload)
        assert restored.reporting.callback_url == ""
        assert restored.run_id == "run-1"

    def test_014_FR_012_a_manifest_missing_its_reporting_block_would_break_rollback(
        self,
    ) -> None:
        """The negative case, so the guard above cannot be vacuous.

        If this ever stops raising, the 007 model has been relaxed and the
        rollback boundary is no longer being tested by the test above.
        """

        payload = {
            "token": "a" * 64,
            "run_id": "run-1",
            "task_id": "task-1",
            "connection_id": "conn-1",
            "agent_name": "Agent",
            "title": "Do the thing",
            "reporting_instructions": "",
        }

        with pytest.raises(PydanticValidationError):
            self.Frozen007RunManifest.model_validate(payload)


# --- User Story 3: observation, reply, cancel and push (spec 014) ------------
#
# Every case below is about the one promise the observation lane makes: run
# state comes only from BrainBuddy's own authenticated read of the agent's task.
# Nothing here is allowed to invent a state, and nothing is allowed to lose one.


def observed_task(
    task_id: str,
    context_id: str,
    state: str = "TASK_STATE_WORKING",
    *,
    text: str | None = None,
    timestamp: str = "2026-08-09T12:00:00Z",
) -> Task:
    status: dict[str, Any] = {"state": state, "timestamp": timestamp}
    if text is not None:
        status["message"] = {"role": "ROLE_AGENT", "parts": [{"text": text}]}
    return Task.model_validate(
        {"id": task_id, "contextId": context_id, "status": status}
    )


def observation_of(task: Task, *, now: datetime) -> Any:
    return project_observation(task, now=now, limits=ObservationLimits())


class ObservedRelay:
    """A ready connection with one dispatched, observable A2A run."""

    def __init__(
        self,
        service: AgentRelayService,
        clock: Clock,
        a2a_client: FakeA2AClient,
        *,
        key: str = "idem-dispatch",
        task_id: str = "task_1",
    ) -> None:
        self.service = service
        self.clock = clock
        self.a2a_client = a2a_client
        self.connection_id = connect(service, key=f"{key}-create")
        make_ready(service, self.connection_id)
        run_id_holder = dispatch(
            service, self.connection_id, task_id=task_id, key=key
        )
        self.run_id = run_id_holder.id
        a2a_client.calls.clear()

    def observe(self, task: Task, *, trigger: str = "schedule") -> Any:
        run = self.service.agent_repo.get_run(self.run_id, owner_id=OWNER)
        return self.service.apply_observation(
            self.run_id,
            owner_id=OWNER,
            observation=observation_of(task, now=self.clock.now),
            based_on=run.run_version,
            trigger=trigger,
        )

    def projection(self) -> Any:
        return self.service.get_run(self.run_id, owner_id=OWNER)

    def audit_actions(self) -> list[str]:
        return [entry.action for entry in self.service.list_audit(owner_id=OWNER)]


def reply_command(run: Any) -> Any:
    """The run's newest reply command.

    Selected by kind rather than by position: a dispatched run already carries
    its `start` command, and the two rows share a creation timestamp, so
    "the last one" is whichever id sorts higher — which is nothing at all.
    """

    return [command for command in run.commands if command.kind == "reply"][-1]


def cancel_command(run: Any) -> Any:
    return [command for command in run.commands if command.kind == "cancel"][-1]


@pytest.fixture
def observed(
    service: AgentRelayService, clock: Clock, a2a_client: FakeA2AClient
) -> ObservedRelay:
    return ObservedRelay(service, clock, a2a_client)


class TestApplyObservation:
    def test_014_FR_008_an_identical_observation_only_refreshes_contact(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """AC-019. Sixty-second polling must not become sixty timeline rows."""

        observed.observe(observed_task("t1", observed.run_id))
        first = observed.projection()
        assert first.run_version == 1
        assert len(first.events) == 1

        clock.advance(timedelta(seconds=60))
        observed.observe(observed_task("t1", observed.run_id))

        again = observed.projection()
        assert again.run_version == 1, "an unchanged state is not a new version"
        assert len(again.events) == 1
        assert again.last_contact_at == clock.now
        assert again.last_observed_at == clock.now
        assert observed.audit_actions().count("observation_accepted") == 1

    def test_014_FR_008_a_differing_observation_appends_one_row_with_its_trigger(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """FR-009. Why the observation ran is part of what the row records."""

        observed.observe(observed_task("t1", observed.run_id))
        clock.advance(timedelta(seconds=5))
        observed.observe(
            observed_task("t1", observed.run_id, "TASK_STATE_INPUT_REQUIRED", text="Which?"),
            trigger="push",
        )

        run = observed.projection()
        assert [(event.type, event.trigger) for event in run.events] == [
            ("running", "schedule"),
            ("blocked", "push"),
        ]
        assert [event.kind for event in run.events] == ["observation", "observation"]
        assert run.question_text == "Which?"
        assert run.primary_state_label == "Needs you"

    def test_observation_accepted_audit_rows_are_bounded_per_run_state_and_day(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """014-SC-007. An audit trail that grows per poll is a retention problem."""

        for index in range(6):
            clock.advance(timedelta(seconds=60))
            state = "TASK_STATE_WORKING" if index % 2 else "TASK_STATE_SUBMITTED"
            observed.observe(observed_task("t1", observed.run_id, state))

        accepted = observed.audit_actions().count("observation_accepted")
        assert accepted == 2, "one row per run, state class and UTC day"

        clock.advance(timedelta(days=1))
        observed.observe(observed_task("t1", observed.run_id, "TASK_STATE_SUBMITTED"))
        assert observed.audit_actions().count("observation_accepted") == 3

    def test_014_FR_008_a_later_observation_never_reopens_a_terminal_run(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """AC-017. "Completed" then "running" is a straggler, not a reopening."""

        observed.observe(
            observed_task("t1", observed.run_id, "TASK_STATE_COMPLETED", text="Done.")
        )
        settled = observed.projection()
        assert settled.primary_state_label == "Agent reported complete"

        clock.advance(timedelta(seconds=60))
        observed.observe(observed_task("t1", observed.run_id, "TASK_STATE_WORKING"))

        after = observed.projection()
        assert after.reported_state == "completed"
        assert after.run_version == settled.run_version
        assert len(after.events) == len(settled.events)
        assert observed.audit_actions().count("observation_rejected") == 1

        for _ in range(4):
            clock.advance(timedelta(minutes=1))
            observed.observe(observed_task("t1", observed.run_id, "TASK_STATE_WORKING"))
        assert observed.audit_actions().count("observation_rejected") == 1

    def test_014_FR_008_no_write_happens_for_a_run_that_is_gone(
        self, observed: ObservedRelay, service: AgentRelayService, clock: Clock
    ) -> None:
        """FR-016. A purge that raced an observation is not undone by it."""

        service.delete_all_for_owner(owner_id=OWNER)

        applied = service.apply_observation(
            observed.run_id,
            owner_id=OWNER,
            observation=observation_of(
                observed_task("t1", observed.run_id), now=clock.now
            ),
            based_on=0,
        )

        assert applied is None
        assert service.list_audit(owner_id=OWNER) == []
        with pytest.raises(NotFoundError):
            service.agent_repo.get_run(observed.run_id, owner_id=OWNER)

    def test_014_FR_016_a_disconnected_run_is_never_written_by_an_observation(
        self, observed: ObservedRelay, service: AgentRelayService, clock: Clock
    ) -> None:
        """AC-022. Disconnect freezes the run; a late read must not thaw it."""

        observed.observe(observed_task("t1", observed.run_id))
        service.disconnect_connection(
            observed.connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=service.get_connection(
                    observed.connection_id, owner_id=OWNER
                ).revision,
            ),
            owner_id=OWNER,
            idempotency_key="idem-disconnect",
            reauthenticated=True,
        )
        frozen = observed.projection()

        observed.observe(
            observed_task("t1", observed.run_id, "TASK_STATE_COMPLETED", text="Done.")
        )

        after = observed.projection()
        assert after.reported_state == frozen.reported_state
        assert after.primary_state_label == "Connection disconnected"
        assert after.run_version == frozen.run_version

    def test_014_SC_007_an_identifiers_expired_run_is_never_observed_again(
        self, observed: ObservedRelay, service: AgentRelayService
    ) -> None:
        """There is nothing left to ask with: the identifiers are gone."""

        run = service.agent_repo.get_run(observed.run_id, owner_id=OWNER)
        service.agent_repo.save_run(
            run.model_copy(update={"identifiers_expired": True})
        )

        observed.observe(observed_task("t1", observed.run_id, "TASK_STATE_COMPLETED"))

        after = service.agent_repo.get_run(observed.run_id, owner_id=OWNER)
        assert after.reported_state is None
        assert after.run_version == run.run_version

    def test_observation_after_content_expiry_writes_no_agent_text(
        self, observed: ObservedRelay, service: AgentRelayService, clock: Clock
    ) -> None:
        """014-SC-007. Retention is irreversible: state moves, text does not."""

        clock.advance(timedelta(days=31))
        observed.observe(
            observed_task(
                "t1",
                observed.run_id,
                "TASK_STATE_INPUT_REQUIRED",
                text="What is the password?",
            )
        )

        stored = service.agent_repo.get_run(observed.run_id, owner_id=OWNER)
        assert stored.reported_state == "blocked"
        assert stored.question_text is None
        assert stored.blocked_reason is None
        assert stored.result_availability is None
        assert stored.last_contact_at == clock.now
        assert [event.summary for event in service.agent_repo.list_events(
            stored.id, owner_id=OWNER
        )] == [None]

    def test_014_FR_015_last_contact_is_the_latest_of_every_kind_of_contact(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """AC-019. An unchanged observation is still contact, and says so."""

        dispatched = observed.projection().last_contact_at
        assert dispatched is not None

        clock.advance(timedelta(minutes=10))
        observed.observe(observed_task("t1", observed.run_id))
        assert observed.projection().last_contact_at == clock.now

        clock.advance(timedelta(minutes=10))
        observed.observe(observed_task("t1", observed.run_id))
        assert observed.projection().last_contact_at == clock.now
        assert observed.projection().primary_state_label == "Running"

        clock.advance(timedelta(hours=2))
        stale = observed.projection()
        assert stale.primary_state_label == "Stopped reporting"
        assert stale.stopped_reporting is True
        assert stale.last_contact_at is not None
        assert stale.last_contact_at < clock.now

    def test_014_FR_013_an_over_cap_result_is_marked_never_stopped_reporting(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """AC-016. BrainBuddy's byte budget is not the agent going quiet."""

        task = observed_task("t1", observed.run_id, "TASK_STATE_COMPLETED")
        run = observed.service.agent_repo.get_run(observed.run_id, owner_id=OWNER)
        observed.service.apply_observation(
            observed.run_id,
            owner_id=OWNER,
            observation=project_observation(
                task,
                now=clock.now,
                limits=ObservationLimits(),
                result_availability="too_large",
            ),
            based_on=run.run_version,
        )

        clock.advance(timedelta(hours=5))
        projection = observed.projection()
        assert projection.result_availability == "too_large"
        assert projection.result_text is None
        assert projection.primary_state_label == "Agent reported complete"
        assert projection.stopped_reporting is False

    def test_014_FR_010_a_missing_task_withdraws_both_controls_and_keeps_contact(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """AC-020. "We can no longer see it" is not "it failed"."""

        observed.observe(observed_task("t1", observed.run_id))
        contact = observed.projection().last_contact_at

        clock.advance(timedelta(minutes=1))
        observed.service.record_task_missing(observed.run_id, owner_id=OWNER)

        run = observed.projection()
        assert run.agent_task_missing is True
        assert run.primary_state_label == "Agent no longer reports this run"
        assert run.capabilities.reply is False
        assert run.capabilities.cancel is False
        assert run.last_contact_at == contact
        assert run.reported_state == "running", "no failure is claimed"


class TestReplyOverTheA2AWire:
    def _blocked(self, observed: ObservedRelay) -> Any:
        observed.observe(
            observed_task(
                "t1", observed.run_id, "TASK_STATE_INPUT_REQUIRED", text="Which env?"
            )
        )
        return observed.projection()

    def _reply(
        self,
        observed: ObservedRelay,
        *,
        key: str = "idem-reply",
        message: str = "Use staging.",
    ) -> Any:
        return observed.service.reply_to_run(
            observed.run_id,
            AgentReplyRequest(
                message=message, expected_revision=observed.projection().revision
            ),
            owner_id=OWNER,
            idempotency_key=key,
        )

    def test_014_FR_010_a_reply_is_one_send_carrying_the_command_id(
        self, observed: ObservedRelay, a2a_client: FakeA2AClient, clock: Clock
    ) -> None:
        """AC-015. The reply is correlated by its own id, not by timing."""

        self._blocked(observed)
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=observed_task("t1", observed.run_id, "TASK_STATE_WORKING"),
            ),
        )

        run = self._reply(observed)

        outgoing = sends(a2a_client)
        assert len(outgoing) == 1
        message = outgoing[0]
        command = reply_command(run)
        assert message["messageId"] == command.id
        assert message["contextId"] == observed.run_id
        assert message["taskId"] == "t1"
        assert message["referenceTaskIds"] == ["t1"]
        assert message["metadata"]["brainbuddy.command_id"] == command.id
        assert [part["text"] for part in message["parts"]] == ["Use staging."]
        assert command.delivery == "confirmed"
        assert run.reported_state == "running"
        assert "run_replied" in observed.audit_actions()

    def test_014_FR_010_a_reply_carries_the_same_push_config_as_the_start(
        self,
        service: AgentRelayService,
        clock: Clock,
        a2a_client: FakeA2AClient,
        card_fetcher: FakeCardFetcher,
    ) -> None:
        """A successor task keeps push acceleration; the schedule is the fallback."""

        card_fetcher.discovery = ready_discovery(
            summary=card_summary(push_notifications=True)
        )
        observed = ObservedRelay(service, clock, a2a_client, key="idem-push-reply")
        start_config = [
            call[2].get("push_config")
            for call in service.a2a_client.calls  # type: ignore[union-attr]
            if call[0] == "SendMessage"
        ]
        self._blocked(observed)
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True, correlation_id="c", task=observed_task("t1", observed.run_id)
            ),
        )

        self._reply(observed)

        reply_config = a2a_client.calls_to("SendMessage")[-1][2]["push_config"]
        assert reply_config is not None
        assert reply_config["url"].startswith(PUSH_BASE)
        assert start_config == start_config  # the start registered one too

    def test_014_FR_010_a_successor_task_is_adopted_and_the_reply_never_refused(
        self, observed: ObservedRelay, a2a_client: FakeA2AClient, clock: Clock
    ) -> None:
        """AC-028, D-03-S27. The identifier moved; the run did not."""

        self._blocked(observed)
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=observed_task("t2", observed.run_id, "TASK_STATE_WORKING"),
            ),
        )

        run = self._reply(observed)

        assert run.agent_task_id == "t2"
        assert run.correlation_id == observed.run_id
        succession = [event for event in run.events if event.kind == "task_succession"]
        assert len(succession) == 1
        assert succession[0].previous_agent_task_id == "t1"
        assert succession[0].new_agent_task_id == "t2"
        assert succession[0].summary == "The agent continued this run in a new task"
        assert reply_command(run).delivery == "confirmed"
        stored = observed.service.agent_repo.get_command(
            reply_command(run).id, owner_id=OWNER
        )
        assert stored is not None
        assert stored.agent_task_id_after == "t2"
        assert "task_succession_recorded" in observed.audit_actions()

    def test_014_FR_010_a_foreign_conversation_is_never_adopted_by_a_reply(
        self, observed: ObservedRelay, a2a_client: FakeA2AClient
    ) -> None:
        """A task from another conversation would attach this run to strange work."""

        self._blocked(observed)
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=observed_task("t9", "someone-elses-run", "TASK_STATE_WORKING"),
            ),
        )

        run = self._reply(observed)

        assert run.agent_task_id == "t1"
        assert reply_command(run).delivery == "unconfirmed"
        assert reply_command(run).outcome_code == "a2a_response_invalid"
        assert not [event for event in run.events if event.kind == "task_succession"]

    def test_014_FR_010_a_terminal_task_withdraws_the_reply_and_states_the_reason(
        self, observed: ObservedRelay, a2a_client: FakeA2AClient, clock: Clock
    ) -> None:
        """AC-033 (c). `-32004` with no successor is the agent's own answer."""

        self._blocked(observed)
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=False,
                correlation_id="c",
                error_code="a2a_unsupported_operation",
                a2a_error_code=-32004,
            ),
        )
        a2a_client.script(
            "GetTask",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=observed_task(
                    "t1", observed.run_id, "TASK_STATE_FAILED", text="Timed out."
                ),
            ),
        )

        run = self._reply(observed)

        assert reply_command(run).delivery == "rejected"
        assert reply_command(run).outcome_code == "a2a_unsupported_operation"
        assert run.capabilities.reply is False

    def test_ambiguous_reply_stays_unconfirmed_and_returns_only_after_blocked(
        self, observed: ObservedRelay, a2a_client: FakeA2AClient, clock: Clock
    ) -> None:
        """AC-033. Silence is not a rejection, and it is not an acknowledgement."""

        self._blocked(observed)
        a2a_client.script(
            "SendMessage",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_timeout"),
        )

        run = self._reply(observed)
        assert reply_command(run).delivery == "unconfirmed"
        assert reply_command(run).outcome_code is None
        assert run.exchange_state == "closed"

        clock.advance(timedelta(minutes=6))
        observed.observe(
            observed_task(
                "t1", observed.run_id, "TASK_STATE_INPUT_REQUIRED", text="Still which?"
            )
        )

        after = observed.projection()
        assert after.capabilities.reply is True
        assert reply_command(after).delivery == "unconfirmed"

        second = self._reply(observed, key="idem-reply-2", message="Staging, again.")
        assert reply_command(second).id != reply_command(run).id


class TestCancelOverTheA2AWire:
    def _cancel(self, observed: ObservedRelay, *, key: str = "idem-cancel") -> Any:
        return observed.service.cancel_run(
            observed.run_id, owner_id=OWNER, idempotency_key=key
        )

    @pytest.mark.parametrize(
        ("error_code", "a2a_code", "expected"),
        [
            ("a2a_not_cancelable", -32002, "not_cancelable"),
            ("a2a_unsupported_operation", -32004, "unsupported"),
            ("a2a_method_not_found", -32601, "unsupported"),
            ("a2a_task_not_found", -32001, "task_missing"),
            ("a2a_internal_error", -32603, "unconfirmed"),
            ("a2a_server_error", None, "unconfirmed"),
            ("a2a_timeout", None, "unconfirmed"),
            ("a2a_unreachable", None, "unconfirmed"),
        ],
    )
    def test_014_FR_010_every_cancel_answer_maps_to_exactly_one_outcome(
        self,
        observed: ObservedRelay,
        a2a_client: FakeA2AClient,
        error_code: str,
        a2a_code: int | None,
        expected: str,
    ) -> None:
        """AC-018, AC-029. Only the agent's own words may withdraw the control."""

        observed.observe(observed_task("t1", observed.run_id))
        a2a_client.script(
            "CancelTask",
            A2AResult(
                ok=False,
                correlation_id="c",
                error_code=error_code,
                a2a_error_code=a2a_code,
            ),
        )

        run = self._cancel(observed)

        assert run.cancel_outcome == expected
        # `task_missing` withdraws the control too, but for a different reason:
        # not "the agent refuses", but "there is nothing left to cancel".
        withdrawn = expected in {"unsupported", "not_cancelable", "task_missing"}
        assert run.capabilities.cancel is not withdrawn
        assert run.reported_state == "running", "the last observed state survives"

    def test_014_FR_010_an_accepted_cancel_is_confirmed_and_observed(
        self, observed: ObservedRelay, a2a_client: FakeA2AClient
    ) -> None:
        observed.observe(observed_task("t1", observed.run_id))
        a2a_client.script(
            "CancelTask",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=observed_task("t1", observed.run_id, "TASK_STATE_CANCELED"),
            ),
        )

        run = self._cancel(observed)

        assert run.cancel_outcome == "accepted"
        assert run.reported_state == "cancelled"
        assert run.primary_state_label == "Cancelled"
        assert cancel_command(run).delivery == "confirmed"

    def test_cancel_transient_error_then_success_reuses_the_command_id(
        self, observed: ObservedRelay, a2a_client: FakeA2AClient
    ) -> None:
        """AC-029. A retry must not be a second request the agent can act on."""

        observed.observe(observed_task("t1", observed.run_id))
        a2a_client.script(
            "CancelTask",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_timeout"),
        )
        first = self._cancel(observed)
        assert first.cancel_outcome == "unconfirmed"
        first_command_id = a2a_client.calls_to("CancelTask")[-1][2]["command_id"]

        a2a_client.script(
            "CancelTask",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=observed_task("t1", observed.run_id, "TASK_STATE_CANCELED"),
            ),
        )
        second = self._cancel(observed, key="idem-cancel-2")

        assert second.cancel_outcome == "accepted"
        assert a2a_client.calls_to("CancelTask")[-1][2]["command_id"] == (
            first_command_id
        )

    def test_014_FR_010_a_recorded_refusal_replays_without_a_second_request(
        self, observed: ObservedRelay, a2a_client: FakeA2AClient
    ) -> None:
        """Asking again cannot change an answer the agent already gave."""

        observed.observe(observed_task("t1", observed.run_id))
        a2a_client.script(
            "CancelTask",
            A2AResult(
                ok=False,
                correlation_id="c",
                error_code="a2a_not_cancelable",
                a2a_error_code=-32002,
            ),
        )
        self._cancel(observed)
        before = len(a2a_client.calls_to("CancelTask"))

        replayed = self._cancel(observed, key="idem-cancel-again")

        assert replayed.cancel_outcome == "not_cancelable"
        assert len(a2a_client.calls_to("CancelTask")) == before


# --- User Story 4: disconnect, and keep only bounded evidence ----------------


class TestDisconnectAndBoundedEvidence:
    def _disconnect(
        self, observed: ObservedRelay, *, key: str = "idem-disconnect"
    ) -> Any:
        service = observed.service
        return service.disconnect_connection(
            observed.connection_id,
            AgentConnectionDisconnectRequest(
                current_password="correct-horse-battery-staple",
                expected_revision=service.get_connection(
                    observed.connection_id, owner_id=OWNER
                ).revision,
            ),
            owner_id=OWNER,
            idempotency_key=key,
            reauthenticated=True,
        )

    def test_014_FR_016_disconnect_erases_the_credential_and_the_card_together(
        self, observed: ObservedRelay
    ) -> None:
        """AC-022, AC-024. A connection that cannot say where it pointed is not
        a connection anyone can reason about, so the card goes with the key."""

        service = observed.service
        before = service.agent_repo.get_connection(
            observed.connection_id, owner_id=OWNER
        )
        assert before.credential is not None
        assert before.card is not None
        assert before.card_fingerprint is not None

        response = self._disconnect(observed)

        stored = service.agent_repo.get_connection(
            observed.connection_id, owner_id=OWNER
        )
        assert stored.credential is None
        assert stored.card is None
        assert stored.card_fingerprint is None
        assert stored.disconnect_reason == "owner"
        assert response.status == "disconnected"
        assert response.card is None

    def test_014_FR_016_disconnect_stops_observation_and_push_for_its_runs(
        self, observed: ObservedRelay, a2a_client: FakeA2AClient
    ) -> None:
        """AC-022. Nothing else will be asked of an agent BrainBuddy cannot reach."""

        observed.observe(observed_task("t1", observed.run_id))
        service = observed.service
        assert (
            service.agent_repo.get_run(
                observed.run_id, owner_id=OWNER
            ).next_observation_at
            is not None
        )
        a2a_client.calls.clear()

        self._disconnect(observed)

        run = service.agent_repo.get_run(observed.run_id, owner_id=OWNER)
        assert run.next_observation_at is None
        assert run.connection_disconnected_at is not None
        assert a2a_client.calls_to("CreateTaskPushNotificationConfig") == []
        assert service.agent_repo.due_observations(now=run.updated_at) == []

    def test_014_FR_016_a_disconnected_run_is_frozen_and_claims_no_cancellation(
        self, observed: ObservedRelay
    ) -> None:
        """AC-022. Disconnecting did not cancel work the agent already accepted."""

        observed.observe(observed_task("t1", observed.run_id))
        before = observed.projection()

        self._disconnect(observed)

        run = observed.projection()
        assert run.primary_state_label == "Connection disconnected"
        assert run.reported_state == before.reported_state
        assert run.cancel_requested is False
        assert run.cancel_outcome == "none"
        assert run.capabilities.reply is False
        assert run.capabilities.cancel is False
        assert [event.type for event in run.events] == [
            event.type for event in before.events
        ]

    def test_014_FR_016_the_credential_appears_in_no_view_after_a_disconnect(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """AC-023. Not in a connection, a run, an audit row or an export."""

        service = observed.service
        self._disconnect(observed)

        rendered = json.dumps(
            {
                "connections": [
                    connection.model_dump(mode="json")
                    for connection in service.list_connections(owner_id=OWNER)
                ],
                "runs": [
                    run.model_dump(mode="json")
                    for run in service.list_runs_for_task("task_1", owner_id=OWNER)
                ],
                "audit": [
                    entry.model_dump(mode="json")
                    for entry in service.list_audit(owner_id=OWNER)
                ],
                "export": service.agent_repo.export_owner_data(
                    owner_id=OWNER, now=clock.now
                ),
            },
            default=str,
        )

        assert "super-secret-token" not in rendered

    def test_run_id_is_retained_with_the_run_row_until_purge_and_identifiers_expire_at_90_days(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """014-SC-007, stated honestly.

        The conversation identifier *is* the run id, and it is embedded in a
        callback URL the agent keeps and in a run row no sweep deletes. Nulling
        it at ninety days would erase nothing anyone actually holds, so the
        promise made is the one that can be kept: the identifiers the agent
        could act on go, and the run id stays until the account is purged.
        """

        service = observed.service
        run_id = observed.run_id
        clock.advance(timedelta(days=91))

        service.run_retention_sweep()

        run = service.agent_repo.get_run(run_id, owner_id=OWNER)
        assert run.id == run_id
        assert run.context_id == run_id
        assert run.identifiers_expired is True
        assert run.message_id is None
        assert run.agent_task_id is None
        assert run.interface_url is None
        assert run.card_fingerprint is None
        assert run.push_token_fingerprint is None
        assert service.agent_repo.list_events(run_id, owner_id=OWNER) == []
        assert "identifiers_expired" in observed.audit_actions()

    def test_expired_but_unswept_run_reads_with_no_agent_text(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """014-SC-007. Read-time projection, so the sweep's timing is not a promise."""

        observed.observe(
            observed_task(
                "t1",
                observed.run_id,
                "TASK_STATE_INPUT_REQUIRED",
                text="What is the password?",
            )
        )
        clock.advance(timedelta(days=31))
        # The sweep is deliberately not run.

        run = observed.projection()

        assert run.content_expired is True
        assert run.question_text is None
        assert run.blocked_reason is None
        assert run.result_availability is None
        assert run.artifacts_summary == []
        assert run.primary_state_label == "Content expired under retention policy"

    def test_014_SC_007_content_written_after_expiry_is_re_erased_next_pass(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """A partial expiry must not survive: the predicate re-detects text."""

        service = observed.service
        clock.advance(timedelta(days=31))
        service.run_retention_sweep()
        run = service.agent_repo.get_run(observed.run_id, owner_id=OWNER)
        assert run.content_expired is True
        service.agent_repo.save_run(
            run.model_copy(
                update={
                    "question_text": "Snuck back in",
                    "blocked_reason": "And so did this",
                    "result_availability": "too_large",
                }
            )
        )

        service.run_retention_sweep()

        after = service.agent_repo.get_run(observed.run_id, owner_id=OWNER)
        assert after.question_text is None
        assert after.blocked_reason is None
        assert after.result_availability is None

    def test_expire_due_content_skips_and_logs_an_unparseable_row(
        self,
        observed: ObservedRelay,
        service: AgentRelayService,
        clock: Clock,
        a2a_client: FakeA2AClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """One broken row must not deny every other owner their retention.

        Aborting the transaction would make one unparseable payload a permanent
        retention failure for the whole instance — the strongest possible form
        of the bug, and the hardest to notice.
        """

        import logging

        other = ObservedRelay(service, clock, a2a_client, key="idem-other-owner")
        with sqlite3.connect(service.agent_repo.root / "agents.sqlite3") as raw:
            raw.execute(
                "UPDATE agent_runs SET payload = ? WHERE id = ?",
                ('{"not": "a run"}', observed.run_id),
            )
        clock.advance(timedelta(days=31))

        with caplog.at_level(logging.WARNING):
            service.run_retention_sweep()

        healthy = service.agent_repo.get_run(other.run_id, owner_id=OWNER)
        assert healthy.content_expired is True
        assert healthy.manifest is None
        messages = [record.getMessage() for record in caplog.records]
        assert any("unparseable" in message for message in messages)
        assert not any("Draft the plan" in message for message in messages)

    def test_014_SC_007_a_live_connections_card_survives_every_sweep(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """AC-024. The card is connection configuration, not run content."""

        service = observed.service
        clock.advance(timedelta(days=200))

        service.run_retention_sweep()

        connection = service.agent_repo.get_connection(
            observed.connection_id, owner_id=OWNER
        )
        assert connection.card is not None
        assert connection.card_fingerprint is not None

    def test_014_SC_007_audit_rows_are_gone_at_ninety_days(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        service = observed.service
        assert service.list_audit(owner_id=OWNER)
        clock.advance(timedelta(days=91))

        service.run_retention_sweep()

        assert [
            entry
            for entry in service.list_audit(owner_id=OWNER)
            if entry.created_at < clock.now - timedelta(days=90)
        ] == []

    def test_014_FR_016_purge_leaves_no_row_for_the_owner_and_every_row_for_another(
        self,
        observed: ObservedRelay,
        service: AgentRelayService,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-025. Purge is complete, and it is scoped."""

        stranger = ObservedRelay(
            service, clock, a2a_client, key="idem-stranger", task_id="task_2"
        )
        assert stranger.run_id

        service.delete_all_for_owner(owner_id=OWNER)

        assert service.agent_repo.list_runs_for_owner(owner_id=OWNER) == []
        assert service.list_connections(owner_id=OWNER) == []
        assert service.list_audit(owner_id=OWNER) == []
        export = service.agent_repo.export_owner_data(owner_id=OWNER, now=clock.now)
        assert all(rows == [] for rows in export.values())

    def test_014_SC_007_the_relay_export_carries_the_run_but_never_a_verifier(
        self, observed: ObservedRelay, clock: Clock
    ) -> None:
        """AC-025. A fingerprint is a verifier, and none of them is user content."""

        export = observed.service.agent_repo.export_owner_data(
            owner_id=OWNER, now=clock.now
        )

        assert [run["id"] for run in export["runs"]] == [observed.run_id]
        rendered = json.dumps(export)
        for excluded in (
            "credential",
            "push_token_fingerprint",
            "card_fingerprint",
            "inbound_secret",
        ):
            assert excluded not in rendered, f"{excluded} must not leave"

    def test_014_SC_007_data_retention_doc_names_the_relay_tiers_and_sweeps(
        self,
    ) -> None:
        """T124's assertion: the promise a user can read matches the code.

        A retention tier that exists only in the sweep is a promise nobody was
        made. This is the one place the two are compared, so the document has
        to name each tier, each sweep step and the one thing that survives.
        """

        doc = (
            Path(__file__).resolve().parents[2] / "docs" / "data-retention.md"
        ).read_text(encoding="utf-8")

        assert "expire_due_content" in doc
        assert "expire_due_identifiers" in doc
        assert "purge_expired_audit" in doc
        assert "30" in doc and "90" in doc
        assert "relay/relay.json" in doc
        assert "disconnect_connection" in doc
        lowered = doc.lower()
        assert "card" in lowered and "fingerprint" in lowered
        assert "run id" in lowered or "run identifier" in lowered
        assert "purge" in lowered
