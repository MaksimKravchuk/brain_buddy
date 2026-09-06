"""Conformance against the unmodified a2a-sdk `helloworld` sample.

014-FR-017, 014-SC-001, 014-SC-002.

The sample is vendored byte-for-byte from the official `a2a-samples` repository
(`backend/vendor/a2a_helloworld/`, provenance recorded beside it) and runs here
as its own process on `127.0.0.1:9999`, exactly as its `__main__` binds it. That
is the whole point: nothing in this file may adapt the agent to BrainBuddy, so
what passes here is the wire contract and not a shared assumption.

AC-001, AC-009, AC-016, AC-026.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.container import Container, build_container
from app.core import get_config
from app.modules.agents.a2a.client import A2A_NOT_CANCELABLE
from app.schemas.agents import (
    AgentConnectionCreateRequest,
    AgentHandoffConfirmRequest,
    AgentHandoffPreviewRequest,
)

from .a2a_reference import (
    VENDOR_ROOT,
    card_is_served,
    jsonrpc,
    require_free_port,
    start_runtime,
)

OWNER = "user_reference"
PASSWORD = "correct-horse-battery-staple"
SAMPLE_PORT = 9999
SAMPLE_URL = f"http://127.0.0.1:{SAMPLE_PORT}"
CARD_URL = f"{SAMPLE_URL}/.well-known/agent-card.json"


@pytest.fixture(scope="module")
def helloworld(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> str:
    """The vendored sample, running as its own process, or a failed test."""

    require_free_port(SAMPLE_PORT)
    home = tmp_path_factory.mktemp("helloworld-home")
    start_runtime(
        request,
        argv=[sys.executable, "__main__.py"],
        cwd=VENDOR_ROOT / "a2a_helloworld",
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(VENDOR_ROOT / "a2a_helloworld"),
        },
        ready=card_is_served(CARD_URL),
        name="the a2a-sdk helloworld sample",
    )
    return SAMPLE_URL


@pytest.fixture
def container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Container]:
    """A real container aimed at a private destination, as the fixture is."""

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "relay-data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_AGENT_ALLOW_PRIVATE_DESTINATIONS", "1")
    monkeypatch.setenv(
        "BRAIN_BUDDY_FEATURE_FLAGS", "external_agent_relay=on,voice_brain_dump=off"
    )
    get_config.cache_clear()
    built = build_container(get_config())
    assert (
        built.agent_relay_service.allow_private_destinations
    ), "the suite would silently prove nothing if the destination were refused"
    yield built
    get_config.cache_clear()


@pytest.fixture
def connection_id(container: Container, helloworld: str) -> str:
    """One connection registered against the sample's real address."""

    created = container.agent_relay_service.create_connection(
        AgentConnectionCreateRequest(
            name="Hello World Agent",
            agent_address=helloworld,
            auth_scheme="bearer",
            credential="unused-by-the-sample",
            current_password=PASSWORD,
        ),
        owner_id=OWNER,
        idempotency_key="idem-reference-create",
        reauthenticated=True,
    )
    return created.id


def _dispatch(
    container: Container, connection_id: str, *, task_id: str, key: str
) -> Any:
    service = container.agent_relay_service
    preview = service.preview_handoff(
        task_id,
        AgentHandoffPreviewRequest(connection_id=connection_id),
        owner_id=OWNER,
    )
    return service.dispatch_run(
        task_id,
        AgentHandoffConfirmRequest(
            connection_id=connection_id,
            manifest_token=preview.token,
            # The sample is best-effort: it advertises no single-start
            # extension, so the review shows the duplicate-risk box and the
            # confirmation has to carry the acknowledgement (AC-026).
            acknowledge_duplicate_risk=True,
        ),
        owner_id=OWNER,
        idempotency_key=key,
    )


@pytest.fixture(autouse=True)
def _one_task(container: Container, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Task the hand-off reads. Read-only, as the port is by construction."""

    from app.modules.agents.service import TaskSnapshot

    def snapshot(task_id: str, *, owner_id: str) -> TaskSnapshot:
        return TaskSnapshot(
            id=task_id,
            title="Draft the relay migration plan",
            details="Cover rollback and the data backfill.",
        )

    monkeypatch.setattr(container.agent_relay_service, "task_snapshot", snapshot)


class TestHelloWorldConformance:
    """One connection, one hand-off, one task at the agent."""

    def test_014_FR_017_the_sample_card_is_discovered_and_the_connection_tests_ready(
        self, container: Container, connection_id: str
    ) -> None:
        """AC-001. Readiness comes from the agent's own card and an A2A call.

        The sample declares no security scheme and no push notifications, so
        this also pins the honest reading of a best-effort agent: BrainBuddy
        records what the card said rather than what it wishes it said.
        """

        tested = container.agent_relay_service.test_connection(
            connection_id, owner_id=OWNER
        )

        assert tested.status == "ready"
        assert tested.card is not None
        assert tested.card.name == "Hello World Agent"
        assert tested.card.version == "0.0.1"
        assert tested.card.protocol_version == "1.0"
        assert tested.card.streaming is True
        assert [skill.name for skill in tested.card.skills] == ["Echo Bot"]
        assert tested.card.auth_schemes_offered == [], (
            "the sample declares no security scheme, and BrainBuddy must record "
            "that rather than invent one"
        )
        assert tested.capabilities.push_notifications is False
        assert tested.guarantee_tier == "best_effort"

    def test_014_SC_001_a_hand_off_completes_inside_the_exchange(
        self, container: Container, connection_id: str
    ) -> None:
        """AC-009, AC-016. The sample answers synchronously, so **Sent** and the
        agent's own completion land in the same request — and the result text is
        the sample's, rendered inertly rather than interpreted."""

        service = container.agent_relay_service
        service.test_connection(connection_id, owner_id=OWNER)

        run = _dispatch(container, connection_id, task_id="task_1", key="idem-r1")

        assert run.dispatch_state == "sent"
        assert run.reported_state == "completed"
        assert run.primary_state_label == "Agent reported complete"
        assert run.agent_task_id
        assert run.result_text is not None
        assert "Hello, World!" in run.result_text
        assert run.result_link_interactive is False

    def test_014_SC_002_three_replays_create_one_task_at_the_unmodified_sample(
        self, container: Container, connection_id: str
    ) -> None:
        """AC-026. Replay safety proved at the agent, not in BrainBuddy's rows.

        The same confirmation is sent three times with one Idempotency-Key. The
        run projection is asked what BrainBuddy believes, and then the sample is
        asked directly, through its own JSON-RPC endpoint, how many tasks that
        conversation actually has. Only the second answer can catch a duplicate.
        """

        service = container.agent_relay_service
        service.test_connection(connection_id, owner_id=OWNER)
        preview = service.preview_handoff(
            "task_2",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )
        confirmation = AgentHandoffConfirmRequest(
            connection_id=connection_id,
            manifest_token=preview.token,
            acknowledge_duplicate_risk=True,
        )

        runs = [
            service.dispatch_run(
                "task_2",
                confirmation,
                owner_id=OWNER,
                idempotency_key="idem-replay-once",
            )
            for _ in range(3)
        ]

        assert {run.id for run in runs} == {preview.run_id}
        assert len({run.agent_task_id for run in runs}) == 1

        listed = jsonrpc(
            SAMPLE_URL, "ListTasks", {"contextId": preview.run_id, "pageSize": 10}
        )
        tasks = listed["result"]["tasks"]
        assert len(tasks) == 1, f"the sample holds {len(tasks)} tasks, not one"
        assert tasks[0]["id"] == runs[0].agent_task_id

    def test_014_SC_001_cancel_is_withdrawn_on_a_run_the_agent_already_finished(
        self, container: Container, connection_id: str
    ) -> None:
        """AC-016. Two different refusals, and both have to be honest.

        BrainBuddy refuses to *offer* cancel on a run the agent reported
        complete, and the sample refuses to *perform* one. The recorded
        behaviour is the sample's own answer, not the one this feature hoped
        for: `HelloWorldAgentExecutor.cancel` raises, and the a2a-sdk turns that
        into `-32002 TASK_NOT_CANCELABLE` rather than the `-32004
        UnsupportedOperation` the plan anticipated. Asserted as observed, and
        `contracts/a2a-wire.md` maps it to a withdrawn control either way.
        """

        service = container.agent_relay_service
        service.test_connection(connection_id, owner_id=OWNER)
        run = _dispatch(container, connection_id, task_id="task_3", key="idem-r3")
        assert run.reported_state == "completed"

        projection = service.get_run(run.id, owner_id=OWNER)
        assert (
            projection.capabilities.cancel is False
        ), "a settled run has nothing left to cancel"

        refusal = jsonrpc(SAMPLE_URL, "CancelTask", {"id": run.agent_task_id})

        assert refusal["error"]["code"] == -32002
        assert refusal["error"]["data"][0]["reason"] == "TASK_NOT_CANCELABLE"
        connection = service.get_connection(connection_id, owner_id=OWNER)
        target = service._a2a_target(
            connection, interface_url=projection.manifest.destination_interface
        )
        direct = service.a2a_client.cancel_task(target, task_id=run.agent_task_id)
        assert direct.ok is False
        assert direct.error_code == A2A_NOT_CANCELABLE

    def test_014_FR_017_no_content_reaches_the_agent_before_the_owner_confirms(
        self, container: Container, connection_id: str
    ) -> None:
        """AC-001. The review is a disclosure, so it must send nothing."""

        service = container.agent_relay_service
        service.test_connection(connection_id, owner_id=OWNER)
        before = jsonrpc(SAMPLE_URL, "ListTasks", {"pageSize": 50})["result"]

        preview = service.preview_handoff(
            "task_4",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )

        after = jsonrpc(SAMPLE_URL, "ListTasks", {"pageSize": 50})["result"]
        assert after.get("tasks", []) == before.get("tasks", [])
        assert preview.title == "Draft the relay migration plan"
        assert preview.acknowledgement_required is True
        assert (
            preview.push_callback.registered is False
        ), "the sample's card declares no push support, so none was registered"
        # Nothing was dispatched, so the reservation must expire rather than
        # linger as a run the user never confirmed.
        service.agent_repo.prune_undispatched_runs(
            before=service._now() + timedelta(hours=2)
        )
