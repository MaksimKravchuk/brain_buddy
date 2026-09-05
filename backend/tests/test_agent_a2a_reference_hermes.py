"""Conformance against the unmodified Hermes A2A plugin.

014-FR-017, 014-SC-001, 014-SC-002, 014-SC-006.

The plugin under `backend/vendor/hermes_a2a/plugins/platforms/a2a/` is upstream
Hermes, byte-for-byte. Only the *brain* behind it is replaced, by a scripted
one-line reply function, so no model and no provider money is involved; the HTTP
server, JSON-RPC dispatch, agent card, task store, blocking-send semantics,
push notifications and cancellation are all Hermes' own code.

That is what makes this suite worth its cost: it is the only place BrainBuddy's
wire meets a **legacy-shaped** card (`{"type": "http", "scheme": "bearer"}` with
a `security` array rather than 1.0's `securityRequirements`) and a real
input-required round trip.

AC-010, AC-014, AC-015, AC-018, AC-020, AC-021, AC-028.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.container import Container
from app.core import get_config
from app.main import create_app
from app.modules.agents.service import TaskSnapshot
from app.schemas.agents import (
    AgentConnectionCreateRequest,
    AgentHandoffConfirmRequest,
    AgentHandoffPreviewRequest,
    AgentReplyRequest,
)

from .a2a_reference import (
    VENDOR_ROOT,
    free_port,
    jsonrpc,
    start_announcing_runtime,
    wait_until,
)

OWNER = "user_hermes"
PASSWORD = "correct-horse-battery-staple"
BEARER = "hermes-stub-bearer-token"  # noqa: S105 - synthetic fixture value
PORT_PREFIX = "A2A_STUB_PORT="
STUB_AGENT_NAME = "hermes-conformance-stub"
STUB_DIR = VENDOR_ROOT / "hermes_a2a"

#: The reply delay used by the SC-006 cases. Long enough that the exchange
#: closes as **Sent** rather than racing the answer, short enough that a test
#: waiting on the observation is not a sleep in disguise.
DELAY_SECONDS = 3


class Stub:
    """One running Hermes adapter, and the knobs a test needs on it."""

    def __init__(self, process: subprocess.Popen[bytes], port: int) -> None:
        self.process = process
        self.port = port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def card_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/.well-known/agent-card.json"

    def card(self) -> dict[str, Any]:
        response = httpx.get(self.card_url, timeout=5.0)
        response.raise_for_status()
        return dict(response.json())

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                self.process.kill()
                self.process.wait(timeout=10)


def start_stub(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    *,
    bearer: str | None = BEARER,
    delay_seconds: int = 0,
    port: int = 0,
) -> Stub:
    """Start `run_stub.py`, and fail rather than skip when it will not come up."""

    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONUNBUFFERED": "1",
        "A2A_HOST": "127.0.0.1",
        "A2A_PORT": str(port),
        "A2A_STUB_HOME": str(tmp_path / f"hermes-home-{port}"),
        # The adapter's default card name is `hermes-<hostname>`, which made the
        # card assertions depend on the machine running the suite. Naming it
        # through the plugin's own documented knob keeps the vendored code
        # untouched and the expectation the same on every runner.
        "A2A_AGENT_NAME": STUB_AGENT_NAME,
        "STUB_REPLY_DELAY_SECONDS": str(delay_seconds),
    }
    if bearer is not None:
        env["A2A_BEARER_TOKEN"] = bearer
    # `A2A_PUBLIC_URL` is deliberately unset. The adapter then builds its card
    # from the request's `Host` header, which is the only value that is right
    # when the OS chose the port: an env var written before the bind would
    # advertise an interface nothing listens on.
    process, bound = start_announcing_runtime(
        request,
        argv=[sys.executable, "run_stub.py"],
        cwd=STUB_DIR,
        env=env,
        prefix=PORT_PREFIX,
        name="the vendored Hermes A2A adapter",
    )
    stub = Stub(process, bound)
    wait_until(
        lambda: httpx.get(stub.card_url, timeout=2.0).status_code == 200,
        name="the vendored Hermes A2A adapter's card",
    )
    return stub


@pytest.fixture
def stub(request: pytest.FixtureRequest, tmp_path: Path) -> Stub:
    return start_stub(request, tmp_path)


@pytest.fixture
def relay(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Container]:
    """BrainBuddy itself, served over real HTTP so a push can reach it.

    The push callback is an address BrainBuddy hands to a third party, so the
    only honest way to test it is to make that address real: the app runs on a
    socket the stub can post to, and nothing about the route is stubbed.
    """

    port = free_port()
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "relay-data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_AGENT_ALLOW_PRIVATE_DESTINATIONS", "1")
    monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("BRAIN_BUDDY_AGENT_OBSERVATION_INTERVAL_SECONDS", "5")
    monkeypatch.setenv("BRAIN_BUDDY_AGENT_DISPATCH_WAIT_SECONDS", "1")
    # The observer is the only thing that moves a dispatched run forward, and
    # it is gated off in the test environment so the many short-lived apps the
    # rest of the suite builds do not each run a scheduler. This suite is the
    # documented exception: it serves one app on one socket and shuts it down.
    monkeypatch.setenv("BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST", "1")
    monkeypatch.setenv(
        "BRAIN_BUDDY_FEATURE_FLAGS", "external_agent_relay=on,voice_brain_dump=off"
    )
    get_config.cache_clear()

    import uvicorn

    app = create_app()
    container: Container = app.state.container
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True, name="brainbuddy-relay")
    thread.start()
    wait_until(
        lambda: _reachable("127.0.0.1", port),
        name=f"BrainBuddy on 127.0.0.1:{port}",
    )

    def snapshot(task_id: str, *, owner_id: str) -> TaskSnapshot:
        return TaskSnapshot(
            id=task_id, title="Research relay security", details="Cite evidence."
        )

    monkeypatch.setattr(container.agent_relay_service, "task_snapshot", snapshot)
    yield container

    server.should_exit = True
    thread.join(timeout=15)
    get_config.cache_clear()


def _reachable(host: str, port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.settimeout(1.0)
        return probe.connect_ex((host, port)) == 0


def connect(container: Container, stub: Stub, *, key: str = "idem-hermes") -> str:
    created = container.agent_relay_service.create_connection(
        AgentConnectionCreateRequest(
            name="Hermes",
            agent_address=stub.url,
            auth_scheme="bearer",
            credential=BEARER,
            current_password=PASSWORD,
        ),
        owner_id=OWNER,
        idempotency_key=f"{key}-create",
        reauthenticated=True,
    )
    return created.id


def ready_connection(
    container: Container, stub: Stub, *, key: str = "idem-hermes"
) -> str:
    connection_id = connect(container, stub, key=key)
    tested = container.agent_relay_service.test_connection(
        connection_id, owner_id=OWNER
    )
    assert tested.status == "ready", tested.last_test_error_code
    return connection_id


def dispatch(
    container: Container,
    connection_id: str,
    *,
    task_id: str,
    key: str,
    text: str | None = None,
) -> Any:
    service = container.agent_relay_service
    if text is not None:
        service.task_snapshot = lambda _id, *, owner_id: TaskSnapshot(  # type: ignore[method-assign]
            id=task_id, title=text, details=None
        )
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
            acknowledge_duplicate_risk=True,
        ),
        owner_id=OWNER,
        idempotency_key=key,
    )


def until(
    check: Callable[[], bool],
    *,
    what: str,
    timeout: float = 30.0,
    context: Callable[[], object] | None = None,
) -> None:
    """Wait for a real agent to do something, and say what it did instead.

    A bare "timed out" on a suite that drives another process is the least
    debuggable failure available, so the state under test is printed with it.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    detail = f"\nlast seen: {context()!r}" if context is not None else ""
    pytest.fail(f"timed out waiting for {what}{detail}")


class TestHermesCardAndCredential:
    """Discovery against the legacy card shape, and the credential it names."""

    def test_014_FR_017_the_legacy_card_shape_is_parsed_as_the_1_0_one_is(
        self, relay: Container, stub: Stub
    ) -> None:
        """AC-010. Hermes predates the 1.0 card, and it is still an A2A agent.

        Its card declares `securitySchemes.bearer = {"type": "http", "scheme":
        "bearer"}` and a `security` array, not 1.0's `securityRequirements`.
        Refusing that shape would make FR-017 unsatisfiable against a real
        deployment, so the shape is read, not judged.
        """

        raw = stub.card()
        assert raw["securitySchemes"]["bearer"] == {"type": "http", "scheme": "bearer"}
        assert raw["security"] == [{"bearer": []}]

        connection_id = ready_connection(relay, stub)

        tested = relay.agent_relay_service.get_connection(connection_id, owner_id=OWNER)
        assert tested.status == "ready"
        assert tested.card is not None
        assert tested.card.name == STUB_AGENT_NAME
        assert tested.card.protocol_version == "1.0"
        assert tested.card.streaming is True
        assert tested.card.push_notifications is True
        assert [offer.kind for offer in tested.card.auth_schemes_offered] == ["bearer"]

    def test_014_SC_003_a_wrong_bearer_is_refused_and_nothing_is_echoed_back(
        self, relay: Container, stub: Stub
    ) -> None:
        """AC-010. The agent's refusal must not become a disclosure.

        What BrainBuddy shows is a category. The credential it sent, the header
        it sent it in and whatever the agent said about it stay out of the
        connection, its error detail and the owner's audit trail.
        """

        service = relay.agent_relay_service
        wrong = "not-the-stub-token"  # noqa: S105 - synthetic fixture value
        created = service.create_connection(
            AgentConnectionCreateRequest(
                name="Hermes",
                agent_address=stub.url,
                auth_scheme="bearer",
                credential=wrong,
                current_password=PASSWORD,
            ),
            owner_id=OWNER,
            idempotency_key="idem-wrong-bearer",
            reauthenticated=True,
        )

        tested = service.test_connection(created.id, owner_id=OWNER)

        assert tested.status == "invalid_credentials"
        assert tested.last_test_error_code == "a2a_credentials_rejected"
        rendered = tested.model_dump_json()
        assert wrong not in rendered
        assert BEARER not in rendered
        assert "authorization" not in rendered.lower()
        audit = "".join(
            entry.model_dump_json() for entry in service.list_audit(owner_id=OWNER)
        )
        assert wrong not in audit

    def test_014_FR_002_a_stub_that_lost_its_token_reads_as_agent_changed(
        self, request: pytest.FixtureRequest, tmp_path: Path, relay: Container
    ) -> None:
        """AC-028. The card is the contract, so a card that moved invalidates it.

        Restarting the adapter without `A2A_BEARER_TOKEN` changes what it says
        about itself. BrainBuddy pinned the fingerprint when the owner tested
        it, so the review refuses rather than sending content to a destination
        whose terms the owner never saw.
        """

        first = start_stub(request, tmp_path, port=free_port())
        connection_id = ready_connection(relay, first, key="idem-drift")
        first.stop()

        second = start_stub(request, tmp_path, bearer=None, port=first.port)
        assert (
            "securitySchemes" not in second.card()
        ), "the drift under test is the card losing its scheme"

        with pytest.raises(Exception) as refused:  # noqa: PT011 - checked below
            relay.agent_relay_service.preview_handoff(
                "task_drift",
                AgentHandoffPreviewRequest(connection_id=connection_id),
                owner_id=OWNER,
            )

        assert getattr(refused.value, "detail", {}) == {"reason": "agent_card_changed"}
        after = relay.agent_relay_service.get_connection(connection_id, owner_id=OWNER)
        assert after.agent_changed is True
        assert after.ready_for_handoff is False


class TestHermesHandOff:
    """One hand-off, and everything the agent is allowed to say about it."""

    def test_014_SC_002_three_replays_create_one_task_at_the_unmodified_hermes_stub(
        self, relay: Container, stub: Stub
    ) -> None:
        """AC-018. The second of SC-002's three reference replays.

        The same manifest token and the same `Idempotency-Key`, three times, and
        then the stub is asked directly how many tasks the conversation holds.
        Hermes has no `messageId` dedup of its own (research F5), so a duplicate
        here would be a duplicate at the agent — which is exactly the claim
        BrainBuddy makes and must be able to prove.
        """

        connection_id = ready_connection(relay, stub, key="idem-replay")
        service = relay.agent_relay_service
        preview = service.preview_handoff(
            "task_replay",
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
                "task_replay",
                confirmation,
                owner_id=OWNER,
                idempotency_key="idem-replay-once",
            )
            for _ in range(3)
        ]

        assert {run.id for run in runs} == {preview.run_id}
        listed = jsonrpc(
            stub.url,
            "ListTasks",
            {"contextId": preview.run_id, "pageSize": 20},
            bearer=BEARER,
        )
        tasks = listed["result"].get("tasks", [])
        assert len(tasks) == 1, f"the stub holds {len(tasks)} tasks, not one"
        assert {run.agent_task_id for run in runs} == {tasks[0]["id"]}

    def test_014_SC_006_a_delayed_agent_is_sent_then_observed_complete(
        self, request: pytest.FixtureRequest, tmp_path: Path, relay: Container
    ) -> None:
        """AC-014, AC-021. Slow is not failed, and BrainBuddy says so.

        The stub answers after the exchange's dispatch wait, so the hand-off
        closes as **Sent** with nothing invented about the outcome. The truth
        arrives on the schedule: a token-secured Hermes refuses to push to a
        private callback (its own SSRF guard, recorded in review.md), so the
        observation that settles the run is the scheduled one, and that is
        exactly what the trigger assertion below checks. Push, where an agent
        can deliver it, is an acceleration; the schedule is the guarantee.
        """

        delayed = start_stub(request, tmp_path, delay_seconds=DELAY_SECONDS)
        connection_id = ready_connection(relay, delayed, key="idem-delayed")
        service = relay.agent_relay_service

        run = dispatch(
            relay, connection_id, task_id="task_delayed", key="idem-delayed-dispatch"
        )

        assert run.dispatch_state == "sent"
        assert run.reported_state in (None, "accepted", "running")
        assert run.primary_state_label in ("Sent", "Running")
        assert run.dispatch_error_code is None, "a slow agent is not a failed one"

        stored = service.agent_repo.get_run(run.id, owner_id=OWNER)
        assert (
            stored.push_token_fingerprint is not None
        ), "the stub's card declares push, so a callback was registered"

        until(
            lambda: service.get_run(run.id, owner_id=OWNER).reported_state
            == "completed",
            what="the delayed agent's completion to reach BrainBuddy",
            context=lambda: (
                service.agent_repo.get_run(run.id, owner_id=OWNER).reported_state,
                jsonrpc(
                    delayed.url,
                    "GetTask",
                    {
                        "id": service.agent_repo.get_run(
                            run.id, owner_id=OWNER
                        ).agent_task_id,
                        "historyLength": 0,
                    },
                    bearer=BEARER,
                )["result"]["status"]["state"],
            ),
        )

        settled = service.get_run(run.id, owner_id=OWNER)
        assert settled.primary_state_label == "Agent reported complete"
        assert settled.result_text
        assert {event.trigger for event in settled.events} == {"schedule"}
        assert settled.last_observed_at is not None

    def test_014_SC_006_a_question_is_answered_and_the_succession_is_recorded(
        self, relay: Container, stub: Stub
    ) -> None:
        """AC-015, AC-020. A reply may start a *new* task, and that is not a
        new run: the succession row carries both task ids under the run's one
        correlation ID, so the history of the work stays one thread."""

        connection_id = ready_connection(relay, stub, key="idem-ask")
        service = relay.agent_relay_service

        run = dispatch(
            relay,
            connection_id,
            task_id="task_ask",
            key="idem-ask-dispatch",
            text="Please ask me which environment",
        )

        until(
            lambda: service.get_run(run.id, owner_id=OWNER).needs_user is True,
            what="the stub's clarifying question",
        )
        asked = service.get_run(run.id, owner_id=OWNER)
        assert asked.primary_state_label == "Needs you"
        assert asked.question_text
        first_task_id = asked.agent_task_id

        replied = service.reply_to_run(
            run.id,
            AgentReplyRequest(message="Use staging.", expected_revision=asked.revision),
            owner_id=OWNER,
            idempotency_key="idem-ask-reply",
        )

        assert replied.id == run.id
        assert replied.correlation_id == run.id
        if replied.agent_task_id != first_task_id:
            succession = [
                event
                for event in replied.events
                if event.previous_agent_task_id or event.new_agent_task_id
            ]
            assert succession, "a task the reply replaced must be recorded"
            assert succession[-1].previous_agent_task_id == first_task_id
            assert succession[-1].new_agent_task_id == replied.agent_task_id

    def test_014_SC_006_a_cancel_while_the_agent_is_working_settles_as_cancelled(
        self, request: pytest.FixtureRequest, tmp_path: Path, relay: Container
    ) -> None:
        """AC-021. Requested is not done, and Hermes is what closes the gap."""

        delayed = start_stub(request, tmp_path, delay_seconds=DELAY_SECONDS * 3)
        connection_id = ready_connection(relay, delayed, key="idem-cancel")
        service = relay.agent_relay_service
        run = dispatch(
            relay, connection_id, task_id="task_cancel", key="idem-cancel-dispatch"
        )
        assert run.dispatch_state == "sent"

        cancelled = service.cancel_run(
            run.id, owner_id=OWNER, idempotency_key="idem-cancel-command"
        )

        assert cancelled.cancel_outcome in ("requested", "accepted")
        until(
            lambda: service.get_run(run.id, owner_id=OWNER).reported_state
            == "cancelled",
            what="the stub to confirm the cancellation",
        )
        settled = service.get_run(run.id, owner_id=OWNER)
        assert settled.primary_state_label == "Cancelled"

    def test_014_FR_008_a_stub_that_disappears_is_reported_as_lost_not_finished(
        self, request: pytest.FixtureRequest, tmp_path: Path, relay: Container
    ) -> None:
        """AC-021. BrainBuddy cannot see the work, and must not pretend to.

        The adapter is stopped mid-run and restarted with an empty task store,
        so the run's task id no longer resolves. The honest report is that
        BrainBuddy has lost track of it — with the last contact it *did* have
        preserved, because that timestamp is a fact and the outcome is not.
        """

        first = start_stub(
            request, tmp_path, delay_seconds=DELAY_SECONDS * 3, port=free_port()
        )
        connection_id = ready_connection(relay, first, key="idem-restart")
        service = relay.agent_relay_service
        run = dispatch(
            relay, connection_id, task_id="task_restart", key="idem-restart-dispatch"
        )
        contacted = service.get_run(run.id, owner_id=OWNER).last_contact_at
        assert contacted is not None

        first.stop()
        start_stub(request, tmp_path, port=first.port)

        until(
            lambda: service.get_run(run.id, owner_id=OWNER).agent_task_missing is True,
            what="the observation that finds no such task",
            timeout=60.0,
        )

        lost = service.get_run(run.id, owner_id=OWNER)
        assert lost.primary_state_label == "Agent no longer reports this run"
        assert lost.reported_state != "completed"
        assert lost.last_contact_at is not None
        assert lost.last_contact_at >= contacted
