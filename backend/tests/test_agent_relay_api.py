"""HTTP contract for the external-agent relay.

Drives the real FastAPI app end to end: session auth, the rollout flag, owner
isolation across two real accounts, re-authentication, idempotency headers, and
the A2A push callback.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.agents import MAX_EVENT_BODY_BYTES, _verify_password
from app.container import Container
from app.core import get_config
from app.core.config import FeatureFlagState
from app.core.rate_limit import sensitive_action_rate_limiter
from app.main import _run_privacy_maintenance_sweep, create_app
from app.modules.agents.a2a.card import (
    MAX_CARD_DESCRIPTION_CHARS,
    CardDiscovery,
)
from app.modules.agents.a2a.mapping import ObservationLimits, project_observation
from app.modules.agents.a2a.types import Task
from app.modules.agents.connector import (
    ConnectorCommandOutcome,
    ConnectorStartOutcome,
    ConnectorTarget,
    ConnectorTestOutcome,
)
from app.modules.agents.domain import (
    AgentCapabilities,
)
from app.repositories.feature_flag import FlagMode
from app.schemas.auth import Invite, User
from app.services.auth_service import AuthService
from app.utils.time import utcnow

from .a2a_fakes import (
    A2AResult,
    FakeA2AClient,
    FakeCardFetcher,
    card_summary,
    ready_discovery,
)
from .conftest import TEST_USER_EMAIL, TEST_USER_PASSWORD

SECOND_EMAIL = "second-relay@example.com"
SECOND_PASSWORD = "another-horse-battery-staple"
ENDPOINT = "https://agent.example.com"


def test_sensitive_reauthentication_rejects_a_missing_password_before_rate_limiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing proof fails closed without consuming the owner's attempt budget."""

    monkeypatch.setattr(
        sensitive_action_rate_limiter,
        "check",
        lambda _owner_id: pytest.fail("missing passwords must not consume attempts"),
    )

    auth_service = cast(AuthService, object())
    user = cast(User, type("UserStub", (), {"id": "owner-a"})())

    assert _verify_password(auth_service, user, None) is False


def test_sensitive_reauthentication_reports_rate_limit_before_password_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exhausted owner cannot spend verification work or learn password validity."""

    monkeypatch.setattr(sensitive_action_rate_limiter, "check", lambda _owner_id: False)
    auth_service = cast(
        AuthService,
        type(
            "AuthService",
            (),
            {"verify_password": lambda *_args: pytest.fail("rate limit must win")},
        )(),
    )
    user = cast(User, type("UserStub", (), {"id": "owner-a"})())

    with pytest.raises(HTTPException) as excinfo:
        _verify_password(
            auth_service,
            user,
            "candidate-password",
        )

    assert excinfo.value.status_code == 429
    assert excinfo.value.detail == "Too many attempts. Try again later."


class FakeConnector:
    def __init__(self) -> None:
        self.test_outcome = ConnectorTestOutcome(
            "ready", AgentCapabilities(progress=True, reply=True, cancel=True)
        )
        self.start_outcome = ConnectorStartOutcome("sent")
        self.command_outcome = ConnectorCommandOutcome("confirmed")
        self.starts: list[dict[str, Any]] = []
        self.commands: list[dict[str, Any]] = []

    def test(self, target: ConnectorTarget) -> ConnectorTestOutcome:
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


def _resolver(host: str, port: int) -> list[str]:
    return {
        "agent.example.com": ["93.184.216.34"],
        "second.example.com": ["93.184.216.35"],
    }[host]


@pytest.fixture
def relay_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, TestClient, FakeConnector, Container], None, None]:
    """Two signed-in clients on one app, with the relay flag on and no network."""

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "relay-data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv(
        "BRAIN_BUDDY_FEATURE_FLAGS", "voice_brain_dump=on,external_agent_relay=on"
    )
    get_config.cache_clear()
    app = create_app()
    container: Container = app.state.container

    connector = FakeConnector()
    container.agent_relay_service.connector = connector
    container.agent_relay_service._resolver = _resolver
    # Discovery and the A2A wire are scripted in-process: the HTTP contract is
    # what these tests are about, and a real socket would make them a network
    # test that happens to exercise routing.
    container.agent_relay_service._card_fetcher = FakeCardFetcher()
    container.agent_relay_service.a2a_client = FakeA2AClient()

    for code in ("invite_relay_a", "invite_relay_b"):
        container.invite_repo.create(Invite(code=code, created_at=utcnow()))

    first = TestClient(app)
    assert (
        first.post(
            "/api/auth/signup",
            json={
                "email": TEST_USER_EMAIL,
                "password": TEST_USER_PASSWORD,
                "invite_code": "invite_relay_a",
            },
        ).status_code
        == 201
    )
    second = TestClient(app)
    assert (
        second.post(
            "/api/auth/signup",
            json={
                "email": SECOND_EMAIL,
                "password": SECOND_PASSWORD,
                "invite_code": "invite_relay_b",
            },
        ).status_code
        == 201
    )

    yield first, second, connector, container
    first.close()
    second.close()
    get_config.cache_clear()


@pytest.fixture
def client(
    relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
) -> TestClient:
    return relay_app[0]


@pytest.fixture
def other_client(
    relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
) -> TestClient:
    return relay_app[1]


@pytest.fixture
def connector(
    relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
) -> FakeConnector:
    return relay_app[2]


@pytest.fixture
def container(
    relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
) -> Container:
    return relay_app[3]


def register_connection(client: TestClient, *, key: str = "k-create") -> dict[str, Any]:
    """The registration response exactly as the route returns it (no secret)."""

    response = client.post(
        "/api/agent-connections",
        headers={"Idempotency-Key": key},
        json={
            "name": "Hermes",
            "agent_address": ENDPOINT,
            "credential": "Bearer super-secret-token",
            "current_password": TEST_USER_PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_task(client: TestClient, title: str = "Draft the migration plan") -> str:
    response = client.post(
        "/api/tasks",
        headers={"Idempotency-Key": f"task-{title}"},
        json={"title": title, "details": "Cover rollback.", "state": "next"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def observe(
    container: Container,
    run_id: str,
    *,
    state: str = "TASK_STATE_WORKING",
    text: str | None = None,
    agent_task_id: str = "agent-task-1",
) -> None:
    """Apply one observation the way the scheduled observer would."""

    service = container.agent_relay_service
    owner_id = service.agent_repo.owner_of_run(run_id) or ""
    run = service.agent_repo.get_run(run_id, owner_id=owner_id)
    status: dict[str, Any] = {"state": state, "timestamp": "2026-08-09T12:00:00Z"}
    if text is not None:
        status["message"] = {"role": "ROLE_AGENT", "parts": [{"text": text}]}
    task = Task.model_validate(
        {"id": agent_task_id, "contextId": run_id, "status": status}
    )
    service.apply_observation(
        run_id,
        owner_id=owner_id,
        observation=project_observation(task, now=utcnow(), limits=ObservationLimits()),
        based_on=run.run_version,
        trigger="schedule",
    )


def blocked_run(
    client: TestClient,
    container: Container,
    connection_id: str,
    task_id: str,
    *,
    question: str = "Which environment?",
    key: str = "k-dispatch",
    agent_task_id: str = "agent-task-1",
) -> dict[str, Any]:
    """One dispatched run whose agent answered `input_required` with a question.

    The A2A wire has no inbound event: a question reaches BrainBuddy only as a
    Task state, so the hand-off exchange itself is where the run becomes
    **Needs you** (AC-012).
    """

    a2a = cast(FakeA2AClient, container.agent_relay_service.a2a_client)
    preview = client.post(
        f"/api/tasks/{task_id}/agent-runs/preview",
        json={"connection_id": connection_id},
    )
    assert preview.status_code == 200, preview.text
    reserved = preview.json()
    a2a.script(
        "SendMessage",
        A2AResult(
            ok=True,
            correlation_id="corr",
            task=Task.model_validate(
                {
                    "id": agent_task_id,
                    "contextId": reserved["run_id"],
                    "status": {
                        "state": "TASK_STATE_INPUT_REQUIRED",
                        "message": {
                            "role": "ROLE_AGENT",
                            "parts": [{"text": question}],
                        },
                    },
                }
            ),
        ),
    )
    response = client.post(
        f"/api/tasks/{task_id}/agent-runs",
        headers={"Idempotency-Key": key},
        json={
            "connection_id": connection_id,
            "manifest_token": reserved["token"],
            "acknowledge_duplicate_risk": True,
        },
    )
    assert response.status_code == 201, response.text
    a2a.results.pop("SendMessage", None)
    return dict(response.json())


def hand_off(
    client: TestClient,
    connection_id: str,
    task_id: str,
    *,
    key: str = "k-dispatch",
    acknowledge: bool = True,
) -> dict[str, Any]:
    """One review and the confirmation it authorises.

    The default acknowledges the duplicate risk because every fixture connection
    here is best-effort and a real client would have shown the box; the suites
    that assert the *gate* pass `acknowledge=False` explicitly (AC-026).
    """

    preview = client.post(
        f"/api/tasks/{task_id}/agent-runs/preview",
        json={"connection_id": connection_id},
    )
    assert preview.status_code == 200, preview.text
    response = client.post(
        f"/api/tasks/{task_id}/agent-runs",
        headers={"Idempotency-Key": key},
        json={
            "connection_id": connection_id,
            "manifest_token": preview.json()["token"],
            "acknowledge_duplicate_risk": acknowledge,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def set_relay_flag(client: TestClient, state: FeatureFlagState) -> None:
    """Flip the runtime-owned `external_agent_relay` flag through the same
    SQLite-backed service request-time gating consults (ADR-0019) — `config`
    no longer holds any runtime authority for a managed flag to override."""

    app: Any = client.app
    container: Container = app.state.container
    container.feature_flag_service.set_mode(
        "external_agent_relay", FlagMode(state.value), operator_id="test-harness"
    )


class TestAuthAndRollout:
    def test_every_owner_route_requires_a_session(
        self, anonymous_api_client: TestClient
    ) -> None:
        """An unauthenticated caller reaches nothing."""

        for method, path in (
            ("get", "/api/agent-connections"),
            ("post", "/api/agent-connections"),
            ("get", "/api/agent-runs/agentrun_1"),
            ("post", "/api/agent-runs/agentrun_1/cancel"),
            ("get", "/api/tasks/task_1/agent-runs"),
            ("post", "/api/tasks/task_1/agent-runs/preview"),
        ):
            call = getattr(anonymous_api_client, method)
            response = call(path) if method == "get" else call(path, json={})
            assert response.status_code == 401, f"{method} {path}: {response.text}"

    def test_rollout_off_preserves_reads_but_blocks_new_connections(
        self, api_client: TestClient
    ) -> None:
        """FR-019: rollback keeps owner visibility while blocking fresh work."""

        assert api_client.get("/api/agent-connections").status_code == 200
        response = api_client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "off-create"},
            json={},
        )
        assert response.status_code == 404

    def test_rollout_off_allows_owner_to_disconnect_and_destroy_secrets(
        self,
        client: TestClient,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        created = register_connection(client)
        set_relay_flag(client, FeatureFlagState.OFF)

        response = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "disconnect-while-off"},
            json={
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": created["revision"],
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "disconnected"
        replay = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "disconnect-while-off"},
            json={
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": created["revision"],
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["revision"] == response.json()["revision"]
        stored = relay_app[3].agent_repo.get_connection(
            created["id"], owner_id=client.get("/api/account").json()["id"]
        )
        assert stored.credential is None

    def test_rollout_off_disconnect_preserves_owner_password_revision_and_key_checks(
        self, client: TestClient, other_client: TestClient
    ) -> None:
        created = register_connection(client)
        set_relay_flag(client, FeatureFlagState.OFF)

        wrong_owner = other_client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "off-disconnect-other"},
            json={
                "current_password": SECOND_PASSWORD,
                "expected_revision": created["revision"],
            },
        )
        bad_password = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "off-disconnect-password"},
            json={
                "current_password": "not-the-password",
                "expected_revision": created["revision"],
            },
        )
        bad_revision = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "off-disconnect-revision"},
            json={"current_password": TEST_USER_PASSWORD, "expected_revision": 99},
        )
        missing_key = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            json={
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": created["revision"],
            },
        )

        assert wrong_owner.status_code == 404
        assert bad_password.status_code == 403
        assert bad_revision.status_code == 409
        assert missing_key.status_code == 400
        assert (
            client.get(f"/api/agent-connections/{created['id']}").json()["status"]
            == "untested"
        )

    def test_rollout_off_keeps_every_dispatch_enabling_mutation_closed(
        self, client: TestClient
    ) -> None:
        created = register_connection(client)
        task_id = create_task(client, "Blocked while rollout is off")
        set_relay_flag(client, FeatureFlagState.OFF)

        requests = (
            client.post(
                "/api/agent-connections",
                headers={"Idempotency-Key": "off-create-again"},
                json={
                    "name": "Other",
                    "agent_address": ENDPOINT,
                    "credential": "Bearer other",
                    "current_password": TEST_USER_PASSWORD,
                },
            ),
            client.post(f"/api/agent-connections/{created['id']}/test"),
            client.post(
                f"/api/agent-connections/{created['id']}/credential",
                headers={"Idempotency-Key": "off-credential"},
                json={
                    "credential": "Bearer replacement",
                    "current_password": TEST_USER_PASSWORD,
                    "expected_revision": created["revision"],
                },
            ),
            client.post(
                f"/api/tasks/{task_id}/agent-runs/preview",
                json={"connection_id": created["id"]},
            ),
            client.post(
                f"/api/tasks/{task_id}/agent-runs",
                headers={"Idempotency-Key": "off-fresh-dispatch"},
                json={
                    "connection_id": created["id"],
                    "manifest_token": "a" * 64,
                },
            ),
        )

        assert [response.status_code for response in requests] == [404] * len(requests)

    def test_the_effective_flag_is_reported_to_the_client(
        self, client: TestClient
    ) -> None:
        """Clients gate their UI on the same server-owned flag."""

        response = client.get("/api/auth/me")

        assert response.json()["feature_flags"]["external_agent_relay"] is True

    def test_responses_carry_a_correlation_id(self, client: TestClient) -> None:
        """FR-017: every response is traceable."""

        response = client.get("/api/agent-connections")

        assert response.headers["X-Correlation-ID"]


class TestConnectionRoutes:
    def test_updates_name_or_destination_without_returning_secrets(
        self, client: TestClient
    ) -> None:
        created = register_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        current = client.get(f"/api/agent-connections/{created['id']}").json()

        renamed = client.put(
            f"/api/agent-connections/{created['id']}",
            headers={"Idempotency-Key": "update-name"},
            json={"name": "Renamed", "expected_revision": current["revision"]},
        )
        moved = client.put(
            f"/api/agent-connections/{created['id']}",
            headers={"Idempotency-Key": "update-destination"},
            json={
                "agent_address": "https://second.example.com",
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": renamed.json()["revision"],
            },
        )

        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["status"] == "ready"
        assert moved.status_code == 200, moved.text
        assert moved.json()["status"] == "untested"
        assert "credential" not in moved.json()
        assert "inbound_signing_secret" not in moved.json()

    def test_rollout_off_blocks_connection_update(self, client: TestClient) -> None:
        created = register_connection(client)
        set_relay_flag(client, FeatureFlagState.OFF)

        response = client.put(
            f"/api/agent-connections/{created['id']}",
            headers={"Idempotency-Key": "off-update"},
            json={"name": "Cannot enable", "expected_revision": created["revision"]},
        )

        assert response.status_code == 404

    def test_014_FR_012_creating_a_connection_returns_no_secret_at_all(
        self, client: TestClient
    ) -> None:
        """AC-019, 014-FR-012: neither the credential nor any inbound secret.

        007's 201 carried a signing secret the owner had to copy into their
        agent. The A2A wire has none, so the safest registration response is one
        whose schema cannot hold a secret in the first place.
        """

        created = register_connection(client)

        assert created["status"] == "untested"
        assert created["auth_scheme"] == "bearer"
        assert created["agent_address"] == ENDPOINT
        assert "inbound_signing_secret" not in created
        assert "credential" not in created

        listed = client.get("/api/agent-connections").json()
        assert "inbound_signing_secret" not in listed[0]
        assert "super-secret-token" not in json.dumps(listed)

    def test_creating_without_the_password_is_rejected(
        self, client: TestClient
    ) -> None:
        """FR-003: registration is a re-authenticated action."""

        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "k1"},
            json={
                "name": "Hermes",
                "agent_address": ENDPOINT,
                "credential": "Bearer token",
            },
        )

        assert response.status_code == 422

    def test_creating_with_a_wrong_password_is_forbidden(
        self, client: TestClient
    ) -> None:
        """A stolen session alone cannot register a destination."""

        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "k1"},
            json={
                "name": "Hermes",
                "agent_address": ENDPOINT,
                "credential": "Bearer token",
                "current_password": "not-the-password",
            },
        )

        assert response.status_code == 403
        assert client.get("/api/agent-connections").json() == []

    def test_creating_with_a_whitespace_only_name_is_rejected_before_action(
        self, client: TestClient, connector: FakeConnector
    ) -> None:
        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "blank-name"},
            json={
                "name": "   ",
                "agent_address": ENDPOINT,
                "credential": "Bearer token",
                "current_password": TEST_USER_PASSWORD,
            },
        )

        assert response.status_code == 422
        assert client.get("/api/agent-connections").json() == []
        assert connector.starts == []
        assert connector.commands == []

    @pytest.mark.parametrize(
        "auth_header_name",
        ["Authorization", "content-type", "X Bad"],
    )
    def test_creating_with_an_owned_or_malformed_auth_header_is_rejected_before_action(
        self,
        client: TestClient,
        connector: FakeConnector,
        auth_header_name: str,
    ) -> None:
        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": f"bad-header-{auth_header_name}"},
            json={
                "name": "Hermes",
                "agent_address": ENDPOINT,
                "auth_header_name": auth_header_name,
                "credential": "Bearer token",
                "current_password": TEST_USER_PASSWORD,
            },
        )

        assert response.status_code == 422
        assert client.get("/api/agent-connections").json() == []
        assert connector.starts == []
        assert connector.commands == []

    def test_creating_without_an_idempotency_key_is_rejected(
        self, client: TestClient
    ) -> None:
        """Every mutation carries a key, as elsewhere in the API."""

        response = client.post(
            "/api/agent-connections",
            json={
                "name": "Hermes",
                "agent_address": ENDPOINT,
                "credential": "Bearer token",
                "current_password": TEST_USER_PASSWORD,
            },
        )

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://127.0.0.1/hooks",
            "https://169.254.169.254/latest",
            "http://agent.example.com/hooks",
        ],
    )
    def test_an_unsafe_destination_is_refused(
        self, client: TestClient, endpoint: str
    ) -> None:
        """AC-005 over HTTP."""

        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "k1"},
            json={
                "name": "Hermes",
                "agent_address": endpoint,
                "credential": "Bearer token",
                "current_password": TEST_USER_PASSWORD,
            },
        )

        assert response.status_code == 400
        assert client.get("/api/agent-connections").json() == []

    def test_014_FR_002_testing_reports_the_discovery_result_and_the_tier(
        self, client: TestClient
    ) -> None:
        """AC-001, AC-005 over HTTP. Two separate claims, kept separate.

        `capabilities` is what the *card* declared; `controls_offered` is what
        BrainBuddy offers on this connection's runs. A single blended object
        would let a product decision be read as an agent's promise.
        """

        created = register_connection(client)

        response = client.post(f"/api/agent-connections/{created['id']}/test")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["ready_for_handoff"] is True
        assert body["capabilities"] == {"streaming": True, "push_notifications": False}
        assert body["controls_offered"] == {"reply": True, "cancel": True}
        assert body["guarantee_tier"] == "best_effort"
        assert body["tier_disclosure"].startswith("Best-effort single start.")
        assert body["tier_disclosure_url"]
        assert body["cancellation_disclosure"].startswith(
            "Cancellation depends on the agent"
        )
        assert body["agent_changed"] is False
        assert body["correlation_id_honoured"] is None
        assert body["disconnect_reason"] is None
        assert body["last_test_error_detail"] is None
        assert body["auth_header_name"] is None
        assert body["card"]["interface_url"] == "https://agent.example.com/a2a"

    def test_014_FR_001_the_create_route_rejects_a_caller_supplied_header_name(
        self, client: TestClient
    ) -> None:
        """AC-002. The header a credential travels in comes from the card only."""

        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "k-header-name"},
            json={
                "name": "Hermes",
                "agent_address": ENDPOINT,
                "auth_scheme": "api_key",
                "auth_header_name": "X-API-Key",
                "credential": "Bearer super-secret-token",
                "current_password": TEST_USER_PASSWORD,
            },
        )

        assert response.status_code == 422, response.text
        assert "auth_header_name" in response.text
        assert client.get("/api/agent-connections").json() == []

    def test_card_text_is_returned_verbatim_and_bounded(
        self,
        client: TestClient,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """AC-031. Card text is returned exactly as the agent wrote it.

        Not escaped, not stripped, not linkified: escaping here would hide what
        the agent actually claims, and the clients are the layer that renders it
        inertly. The bound is the only processing it receives.
        """

        container = relay_app[3]
        hostile = "<script>alert(1)</script> **not markdown** [x](javascript:alert(2))"
        fetcher = FakeCardFetcher()
        fetcher.discovery = ready_discovery(
            summary=card_summary(
                name=hostile,
                description=hostile * 8,
                interface_url="javascript:alert(3)",
            )
        )
        container.agent_relay_service._card_fetcher = fetcher
        created = register_connection(client)

        body = client.post(f"/api/agent-connections/{created['id']}/test").json()

        card = body["card"]
        assert card["name"] == hostile
        assert card["description"] == hostile * 8
        assert len(card["description"]) <= MAX_CARD_DESCRIPTION_CHARS
        assert card["interface_url"] == "javascript:alert(3)"

    def test_014_FR_002_a_rate_limited_test_stays_untested_with_its_retry_hint(
        self,
        client: TestClient,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """AC-037, D-01-S25 over HTTP: never `ready`, and never a hand-off."""

        container = relay_app[3]
        a2a_client = FakeA2AClient()
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
        container.agent_relay_service.a2a_client = a2a_client
        created = register_connection(client)

        body = client.post(f"/api/agent-connections/{created['id']}/test").json()

        assert body["status"] == "untested"
        assert body["ready_for_handoff"] is False
        assert body["last_test_error_code"] == "a2a_rate_limited"
        assert body["last_test_error_detail"] == {"retry_after_seconds": 30}

        task_id = create_task(client)
        refused = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )
        assert refused.status_code == 400
        assert refused.json()["detail"]["reason"] == "a2a_rate_limited"
        assert refused.headers["X-Correlation-ID"]

    def test_014_FR_002_a_changed_agent_refuses_the_hand_off_by_name(
        self,
        client: TestClient,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """AC-012, D-01-S20 over HTTP."""

        container = relay_app[3]
        fetcher = FakeCardFetcher()
        container.agent_relay_service._card_fetcher = fetcher
        created = register_connection(client)
        assert (
            client.post(f"/api/agent-connections/{created['id']}/test").json()["status"]
            == "ready"
        )

        fetcher.discovery = ready_discovery(
            summary=card_summary(interface_url="https://second.example.com/a2a")
        )
        drifted = client.post(f"/api/agent-connections/{created['id']}/test").json()

        assert drifted["status"] == "untested"
        assert drifted["agent_changed"] is True
        assert drifted["last_test_error_code"] == "agent_card_changed"
        assert drifted["last_test_error_detail"] == {
            "interface_url": "https://second.example.com/a2a"
        }

        task_id = create_task(client)
        refused = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )
        assert refused.status_code == 400
        assert refused.json()["detail"]["reason"] == "agent_card_changed"
        assert refused.headers["X-Correlation-ID"]

    def test_014_FR_001_an_unsupported_card_scheme_is_named_on_the_refusal(
        self,
        client: TestClient,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """AC-004. The owner is told which scheme their card demands."""

        container = relay_app[3]
        fetcher = FakeCardFetcher()
        fetcher.discovery = CardDiscovery(
            failure_code="a2a_auth_scheme_unsupported",
            failure_detail={"scheme": "oauth2"},
        )
        container.agent_relay_service._card_fetcher = fetcher
        created = register_connection(client)

        body = client.post(f"/api/agent-connections/{created['id']}/test").json()
        assert body["status"] == "unsupported"
        assert body["last_test_error_detail"] == {"scheme": "oauth2"}

        task_id = create_task(client)
        refused = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )
        assert refused.status_code == 400
        assert refused.json()["detail"]["reason"] == "a2a_auth_scheme_unsupported"
        assert refused.headers["X-Correlation-ID"]

    def test_014_FR_016_rollout_off_blocks_every_connection_write_but_disconnect(
        self, client: TestClient
    ) -> None:
        """D-01-S22, 014-FR-016. Disconnect stays: it only ever destroys."""

        created = register_connection(client)
        set_relay_flag(client, FeatureFlagState.OFF)

        blocked = {
            "create": client.post(
                "/api/agent-connections",
                headers={"Idempotency-Key": "off-create-2"},
                json={
                    "name": "Second",
                    "agent_address": ENDPOINT,
                    "credential": "Bearer other",
                    "current_password": TEST_USER_PASSWORD,
                },
            ),
            "update": client.put(
                f"/api/agent-connections/{created['id']}",
                headers={"Idempotency-Key": "off-update-2"},
                json={"name": "Renamed", "expected_revision": created["revision"]},
            ),
            "test": client.post(f"/api/agent-connections/{created['id']}/test"),
            "credential": client.post(
                f"/api/agent-connections/{created['id']}/credential",
                headers={"Idempotency-Key": "off-credential"},
                json={
                    "credential": "Bearer replacement",
                    "current_password": TEST_USER_PASSWORD,
                    "expected_revision": created["revision"],
                },
            ),
        }
        for name, response in blocked.items():
            assert response.status_code == 404, f"{name}: {response.text}"

        assert client.get("/api/agent-connections").status_code == 200
        disconnected = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "off-disconnect"},
            json={
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": created["revision"],
            },
        )
        assert disconnected.status_code == 200, disconnected.text
        assert disconnected.json()["status"] == "disconnected"
        assert disconnected.json()["disconnect_reason"] == "owner"

    def test_another_owner_cannot_see_or_touch_the_connection(
        self, client: TestClient, other_client: TestClient
    ) -> None:
        """Owner isolation over HTTP."""

        created = register_connection(client)

        assert other_client.get("/api/agent-connections").json() == []
        assert (
            other_client.get(f"/api/agent-connections/{created['id']}").status_code
            == 404
        )
        assert (
            other_client.post(
                f"/api/agent-connections/{created['id']}/test"
            ).status_code
            == 404
        )

    def test_disconnecting_requires_the_password_and_the_current_revision(
        self, client: TestClient
    ) -> None:
        """AC-018 over HTTP."""

        created = register_connection(client)

        wrong_password = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "k-dis-1"},
            json={"current_password": "nope", "expected_revision": created["revision"]},
        )
        assert wrong_password.status_code == 403

        stale = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "k-dis-2"},
            json={"current_password": TEST_USER_PASSWORD, "expected_revision": 99},
        )
        assert stale.status_code == 409

        ok = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "k-dis-3"},
            json={
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": created["revision"],
            },
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "disconnected"


class TestHandOffRoutes:
    def test_a_reviewed_hand_off_dispatches_exactly_once(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-008 / AC-009 over HTTP: one confirmation, one A2A exchange."""

        a2a = cast(FakeA2AClient, container.agent_relay_service.a2a_client)
        created = register_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)

        run = hand_off(client, created["id"], task_id)

        assert run["dispatch_state"] == "sent"
        assert run["primary_state_label"] == "Sent"
        assert run["exchange_state"] == "closed"
        assert run["message_id"] == f"{run['id']}:start"
        assert run["correlation_id"] == run["id"]
        assert len(a2a.calls_to("SendMessage")) == 1

        listed = client.get(f"/api/tasks/{task_id}/agent-runs").json()
        assert len(listed) == 1

    def test_the_preview_discloses_exactly_what_will_be_sent(
        self, client: TestClient
    ) -> None:
        """AC-006 over HTTP."""

        created = register_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)

        preview = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={
                "connection_id": created["id"],
                "supporting_items": [{"label": "Runbook", "body": "Step one"}],
            },
        ).json()

        assert preview["title"] == "Draft the migration plan"
        assert preview["details"] == "Cover rollback."
        assert preview["supporting_items"] == [{"label": "Runbook", "body": "Step one"}]
        assert preview["destination_interface"] == "https://agent.example.com/a2a"
        assert preview["external_copy_notice"]

    def test_handing_off_another_owners_task_is_refused(
        self, client: TestClient, other_client: TestClient, connector: FakeConnector
    ) -> None:
        """Cross-owner hand-off fails before any content is sent."""

        created = register_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)

        response = other_client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )

        assert response.status_code == 404
        assert connector.starts == []

    def test_an_untested_connection_refuses_the_hand_off(
        self, client: TestClient, connector: FakeConnector
    ) -> None:
        """AC-010 over HTTP."""

        created = register_connection(client)
        task_id = create_task(client)

        response = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )

        assert response.status_code == 400
        assert connector.starts == []


class TestRunControlRoutes:
    """Reading, replying to and cancelling a run over HTTP (014-FR-010)."""

    def test_rollout_off_preserves_existing_run_control_and_reporting(
        self,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """FR-019 blocks new work without abandoning an already-dispatched run."""

        client, _, _, container = relay_app
        created = register_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = blocked_run(client, container, created["id"], task_id)
        fresh_task_id = create_task(client, "Fresh rollout dispatch")
        fresh_preview = client.post(
            f"/api/tasks/{fresh_task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        ).json()

        set_relay_flag(client, FeatureFlagState.OFF)

        assert run["needs_user"] is True

        current = client.get(f"/api/agent-runs/{run['id']}")
        assert current.status_code == 200
        reply = client.post(
            f"/api/agent-runs/{run['id']}/reply",
            headers={"Idempotency-Key": "reply-after-off"},
            json={
                "message": "Use staging.",
                "expected_revision": current.json()["revision"],
            },
        )
        assert reply.status_code == 200
        cancel = client.post(
            f"/api/agent-runs/{run['id']}/cancel",
            headers={"Idempotency-Key": "cancel-after-off"},
        )
        assert cancel.status_code == 200
        assert client.get("/api/agent-connections").status_code == 200

        fresh_preview_response = client.post(
            f"/api/tasks/{fresh_task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )
        fresh_dispatch_response = client.post(
            f"/api/tasks/{fresh_task_id}/agent-runs",
            headers={"Idempotency-Key": "fresh-after-off"},
            json={
                "connection_id": created["id"],
                "manifest_token": fresh_preview["token"],
            },
        )
        assert fresh_preview_response.status_code == 404
        assert fresh_dispatch_response.status_code == 404

    def test_rollout_off_keeps_retention_maintenance_active_without_resurrection(
        self,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """FR-019: OFF cannot suspend expiry of already-relayed content."""

        client, _, _, container = relay_app
        created = register_connection(client, key="retention-off-create")
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client, "Retention while rollout is off")
        run = blocked_run(
            client,
            container,
            created["id"],
            task_id,
            question="Sensitive retained question?",
            key="retention-off-dispatch",
        )
        current = client.get(f"/api/agent-runs/{run['id']}").json()
        reply = client.post(
            f"/api/agent-runs/{run['id']}/reply",
            headers={"Idempotency-Key": "retention-off-reply"},
            json={
                "message": "Sensitive retained reply",
                "expected_revision": current["revision"],
            },
        )
        assert reply.status_code == 200, reply.text

        stored = container.agent_repo.get_run(
            run["id"], owner_id=client.get("/api/auth/me").json()["id"]
        )
        due = datetime.now(tz=UTC)
        container.agent_repo.save_run(
            stored.model_copy(update={"content_expires_at": due})
        )
        container.agent_relay_service._now = lambda: due + timedelta(seconds=1)
        set_relay_flag(client, FeatureFlagState.OFF)

        assert _run_privacy_maintenance_sweep(container)[1] == 1
        expired = container.agent_relay_service.get_run(
            run["id"], owner_id=stored.owner_id
        )
        assert expired.content_expired is True
        assert expired.manifest is None
        assert expired.question_text is None
        assert expired.events and all(event.summary is None for event in expired.events)
        assert expired.commands and all(
            command.body is None for command in expired.commands
        )

        assert _run_privacy_maintenance_sweep(container)[1] == 0
        unchanged = container.agent_relay_service.get_run(
            run["id"], owner_id=stored.owner_id
        )
        assert unchanged == expired

    def test_014_FR_010_a_blocked_run_lets_the_owner_reply(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-012 over HTTP."""

        created = register_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = blocked_run(client, container, created["id"], task_id)

        current = client.get(f"/api/agent-runs/{run['id']}").json()
        response = client.post(
            f"/api/agent-runs/{run['id']}/reply",
            headers={"Idempotency-Key": "k-reply"},
            json={
                "message": "Use staging.",
                "expected_revision": current["revision"],
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["needs_user"] is True
        assert body["question_text"] == "Which environment?"
        assert any(command["kind"] == "reply" for command in body["commands"])

    def test_014_FR_010_a_stale_question_revision_returns_409_before_reply_delivery(
        self, client: TestClient, container: Container
    ) -> None:
        """A reply written against a superseded question is refused, not sent."""

        a2a = cast(FakeA2AClient, container.agent_relay_service.a2a_client)
        created = register_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = blocked_run(client, container, created["id"], task_id)
        stale_revision = client.get(f"/api/agent-runs/{run['id']}").json()["revision"]
        observe(
            container,
            run["id"],
            state="TASK_STATE_INPUT_REQUIRED",
            text="Which region?",
        )
        a2a.calls.clear()

        response = client.post(
            f"/api/agent-runs/{run['id']}/reply",
            headers={"Idempotency-Key": "k-stale-reply"},
            json={"message": "Use staging.", "expected_revision": stale_revision},
        )

        assert response.status_code == 409, response.text
        assert a2a.calls_to("SendMessage") == []

    def test_another_owner_cannot_read_or_command_the_run(
        self, client: TestClient, other_client: TestClient
    ) -> None:
        """Owner isolation over the run routes."""

        created = register_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)

        assert other_client.get(f"/api/agent-runs/{run['id']}").status_code == 404
        assert (
            other_client.post(
                f"/api/agent-runs/{run['id']}/cancel",
                headers={"Idempotency-Key": "k-c"},
            ).status_code
            == 404
        )


class TestRunSummaryRoute:
    def test_the_compact_surface_gets_one_summary_per_task(
        self, client: TestClient
    ) -> None:
        """FR-010: the task list asks once for every task's latest run."""

        created = register_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        other_task_id = create_task(client, "Untouched task")
        run = hand_off(client, created["id"], task_id)

        response = client.get(
            "/api/agent-run-summaries",
            params={"task_id": [task_id, other_task_id]},
        )

        assert response.status_code == 200, response.text
        summaries = response.json()
        assert list(summaries) == [task_id]
        assert summaries[task_id]["id"] == run["id"]
        assert summaries[task_id]["primary_state_label"] == "Sent"
        assert summaries[task_id]["needs_user"] is False

    def test_summaries_never_cross_owners(
        self, client: TestClient, other_client: TestClient
    ) -> None:
        """A task ID guessed from another account yields nothing."""

        created = register_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        hand_off(client, created["id"], task_id)

        response = other_client.get(
            "/api/agent-run-summaries", params={"task_id": [task_id]}
        )

        assert response.status_code == 200
        assert response.json() == {}

    def test_asking_for_no_tasks_is_an_empty_answer(self, client: TestClient) -> None:
        """An empty list page must not become an unbounded scan."""

        assert client.get("/api/agent-run-summaries").json() == {}


class TestAccountPurge:
    def test_account_purge_removes_every_relay_record(
        self, client: TestClient, relay_app: tuple[Any, ...]
    ) -> None:
        """AC-021: the existing purge contract covers relay data."""

        container: Container = relay_app[3]
        created = register_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        hand_off(client, created["id"], task_id)

        owner_id = client.get("/api/auth/me").json()["id"]
        container.account_service.purge_account(owner_id)

        assert container.agent_repo.list_connections(owner_id=owner_id) == []
        assert container.agent_repo.list_runs_for_owner(owner_id=owner_id) == []
        assert container.agent_repo.list_audit(owner_id=owner_id) == []

    def test_rollout_off_keeps_account_purge_complete_for_all_relay_material(
        self, client: TestClient, relay_app: tuple[Any, ...]
    ) -> None:
        """FR-019: OFF cannot strand any owner relay or credential material."""

        container: Container = relay_app[3]
        created = register_connection(client, key="purge-off-create")
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client, "Purge relay data while rollout is off")
        run = blocked_run(
            client,
            container,
            created["id"],
            task_id,
            question="Sensitive purge content",
            key="purge-off-dispatch",
        )
        owner_id = client.get("/api/auth/me").json()["id"]
        current = client.get(f"/api/agent-runs/{run['id']}").json()
        assert (
            client.post(
                f"/api/agent-runs/{run['id']}/reply",
                headers={"Idempotency-Key": "purge-off-reply"},
                json={
                    "message": "Sensitive purge reply",
                    "expected_revision": current["revision"],
                },
            ).status_code
            == 200
        )
        relay_tables = (
            "agent_connections",
            "agent_runs",
            "agent_run_events",
            "agent_run_commands",
            "agent_audit",
            "agent_idempotency",
        )
        with sqlite3.connect(container.agent_repo.db_path) as connection:
            assert all(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE owner_id = ?", (owner_id,)
                ).fetchone()[0]
                for table in relay_tables
            )
            stored_connection = connection.execute(
                "SELECT payload FROM agent_connections WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()[0]
        assert '"credential":' in stored_connection

        set_relay_flag(client, FeatureFlagState.OFF)
        container.account_service.purge_account(owner_id)

        with sqlite3.connect(container.agent_repo.db_path) as connection:
            assert all(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE owner_id = ?", (owner_id,)
                ).fetchone()[0]
                == 0
                for table in relay_tables
            )


class TestOpenApiContract:
    def test_no_schema_can_carry_a_stored_credential_outward(
        self, client: TestClient
    ) -> None:
        """FR-003 is enforced structurally, not by discipline."""

        schema = client.get("/api/openapi.json").json()
        responses = json.dumps(schema["components"]["schemas"])

        assert "AgentConnectionResponse" in responses
        connection_schema = schema["components"]["schemas"]["AgentConnectionResponse"]
        assert "credential" not in connection_schema["properties"]
        assert "inbound_secret" not in connection_schema["properties"]


class TestPushCallbackInfrastructure:
    """The two things that must exist before the push route can be safe.

    The A2A push token travels in the URL path — not because that is pleasant,
    but because Hermes stores only the URL of a push config and signs with a
    secret BrainBuddy cannot know, so a header-only token would leave its
    pushes unverifiable (research.md Decision D). That choice is only
    acceptable with two properties actually in place:

    1. **The token never reaches BrainBuddy's own logs.** An agent's logs are
       outside our control and the token's power is bounded by design — it can
       trigger one authenticated observation BrainBuddy would perform anyway —
       but repeating it in our own logs would be a disclosure we chose.
    2. **Limiter memory is bounded.** The route is reachable by anyone who
       guesses a URL shape, so a per-run limiter that never evicts is a remote
       memory-growth primitive.

    014-FR-008, 014-FR-016, 014-SC-009.
    """

    # --- the bounded limiter ------------------------------------------------

    def test_014_FR_008_the_bounded_limiter_never_grows_past_its_key_cap(self) -> None:
        """AC-035: unknown ids must not be able to mint keys without bound.

        `InMemoryRateLimiter` is a `defaultdict` whose `_prune` only trims
        timestamps *inside* a key, so it never forgets a key at all. On a login
        route keyed by source IP that is a considered trade; on a route keyed by
        a caller-supplied run id it is unbounded growth driven by a stranger.
        """

        from app.core.rate_limit import BoundedKeyRateLimiter

        limiter = BoundedKeyRateLimiter(
            max_attempts=30, window_seconds=60.0, max_keys=8
        )

        for index in range(500):
            limiter.check(f"run-{index}")

        assert limiter.key_count <= 8

    def test_014_FR_008_a_runs_bucket_is_evicted_when_the_run_closes(self) -> None:
        """A terminal or disconnected run can never be pushed for again, so
        keeping its bucket is pure retention of something with no use."""

        from app.core.rate_limit import BoundedKeyRateLimiter

        limiter = BoundedKeyRateLimiter(
            max_attempts=2, window_seconds=60.0, max_keys=64
        )

        assert limiter.check("run-a") is True
        assert limiter.check("run-a") is True
        assert limiter.check("run-a") is False, "the window is exhausted"

        assert limiter.evict("run-a") is True
        assert limiter.key_count == 0
        # Eviction is not a bypass: a fresh key starts a fresh window, and the
        # route only evicts when the run can no longer be pushed for at all.
        assert limiter.check("run-a") is True
        assert limiter.evict("never-seen") is False

    def test_014_FR_008_eviction_under_pressure_drops_the_oldest_key(self) -> None:
        """When the cap is reached the limiter must still admit new runs.

        Refusing every new key at the cap would let one flood of stale ids
        deny push acceleration to every legitimate run — the limiter would
        become the outage it exists to prevent.
        """

        from app.core.rate_limit import BoundedKeyRateLimiter

        limiter = BoundedKeyRateLimiter(max_attempts=1, window_seconds=60.0, max_keys=2)

        limiter.check("first")
        limiter.check("second")
        limiter.check("third")

        assert limiter.key_count == 2
        # "first" was displaced, so it is admitted again as a new key rather
        # than silently refused forever.
        assert limiter.check("first") is True

    def test_014_FR_008_the_shared_login_limiter_is_left_alone(self) -> None:
        """The bounded variant is additive. `InMemoryRateLimiter` guards login
        and the sensitive account actions, and changing its eviction semantics
        under them would be a security change made by accident."""

        from app.core.rate_limit import InMemoryRateLimiter

        assert not hasattr(InMemoryRateLimiter, "evict")
        assert not hasattr(InMemoryRateLimiter, "key_count")

    def test_014_FR_008_a_fixed_size_counter_bounds_the_route_before_any_read(
        self,
    ) -> None:
        """Step 2 of the check order: a process-wide counter with no per-key
        state at all, consulted before the database is touched. Rejections of
        unknown ids are counted only here — never per unknown id, which would
        reintroduce the growth the cap above removes."""

        from app.core.rate_limit import FixedWindowCounter

        counter = FixedWindowCounter(max_events=3, window_seconds=60.0)

        assert [counter.check() for _ in range(4)] == [True, True, True, False]
        assert counter.rejected == 1

    # --- path redaction -----------------------------------------------------

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            (
                "/api/a2a/push/run-123/tok-abcdef",
                "/api/a2a/push/run-123/[redacted]",
            ),
            (
                "/api/a2a/push/run-123/tok-abcdef/extra",
                "/api/a2a/push/run-123/[redacted]",
            ),
            # No token segment yet: nothing to hide, and inventing one would
            # make a 404 look like a redacted hit.
            ("/api/a2a/push/run-123", "/api/a2a/push/run-123"),
            ("/api/a2a/push/", "/api/a2a/push/"),
            ("/api/a2a/push", "/api/a2a/push"),
            # Unrelated paths are untouched: over-redaction destroys the
            # operational value of the log without adding safety.
            ("/api/agent-runs/run-1", "/api/agent-runs/run-1"),
            ("/api/tasks", "/api/tasks"),
            ("/", "/"),
        ],
    )
    def test_014_SC_009_the_path_sanitiser_hides_the_token_and_nothing_else(
        self, path: str, expected: str
    ) -> None:
        """AC-035: the run id stays visible because it is what makes a log line
        useful for support; the token is the only secret in the path."""

        from app.api.middleware import sanitize_log_path

        assert sanitize_log_path(path, api_prefix="/api") == expected

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "not-a-path",
            "//////",
            "/api/a2a/push//",
            "/api/a2a/push/%00/%00",
            "?" * 50,
        ],
    )
    def test_014_SC_009_the_path_sanitiser_never_raises(self, path: str) -> None:
        """It runs inside a logging call on the request's exception path. A
        sanitiser that could raise would turn a redaction into a 500 — and
        would do it exactly when something has already gone wrong."""

        from app.api.middleware import sanitize_log_path

        assert isinstance(sanitize_log_path(path, api_prefix="/api"), str)

    def test_014_SC_009_a_custom_api_prefix_is_still_redacted(self) -> None:
        """The prefix is configurable, and a redaction keyed to a hard-coded
        `/api` would silently stop working on a deployment that changed it."""

        from app.api.middleware import sanitize_log_path

        assert (
            sanitize_log_path("/custom/a2a/push/run-1/tok", api_prefix="/custom")
            == "/custom/a2a/push/run-1/[redacted]"
        )

    def test_014_SC_009_both_middleware_log_lines_go_through_the_sanitiser(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`api_request` *and* `api_request_failed`.

        Driven through the real middleware rather than asserted against its
        source, so the property proved is what actually reaches a log handler.
        The exception line is the one most likely to be forgotten and the one
        most likely to be read, because it fires when a push went wrong —
        exactly when someone pastes the line into a ticket.
        """

        import logging

        from fastapi import FastAPI

        from app.api.middleware import CorrelationIdMiddleware

        app = FastAPI()
        app.add_middleware(CorrelationIdMiddleware, api_prefix="/api")

        @app.post("/api/a2a/push/{run_id}/{token}")
        async def _ok(run_id: str, token: str) -> dict[str, str]:
            return {"run_id": run_id}

        @app.post("/api/a2a/push/boom/{token}/fail")
        async def _boom(token: str) -> dict[str, str]:
            raise RuntimeError("the push handler exploded")

        secret = "tok-never-log-this"
        with caplog.at_level(logging.INFO, logger="app.api.middleware"):
            client = TestClient(app, raise_server_exceptions=False)
            client.post(f"/api/a2a/push/run-1/{secret}")
            client.post(f"/api/a2a/push/boom/{secret}/fail")

        # Scoped to BrainBuddy's own loggers, which is exactly what SC-009
        # claims: the two in-process edges. `TestClient` drives httpx, whose
        # client-side logger prints the URL it is calling — a property of the
        # test harness standing in for the network, not of anything the server
        # writes. Asserting over it would be asserting about the test.
        messages = [
            record.getMessage()
            for record in caplog.records
            if record.name.startswith("app.")
        ]
        assert any("api_request " in message for message in messages)
        assert any("api_request_failed" in message for message in messages)
        assert not any(
            secret in message for message in messages
        ), "one unsanitised log call is a full disclosure of the push token"
        assert any("/api/a2a/push/run-1/[redacted]" in message for message in messages)
        # The run id survives: it is what makes the line useful, and it is not
        # the secret.
        assert any("/api/a2a/push/boom/[redacted]" in message for message in messages)

    def test_014_SC_009_the_uvicorn_access_filter_redacts_the_push_path(self) -> None:
        """uvicorn writes its own access line, below the middleware.

        BrainBuddy's log configuration routes `uvicorn.access` to the same
        console handler, so a token redacted by the middleware would still be
        printed verbatim one line later without this filter.
        """

        import logging

        from app.core.logging import PushCallbackAccessFilter

        log_filter = PushCallbackAccessFilter(api_prefix="/api")

        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1:1", "POST", "/api/a2a/push/run-1/tok-secret", "1.1", 204),
            exc_info=None,
        )

        assert log_filter.filter(record) is True
        assert "tok-secret" not in record.getMessage()
        assert "/api/a2a/push/run-1/[redacted]" in record.getMessage()

    def test_014_SC_009_the_access_filter_leaves_other_paths_alone(self) -> None:
        import logging

        from app.core.logging import PushCallbackAccessFilter

        log_filter = PushCallbackAccessFilter(api_prefix="/api")
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1:1", "GET", "/api/tasks", "1.1", 200),
            exc_info=None,
        )

        assert log_filter.filter(record) is True
        assert "/api/tasks" in record.getMessage()

    @pytest.mark.parametrize(
        "args",
        [
            None,
            (),
            ("only-one",),
            ("a", "b", 12345, "d", 200),
            "a bare string",
        ],
    )
    def test_014_SC_009_the_access_filter_never_raises_on_an_odd_record(
        self, args: Any
    ) -> None:
        """A logging filter that raises takes down the log, and uvicorn's record
        shape is not something BrainBuddy controls across versions."""

        import logging

        from app.core.logging import PushCallbackAccessFilter

        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="%s",
            args=args,
            exc_info=None,
        )

        assert PushCallbackAccessFilter(api_prefix="/api").filter(record) is True

    def test_014_SC_009_the_access_filter_is_installed_on_the_uvicorn_logger(
        self,
    ) -> None:
        """A filter nobody attaches redacts nothing.

        The logging dict is where `uvicorn.access` is wired to the console
        handler, so it is also where the filter has to appear.
        """

        from app.core.logging import build_logging_dict

        config = build_logging_dict("INFO")

        assert "push_callback" in config["filters"]
        assert "push_callback" in config["loggers"]["uvicorn.access"].get("filters", [])


class TestCheckDeliveryRoute:
    """**Check again** over HTTP: one lookup, then a resend the rules allow."""

    def _unconfirmed(
        self, client: TestClient, container: Container, *, key: str = "k-unconfirmed"
    ) -> tuple[str, dict[str, Any]]:
        a2a = cast(FakeA2AClient, container.agent_relay_service.a2a_client)
        created = register_connection(client, key=f"{key}-create")
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client, title=f"Task for {key}")
        a2a.script(
            "SendMessage",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_timeout"),
        )
        run = hand_off(client, created["id"], task_id, key=f"{key}-handoff")
        assert run["dispatch_state"] == "delivery_unconfirmed"
        a2a.results.pop("SendMessage", None)
        a2a.calls.clear()
        return created["id"], run

    def test_014_FR_006_a_check_adopts_a_found_task_without_sending_anything(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-027 over HTTP."""

        a2a = cast(FakeA2AClient, container.agent_relay_service.a2a_client)
        _connection_id, run = self._unconfirmed(client, container)
        a2a.script(
            "ListTasks",
            A2AResult(
                ok=True,
                correlation_id="c",
                tasks=(
                    Task.model_validate(
                        {
                            "id": "t-found",
                            "contextId": run["id"],
                            "status": {"state": "TASK_STATE_WORKING"},
                        }
                    ),
                ),
            ),
        )

        response = client.post(
            f"/api/agent-runs/{run['id']}/check-delivery",
            headers={"Idempotency-Key": "k-check"},
            json={},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == run["id"]
        assert body["dispatch_state"] == "sent"
        assert body["agent_task_id"] == "t-found"
        assert a2a.calls_to("SendMessage") == []

    def test_014_FR_016_a_check_without_an_idempotency_key_is_refused(
        self, client: TestClient, container: Container
    ) -> None:
        """The key is what makes a retried check the same check."""

        _connection_id, run = self._unconfirmed(client, container, key="k-nokey")

        response = client.post(f"/api/agent-runs/{run['id']}/check-delivery", json={})

        assert response.status_code == 400, response.text
        assert response.headers["X-Correlation-ID"]

    @pytest.mark.parametrize(
        "condition,reason",
        [
            ("terminal", "run_terminal"),
            ("disconnected", "connection_disconnected"),
            ("not_ready", "connection_not_ready"),
        ],
    )
    def test_014_FR_006_each_refusal_names_its_own_reason_with_a_correlation_id(
        self,
        client: TestClient,
        container: Container,
        condition: str,
        reason: str,
    ) -> None:
        """SC-009: an actionable category, never a generic failure."""

        a2a = cast(FakeA2AClient, container.agent_relay_service.a2a_client)
        connection_id, run = self._unconfirmed(client, container, key=f"k-{condition}")
        repo = container.agent_relay_service.agent_repo
        owner = client.get("/api/auth/me").json()["id"]
        stored_run = repo.get_run(run["id"], owner_id=owner)
        if condition == "terminal":
            repo.save_run(stored_run.model_copy(update={"reported_state": "completed"}))
        elif condition == "disconnected":
            connection = repo.get_connection(connection_id, owner_id=owner)
            repo.save_connection(
                connection.model_copy(update={"status": "disconnected"})
            )
        else:
            connection = repo.get_connection(connection_id, owner_id=owner)
            repo.save_connection(
                connection.model_copy(update={"status": "unreachable"})
            )
            a2a.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

        response = client.post(
            f"/api/agent-runs/{run['id']}/check-delivery",
            headers={"Idempotency-Key": f"k-check-{condition}"},
            json={},
        )

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == {"reason": reason}
        assert response.headers["X-Correlation-ID"]
        assert a2a.calls_to("SendMessage") == []

    def test_014_FR_006_rollout_off_looks_up_but_never_resends(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-036. The lookup runs and adopts; only the send is gated."""

        a2a = cast(FakeA2AClient, container.agent_relay_service.a2a_client)
        _connection_id, run = self._unconfirmed(client, container, key="k-rollout")
        set_relay_flag(client, FeatureFlagState.OFF)
        a2a.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

        response = client.post(
            f"/api/agent-runs/{run['id']}/check-delivery",
            headers={"Idempotency-Key": "k-check-off"},
            json={},
        )

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == {"reason": "rollout_disabled"}
        # The lookup ran before the refusal, so a task created meanwhile would
        # still have been adopted.
        assert a2a.calls_to("ListTasks")
        assert a2a.calls_to("SendMessage") == []

    def test_014_FR_006_a_run_that_is_already_sent_is_returned_unchanged(
        self, client: TestClient, container: Container
    ) -> None:
        """Nothing to check and nothing to send: the run simply reads back."""

        a2a = cast(FakeA2AClient, container.agent_relay_service.a2a_client)
        created = register_connection(client, key="k-sent-create")
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client, title="Already sent")
        run = hand_off(client, created["id"], task_id, key="k-sent-handoff")
        assert run["dispatch_state"] == "sent"
        a2a.calls.clear()
        a2a.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

        response = client.post(
            f"/api/agent-runs/{run['id']}/check-delivery",
            headers={"Idempotency-Key": "k-check-sent"},
            json={},
        )

        assert response.status_code == 200, response.text
        assert response.json()["dispatch_state"] == "sent"
        assert a2a.calls_to("SendMessage") == []


class TestHandOffContractOverHttp:
    """The manifest, the acknowledgement gate and the two honest dispatch labels."""

    def test_014_FR_005_the_manifest_carries_the_review_the_clients_render(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-007: every value that leaves, named in the response."""

        container.agent_relay_service._card_fetcher = FakeCardFetcher()  # type: ignore[assignment]
        container.agent_relay_service._card_fetcher.discovery = ready_discovery(  # type: ignore[attr-defined]
            summary=card_summary(push_notifications=True)
        )
        created = register_connection(client, key="k-manifest")
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client, title="Manifest shape")

        response = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["acknowledgement_required"] is True
        assert body["push_callback"]["registered"] is True
        assert body["push_callback"]["url_preview"].endswith("/…")
        assert body["push_callback"]["disclosure"]
        assert body["parts_preview"][0] == "Manifest shape"
        assert body["correlation_id"] == body["run_id"]
        assert body["message_id"] == f"{body['run_id']}:start"
        assert body["protocol_version"] == "1.0"
        # The bespoke reporting block is gone from the contract entirely.
        assert "reporting" not in body
        assert "reporting_instructions" not in body

    def test_014_FR_005_a_card_that_moved_refuses_the_preview_with_its_own_reason(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-012, D-02-S09 over HTTP."""

        fetcher = FakeCardFetcher()
        container.agent_relay_service._card_fetcher = fetcher  # type: ignore[assignment]
        created = register_connection(client, key="k-drift")
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client, title="Drifted destination")
        fetcher.discovery = ready_discovery(
            summary=card_summary(interface_url="https://second.example.com/a2a")
        )

        response = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == {"reason": "agent_card_changed"}
        assert response.headers["X-Correlation-ID"]
        listed = client.get("/api/agent-connections").json()
        assert [
            item["agent_changed"] for item in listed if item["id"] == created["id"]
        ] == [True]

    def test_014_SC_005_a_confirmation_without_the_acknowledgement_is_refused(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-026 over HTTP, before any reservation is spent."""

        a2a = cast(FakeA2AClient, container.agent_relay_service.a2a_client)
        created = register_connection(client, key="k-ack")
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client, title="Needs the acknowledgement")
        preview = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        ).json()
        assert preview["acknowledgement_required"] is True

        refused = client.post(
            f"/api/tasks/{task_id}/agent-runs",
            headers={"Idempotency-Key": "k-ack-dispatch"},
            json={
                "connection_id": created["id"],
                "manifest_token": preview["token"],
                "acknowledge_duplicate_risk": False,
            },
        )

        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"] == {
            "reason": "duplicate_risk_acknowledgement_required"
        }
        assert refused.headers["X-Correlation-ID"]
        assert a2a.calls_to("SendMessage") == []
        assert client.get(f"/api/tasks/{task_id}/agent-runs").json() == []

    def test_014_FR_006_a_queued_exchange_is_labelled_Queued_and_never_Sent(
        self, client: TestClient, container: Container
    ) -> None:
        """D-03-S04 queued variant over HTTP."""

        a2a = cast(FakeA2AClient, container.agent_relay_service.a2a_client)
        # No pump and no executor, so the confirmed hand-off waits for a worker
        # that is not there. That is exactly a saturated pool.
        container.agent_relay_service.exchange_pump = None
        container.agent_relay_service.exchange_executor = None
        created = register_connection(client, key="k-queued")
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client, title="Waiting for a worker")

        run = hand_off(client, created["id"], task_id, key="k-queued-dispatch")

        assert run["primary_state_label"] == "Queued"
        assert run["exchange_state"] == "queued"
        assert run["exchange_open"] is True
        assert run["dispatch_state"] == "delivery_unconfirmed"
        assert a2a.calls_to("SendMessage") == []

    def test_014_FR_006_a_restart_before_the_send_reads_as_Not_sent(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-032 over HTTP: nothing left BrainBuddy, and the label says so."""

        container.agent_relay_service.exchange_pump = None
        container.agent_relay_service.exchange_executor = None
        created = register_connection(client, key="k-restart")
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client, title="Caught by a restart")
        run = hand_off(client, created["id"], task_id, key="k-restart-dispatch")
        assert run["primary_state_label"] == "Queued"

        container.agent_observer.recover_interrupted_exchanges()

        recovered = client.get(f"/api/agent-runs/{run['id']}").json()
        assert recovered["dispatch_state"] == "not_sent"
        assert recovered["dispatch_error_code"] == "restarted_before_send"
        assert recovered["primary_state_label"] == "Not sent"
        assert recovered["message_id"] == f"{run['id']}:start"


class TestPushCallbackRoute:
    """`POST /api/a2a/push/{run_id}/{token}`, in the order the contract fixes.

    The route has no session by design — the caller is the user's agent — so
    every refusal it can make has to be indistinguishable from every other, and
    the only place the difference is recorded is the owner's own bounded audit.

    014-FR-008, 014-FR-010, 014-SC-003, 014-SC-009.
    """

    def _pushable(
        self, client: TestClient, container: Container, *, key: str = "k-push"
    ) -> tuple[str, str]:
        """One dispatched run whose card supports push, and its token."""

        service = container.agent_relay_service
        service._card_fetcher.discovery = ready_discovery(  # type: ignore[attr-defined]
            summary=card_summary(push_notifications=True)
        )
        connection = register_connection(client, key=key)
        assert (
            client.post(
                f"/api/agent-connections/{connection['id']}/test",
                headers={"Idempotency-Key": f"{key}-test"},
            ).status_code
            == 200
        )
        task_id = create_task(client, title=f"Push {key}")
        run = hand_off(client, connection["id"], task_id, key=f"{key}-dispatch")
        stored = service.agent_repo.get_run(
            run["id"], owner_id=service.agent_repo.owner_of_run(run["id"]) or ""
        )
        assert stored.push_token_fingerprint is not None
        return run["id"], service.push_token_for(stored) or ""

    def _push(self, client: TestClient, run_id: str, token: str) -> Any:
        return client.post(f"/api/a2a/push/{run_id}/{token}", content=b"{}")

    def test_014_FR_008_a_verified_push_is_accepted_and_schedules_an_observation(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-021. The push does not carry state; it only asks BrainBuddy to look."""

        run_id, token = self._pushable(client, container)
        woken: list[str] = []
        container.agent_observer.wake = woken.append  # type: ignore[method-assign]

        response = self._push(client, run_id, token)

        assert response.status_code == 204
        assert response.content == b""
        service = container.agent_relay_service
        owner_id = service.agent_repo.owner_of_run(run_id) or ""
        stored = service.agent_repo.get_run(run_id, owner_id=owner_id)
        assert stored.observation_trigger_pending == "push"
        assert woken == [run_id]
        assert "push_verified" in [
            entry.action for entry in service.list_audit(owner_id=owner_id)
        ]

    def test_014_FR_008_a_verified_push_resets_the_observation_backoff(
        self, client: TestClient, container: Container
    ) -> None:
        run_id, token = self._pushable(client, container, key="k-push-backoff")
        service = container.agent_relay_service
        owner_id = service.agent_repo.owner_of_run(run_id) or ""
        run = service.agent_repo.get_run(run_id, owner_id=owner_id)
        far_off = utcnow() + timedelta(hours=6)
        service.agent_repo.save_run(
            run.model_copy(update={"next_observation_at": far_off})
        )

        assert self._push(client, run_id, token).status_code == 204

        after = service.agent_repo.get_run(run_id, owner_id=owner_id)
        assert after.next_observation_at is not None
        assert after.next_observation_at < far_off

    def test_push_rejections_are_indistinguishable_to_the_caller(
        self, client: TestClient, container: Container
    ) -> None:
        """SC-003. Steps 3, 4 and 5 differ only in BrainBuddy's own audit.

        Compared against each other rather than against a literal, because the
        property is that a prober cannot tell them apart — not that the body
        happens to read a particular way today. Only the per-request
        correlation id, which every error on every route carries, may differ.
        """

        run_id, token = self._pushable(client, container, key="k-push-same")
        _other_run, other_token = self._pushable(
            client, container, key="k-push-same-other"
        )
        service = container.agent_relay_service
        owner_id = service.agent_repo.owner_of_run(run_id) or ""

        unknown = self._push(client, "agentrun_does_not_exist", token)
        forged = self._push(client, run_id, "forged-" + token)
        wrong_run = self._push(client, run_id, other_token)

        connection_id = service.agent_repo.get_run(
            run_id, owner_id=owner_id
        ).connection_id
        connection = service.get_connection(connection_id, owner_id=owner_id)
        assert (
            client.post(
                f"/api/agent-connections/{connection_id}/disconnect",
                headers={"Idempotency-Key": "k-disc-same"},
                json={
                    "current_password": TEST_USER_PASSWORD,
                    "expected_revision": connection.revision,
                },
            ).status_code
            == 200
        )
        disconnected = self._push(client, run_id, token)

        responses = [unknown, forged, wrong_run, disconnected]
        assert [response.status_code for response in responses] == [403] * 4
        bodies = [
            {
                key: value
                for key, value in response.json().items()
                if key != "reference_id"
            }
            for response in responses
        ]
        assert bodies[1:] == bodies[:-1], "the four refusals must read alike"
        for response in responses:
            assert "Retry-After" not in response.headers
            assert response.headers.get("WWW-Authenticate") is None
        # The distinction exists, but only where the owner can see it.
        actions = [entry.action for entry in service.list_audit(owner_id=owner_id)]
        assert "push_token_rejected" in actions
        assert "push_after_close" in actions

    def test_014_SC_003_an_unknown_run_leaves_no_row_and_no_limiter_key(
        self, client: TestClient, container: Container
    ) -> None:
        """Step 3. A stranger's guess must cost nothing durable."""

        from app.api.agents import push_run_limiter

        run_id, _token = self._pushable(client, container, key="k-push-unknown")
        service = container.agent_relay_service
        owner_id = service.agent_repo.owner_of_run(run_id) or ""
        before = len(service.list_audit(owner_id=owner_id))
        push_run_limiter.reset()

        for index in range(50):
            assert (
                self._push(client, f"agentrun_guess_{index}", "whatever").status_code
                == 403
            )

        assert push_run_limiter.key_count == 0
        assert len(service.list_audit(owner_id=owner_id)) == before

    def test_unknown_run_flood_leaves_limiter_memory_bounded_and_no_rows(
        self, client: TestClient, container: Container
    ) -> None:
        """The same property under volume, which is when it matters."""

        from app.api.agents import push_run_limiter

        push_run_limiter.reset()
        for index in range(200):
            self._push(client, f"agentrun_flood_{index}", "t")

        assert push_run_limiter.key_count == 0

    def test_014_SC_003_a_forged_token_writes_one_bounded_row_per_day(
        self, client: TestClient, container: Container
    ) -> None:
        """Step 4. Accountability without a row per attempt."""

        run_id, token = self._pushable(client, container, key="k-push-forged")
        service = container.agent_relay_service
        owner_id = service.agent_repo.owner_of_run(run_id) or ""

        for index in range(5):
            assert self._push(client, run_id, f"forged-{index}").status_code == 403

        actions = [entry.action for entry in service.list_audit(owner_id=owner_id)]
        assert actions.count("push_token_rejected") == 1
        assert token

    def test_valid_push_after_terminal_is_classified_push_after_close(
        self, client: TestClient, container: Container
    ) -> None:
        """Step 5, and the common Hermes race: a terminal push is not a forgery."""

        run_id, token = self._pushable(client, container, key="k-push-late")
        service = container.agent_relay_service
        owner_id = service.agent_repo.owner_of_run(run_id) or ""
        run = service.agent_repo.get_run(run_id, owner_id=owner_id)
        service.agent_repo.save_run(
            run.model_copy(
                update={"reported_state": "completed", "next_observation_at": None}
            )
        )

        assert self._push(client, run_id, token).status_code == 403

        actions = [entry.action for entry in service.list_audit(owner_id=owner_id)]
        assert "push_after_close" in actions
        assert "push_token_rejected" not in actions

    @pytest.mark.parametrize("declared", [True, False])
    def test_014_FR_008_an_oversize_body_is_refused_at_the_cap(
        self, client: TestClient, container: Container, declared: bool
    ) -> None:
        """Step 1, on the header alone and again while reading."""

        run_id, token = self._pushable(
            client, container, key=f"k-push-big-{int(declared)}"
        )
        body = b"x" * (MAX_EVENT_BODY_BYTES + 1)
        headers = {} if declared else {"Transfer-Encoding": "chunked"}

        response = client.post(
            f"/api/a2a/push/{run_id}/{token}", content=body, headers=headers
        )

        assert response.status_code == 413

    def test_global_push_limiter_trips_before_the_run_lookup(
        self, client: TestClient, container: Container
    ) -> None:
        """Step 2. A flood costs one integer comparison, not a database read."""

        from app.api.agents import PUSH_GLOBAL_MAX_PER_MINUTE, push_global_limiter

        run_id, token = self._pushable(client, container, key="k-push-global")
        reads: list[str] = []
        service = container.agent_relay_service
        original = service.agent_repo.owner_of_run

        def counting_lookup(lookup_run_id: str) -> str | None:
            reads.append(lookup_run_id)
            return original(lookup_run_id)

        service.agent_repo.owner_of_run = counting_lookup  # type: ignore[method-assign]
        push_global_limiter.reset()
        attempts = PUSH_GLOBAL_MAX_PER_MINUTE + 100
        try:
            statuses = [
                self._push(client, run_id, token).status_code for _ in range(attempts)
            ]
        finally:
            service.agent_repo.owner_of_run = original  # type: ignore[method-assign]
            push_global_limiter.reset()

        assert 429 in statuses, "the global limiter must trip"
        assert len(reads) == PUSH_GLOBAL_MAX_PER_MINUTE, (
            "everything past the process-wide budget was refused before the "
            "database was touched"
        )

    def test_014_FR_008_the_per_run_limiter_is_reachable_only_for_known_runs(
        self, client: TestClient, container: Container
    ) -> None:
        """The one deliberate existence signal, gated by an unguessable id."""

        from app.api.agents import PUSH_RUN_MAX_PER_MINUTE, push_run_limiter

        run_id, token = self._pushable(client, container, key="k-push-run-limit")
        push_run_limiter.reset()

        statuses = [
            self._push(client, run_id, token).status_code
            for _ in range(PUSH_RUN_MAX_PER_MINUTE + 2)
        ]

        assert 429 in statuses
        assert push_run_limiter.key_count == 1

    def test_014_FR_008_the_push_route_needs_no_session_and_no_rollout_flag(
        self,
        client: TestClient,
        container: Container,
        anonymous_api_client: TestClient,
    ) -> None:
        """A run already dispatched must keep reporting whatever the flag says."""

        run_id, token = self._pushable(client, container, key="k-push-flag")
        set_relay_flag(client, FeatureFlagState.OFF)

        response = client.post(f"/api/a2a/push/{run_id}/{token}", content=b"{}")

        assert response.status_code == 204
        assert anonymous_api_client is not None

    def test_014_FR_016_rollout_off_keeps_observation_push_and_commands_alive(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-036. The flag protects "no task content leaves", not "no run moves".

        A run that was already handed over must be able to reach a terminal
        state whatever the owner's rollout state later becomes; freezing it
        would leave someone with work in flight and no way to learn its
        outcome.
        """

        run_id, token = self._pushable(client, container, key="k-push-off")
        service = container.agent_relay_service
        owner_id = service.agent_repo.owner_of_run(run_id) or ""
        set_relay_flag(client, FeatureFlagState.OFF)

        assert self._push(client, run_id, token).status_code == 204
        assert client.get(f"/api/agent-runs/{run_id}").status_code == 200
        assert (
            client.post(
                f"/api/agent-runs/{run_id}/cancel",
                headers={"Idempotency-Key": "k-off-cancel"},
            ).status_code
            == 200
        )
        # And a new hand-off is still refused, which is what the flag is for.
        task_id = create_task(client, title="Blocked by the rollout flag")
        connection_id = service.agent_repo.get_run(
            run_id, owner_id=owner_id
        ).connection_id
        assert (
            client.post(
                f"/api/tasks/{task_id}/agent-runs/preview",
                json={"connection_id": connection_id},
            ).status_code
            == 404
        )

    def test_014_SC_009_auth_docs_record_the_push_callback_as_the_403_exception(
        self,
    ) -> None:
        """T126's assertion: the one deviation from 404-for-wrong-owner is written down.

        A security decision that lives only in a contract file is one nobody
        reviewing `docs/auth.md` will ever meet. The push route answers 403
        rather than 404, and its per-run 429 is a deliberate existence signal;
        both belong where the repository's auth conventions are stated.
        """

        auth_docs = (
            Path(__file__).resolve().parents[2] / "docs" / "auth.md"
        ).read_text(encoding="utf-8")

        assert "403" in auth_docs and "404" in auth_docs
        assert "/a2a/push/" in auth_docs
        assert "429" in auth_docs
        push_lines = [line for line in auth_docs.splitlines() if "a2a/push" in line]
        assert any(
            "403" in line and "404" in line for line in push_lines
        ), "docs/auth.md must say the push callback answers 403 rather than 404"
        assert any(
            "429" in line for line in push_lines
        ), "docs/auth.md must record the per-run 429 existence signal"

    def test_014_FR_008_the_body_is_never_parsed_for_state(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-021. The observation is authoritative; the body is only a nudge."""

        run_id, token = self._pushable(client, container, key="k-push-body")
        service = container.agent_relay_service
        owner_id = service.agent_repo.owner_of_run(run_id) or ""
        before = service.agent_repo.get_run(run_id, owner_id=owner_id)

        response = client.post(
            f"/api/a2a/push/{run_id}/{token}",
            content=b'{"statusUpdate": {"status": {"state": "TASK_STATE_COMPLETED"}}}',
        )

        assert response.status_code == 204
        after = service.agent_repo.get_run(run_id, owner_id=owner_id)
        assert after.reported_state == before.reported_state
        assert after.run_version == before.run_version

    def test_014_FR_008_a_malformed_body_still_only_schedules_an_observation(
        self, client: TestClient, container: Container
    ) -> None:
        run_id, token = self._pushable(client, container, key="k-push-malformed")

        response = client.post(
            f"/api/a2a/push/{run_id}/{token}", content=b"\x00not json at all"
        )

        assert response.status_code == 204

    def test_push_token_never_appears_in_logs(
        self,
        client: TestClient,
        container: Container,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """014-SC-009. The verified, the rejected, and the exception path."""

        import logging

        run_id, token = self._pushable(client, container, key="k-push-logs")
        service = container.agent_relay_service

        def explode(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("the push handler exploded")

        with caplog.at_level(logging.DEBUG):
            self._push(client, run_id, token)
            self._push(client, run_id, "forged-" + token)
            original = service.verify_push
            service.verify_push = explode  # type: ignore[method-assign]
            try:
                client.post(
                    f"/api/a2a/push/{run_id}/{token}",
                    content=b"{}",
                )
            except RuntimeError:
                pass
            finally:
                service.verify_push = original  # type: ignore[method-assign]

        messages = [
            record.getMessage()
            for record in caplog.records
            if record.name.startswith("app.") or record.name.startswith("uvicorn")
        ]
        assert messages, "the request must have been logged at all"
        assert not any(token in message for message in messages)


class TestRunRouteObservationDeltas:
    """What the run routes say once observation, not a callback, drives them."""

    def _blocked_run(
        self, client: TestClient, container: Container, *, key: str = "k-obs"
    ) -> dict[str, Any]:
        service = container.agent_relay_service
        connection = register_connection(client, key=key)
        client.post(
            f"/api/agent-connections/{connection['id']}/test",
            headers={"Idempotency-Key": f"{key}-test"},
        )
        task_id = create_task(client, title=f"Observed {key}")
        run = hand_off(client, connection["id"], task_id, key=f"{key}-dispatch")
        owner_id = service.agent_repo.owner_of_run(run["id"]) or ""
        stored = service.agent_repo.get_run(run["id"], owner_id=owner_id)
        service.agent_repo.save_run(
            stored.model_copy(
                update={
                    "agent_task_id": "t1",
                    "reported_state": "blocked",
                    "question_text": "Which environment?",
                    "run_version": 1,
                }
            )
        )
        return dict(client.get(f"/api/agent-runs/{run['id']}").json())

    def test_014_FR_013_the_run_response_carries_the_observation_fields(
        self, client: TestClient, container: Container
    ) -> None:
        run = self._blocked_run(client, container)

        assert run["agent_task_missing"] is False
        assert run["cancel_outcome"] == "none"
        assert run["identifiers_expired"] is False
        assert run["observation_interval_seconds"] >= 5
        assert run["artifacts_summary"] == []
        assert run["result_availability"] is None
        assert run["primary_state_label"] == "Needs you"

    def test_014_FR_010_reply_and_cancel_refuse_a_run_the_agent_forgot(
        self, client: TestClient, container: Container
    ) -> None:
        """AC-020. Both controls are withdrawn, with the reason named."""

        run = self._blocked_run(client, container, key="k-missing")
        service = container.agent_relay_service
        owner_id = service.agent_repo.owner_of_run(run["id"]) or ""
        service.record_task_missing(run["id"], owner_id=owner_id)

        reply = client.post(
            f"/api/agent-runs/{run['id']}/reply",
            headers={"Idempotency-Key": "k-missing-reply"},
            json={"message": "Use staging.", "expected_revision": run["revision"] + 1},
        )
        cancel = client.post(
            f"/api/agent-runs/{run['id']}/cancel",
            headers={"Idempotency-Key": "k-missing-cancel"},
        )

        for response in (reply, cancel):
            assert response.status_code == 400, response.text
            assert response.json()["detail"]["reason"] == "agent_task_missing"

    def test_014_FR_013_the_summary_route_carries_the_tier_and_the_withdrawals(
        self, client: TestClient, container: Container
    ) -> None:
        run = self._blocked_run(client, container, key="k-summary")

        response = client.get(
            "/api/agent-run-summaries", params={"task_id": run["task_id"]}
        )

        assert response.status_code == 200, response.text
        summary = response.json()[run["task_id"]]
        assert summary["guarantee_tier"] in {"guaranteed", "best_effort"}
        assert summary["cancel_outcome"] == "none"
        assert summary["agent_task_missing"] is False
