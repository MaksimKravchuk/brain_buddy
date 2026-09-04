"""The exchange side of the observer: pools, bounds, and restart recovery.

Every executor here is synchronous and every clock is controllable, so the
state machine is driven directly rather than raced against real threads — a
sleep would only make the same assertions slower and less trustworthy.
"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.modules.agents.a2a.client import A2AResult
from app.modules.agents.a2a.types import Task
from app.modules.agents.observer import AgentObserver
from app.modules.agents.repository import AgentRepository
from app.modules.agents.secrets import SecretBox
from app.modules.agents.service import AgentRelayService, TaskSnapshot
from app.schemas.agents import (
    AgentConnectionCreateRequest,
    AgentHandoffConfirmRequest,
    AgentHandoffPreviewRequest,
)

from .a2a_fakes import FakeA2AClient, FakeCardFetcher, card_summary, ready_discovery

OWNER = "user_a"
OTHER_OWNER = "user_b"
CALLBACK = "https://brainbuddy.example/api/agent-events"
PUSH_BASE = "https://brainbuddy.example/api/a2a/push"


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class SynchronousExecutor:
    """A pool with one always-free worker: `submit` runs the work inline."""

    def __init__(self) -> None:
        self.submitted: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] = []
        self.shutdowns: list[dict[str, Any]] = []

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        self.submitted.append((fn, args, kwargs))
        future: Future[Any] = Future()
        future.set_result(fn(*args, **kwargs))
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.shutdowns.append({"wait": wait, "cancel_futures": cancel_futures})


class DeferredExecutor:
    """A pool that accepts work and runs it only when the test says so."""

    def __init__(self) -> None:
        self.pending: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] = []
        self.shutdowns: list[dict[str, Any]] = []

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        self.pending.append((fn, args, kwargs))
        return Future()

    def run_pending(self) -> None:
        pending, self.pending = self.pending, []
        for fn, args, kwargs in pending:
            fn(*args, **kwargs)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.shutdowns.append({"wait": wait, "cancel_futures": cancel_futures})


TASKS = {
    "task_1": TaskSnapshot(id="task_1", title="Draft the plan", details=None),
    "task_2": TaskSnapshot(id="task_2", title="Second task", details=None),
}


def task_snapshot(task_id: str, *, owner_id: str) -> TaskSnapshot:
    return TASKS[task_id]


def resolver(host: str, port: int) -> list[str]:
    return {
        "agent.example.com": ["93.184.216.34"],
        "second.example.com": ["93.184.216.35"],
    }[host]


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 8, 9, 12, 0, tzinfo=UTC))


@pytest.fixture
def a2a_client() -> FakeA2AClient:
    return FakeA2AClient()


@pytest.fixture
def repo(tmp_path: Path) -> AgentRepository:
    return AgentRepository(tmp_path)


@pytest.fixture
def service(
    repo: AgentRepository, clock: Clock, a2a_client: FakeA2AClient
) -> AgentRelayService:
    return AgentRelayService(
        repo,
        connector=object(),  # type: ignore[arg-type]
        secret_box=SecretBox(OrderedDict({"v1": b"\x07" * 32})),
        task_snapshot=task_snapshot,
        callback_url=CALLBACK,
        push_base_url=PUSH_BASE,
        card_fetcher=FakeCardFetcher(),
        a2a_client=a2a_client,
        resolver=resolver,
        now=clock,
    )


def connect_ready(
    service: AgentRelayService,
    *,
    owner_id: str = OWNER,
    address: str = "https://agent.example.com",
    key: str = "idem-create",
) -> str:
    created = service.create_connection(
        AgentConnectionCreateRequest.model_validate(
            {
                "name": "Hermes",
                "agent_address": address,
                "credential": "Bearer super-secret-token",
                "current_password": "correct-horse-battery-staple",
            }
        ),
        owner_id=owner_id,
        idempotency_key=key,
        reauthenticated=True,
    )
    service.test_connection(created.id, owner_id=owner_id)
    return created.id


def queue_handoff(
    service: AgentRelayService,
    connection_id: str,
    *,
    owner_id: str = OWNER,
    task_id: str = "task_1",
    key: str = "idem-dispatch",
) -> str:
    """Confirm one hand-off with no exchange pump, so it stays **Queued**.

    Detaching the pump is how "no worker took it yet" is made deterministic;
    it is the same durable state a saturated pool or a restart leaves behind.
    """

    pump, service.exchange_pump = service.exchange_pump, None
    try:
        return _confirm(service, connection_id, owner_id, task_id, key)
    finally:
        service.exchange_pump = pump


def _confirm(
    service: AgentRelayService,
    connection_id: str,
    owner_id: str,
    task_id: str,
    key: str,
) -> str:
    preview = service.preview_handoff(
        task_id,
        AgentHandoffPreviewRequest(connection_id=connection_id),
        owner_id=owner_id,
    )
    run = service.dispatch_run(
        task_id,
        AgentHandoffConfirmRequest(
            connection_id=connection_id,
            manifest_token=preview.token,
            acknowledge_duplicate_risk=True,
        ),
        owner_id=owner_id,
        idempotency_key=key,
    )
    assert run.exchange_state == "queued"
    return run.id


def agent_task(task_id: str, context_id: str | None) -> Task:
    return Task.model_validate(
        {
            "id": task_id,
            "contextId": context_id,
            "status": {"state": "TASK_STATE_WORKING"},
        }
    )


class TestExchangePool:
    def test_014_FR_006_the_exchange_stamps_at_start_and_never_at_submit(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """The gap between submit and start is exactly the **Queued** window."""

        executor = DeferredExecutor()
        observer = AgentObserver(service, exchange_executor=executor, clock=clock)
        connection_id = connect_ready(service)
        run_id = queue_handoff(service, connection_id)
        a2a_client.script(
            "SendMessage",
            A2AResult(ok=True, correlation_id="c", task=agent_task("t1", run_id)),
        )

        observer.submit_exchange(OWNER, run_id)
        submitted = repo.get_run(run_id, owner_id=OWNER)
        assert submitted.exchange_state == "queued"
        assert submitted.exchange_started_at is None
        assert (
            repo.get_connection(connection_id, owner_id=OWNER).first_dispatch_at is None
        )

        clock.advance(timedelta(seconds=45))
        executor.run_pending()

        started = repo.get_run(run_id, owner_id=OWNER)
        assert started.exchange_started_at == clock.now
        assert repo.get_connection(connection_id, owner_id=OWNER).first_dispatch_at == (
            clock.now
        )

    def test_014_FR_007_one_connection_holds_at_most_its_share_of_workers(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        a2a_client: FakeA2AClient,
        clock: Clock,
    ) -> None:
        """AC-034. Excess stays **Queued**; another connection still proceeds."""

        executor = DeferredExecutor()
        observer = AgentObserver(
            service,
            exchange_executor=executor,
            clock=clock,
            max_exchanges_per_connection=1,
        )
        busy = connect_ready(service)
        other = connect_ready(
            service, address="https://second.example.com", key="idem-2"
        )
        first = queue_handoff(service, busy, key="idem-d1")
        second = queue_handoff(service, busy, task_id="task_2", key="idem-d2")
        third = queue_handoff(service, other, key="idem-d3")
        a2a_client.script(
            "SendMessage",
            A2AResult(ok=True, correlation_id="c", task=agent_task("t1", first)),
        )

        # The first exchange takes the connection's only slot and stays open,
        # because the worker has not been run yet.
        observer.submit_exchange(OWNER, first)
        started = repo.start_exchange(
            repo.get_run(first, owner_id=OWNER),
            expected_version=0,
            started_at=clock.now,
            deadline_at=clock.now + timedelta(minutes=5),
        )
        assert started is not None

        assert observer.submit_exchange(OWNER, second) is None
        assert repo.get_run(second, owner_id=OWNER).exchange_state == "queued"
        assert observer.submit_exchange(OWNER, third) is not None

    def test_014_FR_007_queued_exchanges_are_drained_owner_by_owner(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
    ) -> None:
        """One owner's backlog never starves another's first hand-off."""

        executor = DeferredExecutor()
        observer = AgentObserver(
            service,
            exchange_executor=executor,
            clock=clock,
            max_exchanges_per_connection=4,
        )
        mine = connect_ready(service)
        theirs = connect_ready(service, owner_id=OTHER_OWNER, key="idem-other")
        # A minute apart, so "oldest first" within an owner is a fact about the
        # queue rather than a tie broken by an identifier.
        first = queue_handoff(service, mine, key="idem-d1")
        clock.advance(timedelta(minutes=1))
        second = queue_handoff(service, mine, task_id="task_2", key="idem-d2")
        clock.advance(timedelta(minutes=1))
        third = queue_handoff(service, theirs, owner_id=OTHER_OWNER, key="idem-d3")

        observer.drain_queued_exchanges()

        # Round robin, not FIFO: the second owner's only hand-off is served
        # before this owner's second one.
        assert [args[1] for _fn, args, _kwargs in executor.pending] == [
            first,
            third,
            second,
        ]

    def test_014_FR_007_an_exchange_that_is_no_longer_queued_is_not_submitted(
        self, service: AgentRelayService, repo: AgentRepository, clock: Clock
    ) -> None:
        """Whoever started it owns it; a second submission would be a second send."""

        executor = DeferredExecutor()
        observer = AgentObserver(service, exchange_executor=executor, clock=clock)
        connection_id = connect_ready(service)
        run_id = queue_handoff(service, connection_id)
        assert (
            repo.start_exchange(
                repo.get_run(run_id, owner_id=OWNER),
                expected_version=0,
                started_at=clock.now,
                deadline_at=clock.now + timedelta(minutes=5),
            )
            is not None
        )

        assert observer.submit_exchange(OWNER, run_id) is None
        assert executor.pending == []

    def test_014_FR_007_a_drain_leaves_what_the_bound_will_not_admit(
        self, service: AgentRelayService, repo: AgentRepository, clock: Clock
    ) -> None:
        """AC-034: excess stays **Queued**, and the drain says so by starting nothing."""

        executor = DeferredExecutor()
        observer = AgentObserver(
            service,
            exchange_executor=executor,
            clock=clock,
            max_exchanges_per_connection=1,
        )
        connection_id = connect_ready(service)
        held = queue_handoff(service, connection_id, key="idem-held")
        clock.advance(timedelta(minutes=1))
        waiting = queue_handoff(
            service, connection_id, task_id="task_2", key="idem-wait"
        )
        assert (
            repo.start_exchange(
                repo.get_run(held, owner_id=OWNER),
                expected_version=0,
                started_at=clock.now,
                deadline_at=clock.now + timedelta(minutes=5),
            )
            is not None
        )

        assert observer.drain_queued_exchanges() == 0

        assert executor.pending == []
        assert repo.get_run(waiting, owner_id=OWNER).exchange_state == "queued"

    def test_014_FR_008_shutdown_cancels_the_work_that_never_started(
        self, service: AgentRelayService, clock: Clock
    ) -> None:
        """An unstarted exchange is cancelled; a running one is not abandoned."""

        executor = DeferredExecutor()
        observer = AgentObserver(service, exchange_executor=executor, clock=clock)

        observer.shutdown()

        assert executor.shutdowns == [{"wait": False, "cancel_futures": True}]


class TestRestartRecovery:
    def test_014_FR_006_a_queued_exchange_is_settled_as_restarted_before_send(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-032. Nothing left BrainBuddy, so nothing is claimed to have."""

        observer = AgentObserver(
            service, exchange_executor=SynchronousExecutor(), clock=clock
        )
        connection_id = connect_ready(service)
        run_id = queue_handoff(service, connection_id)

        observer.recover_interrupted_exchanges()

        settled = repo.get_run(run_id, owner_id=OWNER)
        assert settled.dispatch_state == "not_sent"
        assert settled.dispatch_error_code == "restarted_before_send"
        assert settled.exchange_state == "closed"
        # The identifiers survive, so the same hand-off can be offered again.
        assert settled.message_id == f"{run_id}:start"
        assert settled.context_id == run_id
        assert a2a_client.calls_to("SendMessage") == []
        # Nothing left, so the first-content trigger is still unspent.
        assert (
            repo.get_connection(connection_id, owner_id=OWNER).first_dispatch_at is None
        )
        assert service.get_run(run_id, owner_id=OWNER).primary_state_label == "Not sent"

    def test_014_FR_006_an_open_exchange_is_resolved_by_lookup_only(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-032. The message may already be at the agent, so we look, never send."""

        observer = AgentObserver(
            service, exchange_executor=SynchronousExecutor(), clock=clock
        )
        connection_id = connect_ready(service)
        run_id = queue_handoff(service, connection_id)
        started = repo.start_exchange(
            repo.get_run(run_id, owner_id=OWNER),
            expected_version=0,
            started_at=clock.now,
            deadline_at=clock.now + timedelta(minutes=5),
        )
        assert started is not None
        a2a_client.script(
            "ListTasks",
            A2AResult(
                ok=True, correlation_id="c", tasks=(agent_task("t-adopted", run_id),)
            ),
        )

        observer.recover_interrupted_exchanges()

        resolved = repo.get_run(run_id, owner_id=OWNER)
        assert resolved.agent_task_id == "t-adopted"
        assert resolved.dispatch_state == "sent"
        assert a2a_client.calls_to("SendMessage") == []

    def test_014_FR_006_an_open_exchange_with_nothing_to_find_stays_unconfirmed(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """An empty lookup is not evidence of anything, so nothing is claimed."""

        observer = AgentObserver(
            service, exchange_executor=SynchronousExecutor(), clock=clock
        )
        connection_id = connect_ready(service)
        run_id = queue_handoff(service, connection_id)
        assert (
            repo.start_exchange(
                repo.get_run(run_id, owner_id=OWNER),
                expected_version=0,
                started_at=clock.now,
                deadline_at=clock.now + timedelta(minutes=5),
            )
            is not None
        )
        a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

        observer.recover_interrupted_exchanges()

        resolved = repo.get_run(run_id, owner_id=OWNER)
        assert resolved.dispatch_state == "delivery_unconfirmed"
        assert resolved.agent_task_id is None
        assert resolved.exchange_state == "interrupted"
        assert a2a_client.calls_to("SendMessage") == []
        assert (
            service.get_run(run_id, owner_id=OWNER).primary_state_label
            == "Delivery unconfirmed"
        )

    def test_014_FR_006_a_foreign_task_is_never_adopted_by_recovery(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """A lookup that matched loosely would settle a run with someone else's work."""

        observer = AgentObserver(
            service, exchange_executor=SynchronousExecutor(), clock=clock
        )
        connection_id = connect_ready(service)
        run_id = queue_handoff(service, connection_id)
        assert (
            repo.start_exchange(
                repo.get_run(run_id, owner_id=OWNER),
                expected_version=0,
                started_at=clock.now,
                deadline_at=clock.now + timedelta(minutes=5),
            )
            is not None
        )
        a2a_client.script(
            "ListTasks",
            A2AResult(
                ok=True,
                correlation_id="c",
                tasks=(agent_task("t-someone-else", "another-conversation"),),
            ),
        )

        observer.recover_interrupted_exchanges()

        resolved = repo.get_run(run_id, owner_id=OWNER)
        assert resolved.agent_task_id is None
        assert resolved.dispatch_state == "delivery_unconfirmed"


@pytest.mark.parametrize("opted_in", [False, True])
def test_014_FR_006_restart_recovery_is_invoked_once_at_boot_under_background_maintenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opted_in: bool
) -> None:
    """Once, at boot, and only where background maintenance is allowed to run.

    The guardrail T070's wiring exists for: a boot-time scan that ran twice
    would resolve the same interrupted exchange twice, and one that ran in every
    short-lived test app would race unrelated tests over a process-wide lock.
    """

    from app import main as main_module
    from app.core import get_config
    from app.modules.agents.observer import AgentObserver as ObserverClass

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "boot-data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    if opted_in:
        monkeypatch.setenv("BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST", "1")
    else:
        monkeypatch.delenv("BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST", raising=False)
    get_config.cache_clear()

    calls: list[int] = []
    monkeypatch.setattr(
        ObserverClass,
        "recover_interrupted_exchanges",
        lambda self: calls.append(1) or 0,
    )
    # No real maintenance threads: this test is about the one-shot scan, and a
    # background thread outliving its own temp directory is the hazard the
    # gating exists to avoid in the first place.
    monkeypatch.setattr(
        main_module, "_start_privacy_maintenance_thread", lambda *a, **k: None
    )
    monkeypatch.setattr(main_module, "_start_voice_sweep_thread", lambda *a, **k: None)

    main_module.create_app()

    assert len(calls) == (1 if opted_in else 0)
    get_config.cache_clear()


def test_014_FR_002_a_guaranteed_card_still_recovers_by_lookup(
    service: AgentRelayService,
    repo: AgentRepository,
    clock: Clock,
    a2a_client: FakeA2AClient,
) -> None:
    """The tier changes the wire, never the recovery rule: no thread resends."""

    service._card_fetcher = FakeCardFetcher()  # type: ignore[assignment]
    service._card_fetcher.discovery = ready_discovery(  # type: ignore[attr-defined]
        summary=card_summary(
            extension_uris=["https://brainbuddy.app/a2a/single-start/v1"]
        )
    )
    observer = AgentObserver(
        service, exchange_executor=SynchronousExecutor(), clock=clock
    )
    connection_id = connect_ready(service)
    run_id = queue_handoff(service, connection_id)
    assert (
        repo.start_exchange(
            repo.get_run(run_id, owner_id=OWNER),
            expected_version=0,
            started_at=clock.now,
            deadline_at=clock.now + timedelta(minutes=5),
        )
        is not None
    )
    a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

    observer.recover_interrupted_exchanges()

    assert a2a_client.calls_to("SendMessage") == []
