"""The exchange side of the observer: pools, bounds, and restart recovery.

Every executor here is synchronous and every clock is controllable, so the
state machine is driven directly rather than raced against real threads — a
sleep would only make the same assertions slower and less trustworthy.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.modules.agents.a2a.client import A2AResult
from app.modules.agents.a2a.types import Task
from app.modules.agents.observer import AgentObserver
from app.modules.agents.repository import AgentRepository
from app.modules.agents.secrets import SecretBox
from app.modules.agents.service import AgentRelayService, TaskSnapshot
from app.schemas.agents import (
    AgentCheckDeliveryRequest,
    AgentConnectionCreateRequest,
    AgentHandoffConfirmRequest,
    AgentHandoffPreviewRequest,
    AgentReplyRequest,
)

from .a2a_fakes import FakeA2AClient, FakeCardFetcher, card_summary, ready_discovery

OWNER = "user_a"
OTHER_OWNER = "user_b"
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


class HeldSendA2AClient(FakeA2AClient):
    """A wire that holds its first send open while the test moves the world.

    A real exchange worker sits inside `SendMessage` for as long as the agent
    takes to answer, and that window is the only moment when a *second*
    submission can observe the connection's slot count. Re-entering here rather
    than racing threads keeps the assertion deterministic without a sleep.
    """

    def __init__(self) -> None:
        super().__init__()
        #: Called once, from inside the first send, then discarded.
        self.during_send: Any = None
        #: The connection's open-exchange count as each send saw it.
        self.open_counts: list[int] = []
        self.probe: Any = None

    def send_message(self, target: Any, **kwargs: Any) -> A2AResult:
        if self.probe is not None:
            self.open_counts.append(self.probe())
        during, self.during_send = self.during_send, None
        if during is not None:
            during()
        return super().send_message(target, **kwargs)


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
    "task_3": TaskSnapshot(id="task_3", title="Third task", details=None),
    "task_4": TaskSnapshot(id="task_4", title="Fourth task", details=None),
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
        secret_box=SecretBox(OrderedDict({"v1": b"\x07" * 32})),
        task_snapshot=task_snapshot,
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

    def test_014_SC_008_the_bound_is_re_checked_where_the_slot_is_actually_taken(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
    ) -> None:
        """AC-034. `open_exchange_count` is the truth, and it moves at start.

        `_slot_available` counts *open* exchanges, and a run that has been
        submitted but not started is still `queued`. Three submissions made
        before any of them starts therefore all see the same free slot, and
        without a second check at the `queued → open` transition every one of
        them would open — one connection holding the whole pool despite
        `max_exchanges_per_connection`.
        """

        executor = DeferredExecutor()
        wire = HeldSendA2AClient()
        service.a2a_client = wire
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
        wire.probe = lambda: repo.open_exchange_count(busy, owner_id=OWNER)
        first = queue_handoff(service, busy, key="idem-d1")
        second = queue_handoff(service, busy, task_id="task_2", key="idem-d2")
        third = queue_handoff(service, busy, task_id="task_3", key="idem-d3")
        elsewhere = queue_handoff(service, other, task_id="task_4", key="idem-d4")

        for run_id in (first, second, third, elsewhere):
            assert observer.submit_exchange(OWNER, run_id) is not None
        # The cheap pre-check admitted all four: none of them is open yet, so
        # each one saw an idle connection. That is the race being closed.
        admitted, executor.pending = executor.pending, []

        seen: dict[str, str] = {}

        def while_the_first_is_held() -> None:
            for fn, args, kwargs in admitted[1:]:
                fn(*args, **kwargs)
            for run_id in (first, second, third, elsewhere):
                seen[run_id] = repo.get_run(run_id, owner_id=OWNER).exchange_state

        wire.during_send = while_the_first_is_held
        held_fn, held_args, held_kwargs = admitted[0]
        held_fn(*held_args, **held_kwargs)

        # One open exchange on the busy connection at every moment a message
        # was on the wire, and the other connection was never made to wait.
        assert max(wire.open_counts) == 1
        assert seen[first] == "open"
        assert seen[second] == "queued"
        assert seen[third] == "queued"
        assert seen[elsewhere] == "closed"

        # The slot freed by the first exchange is what starts the next one, and
        # the drain each finishing worker runs is what notices.
        for _ in range(4):
            pending, executor.pending = executor.pending, []
            for fn, args, kwargs in pending:
                fn(*args, **kwargs)
        assert repo.get_run(second, owner_id=OWNER).exchange_state == "closed"
        assert repo.get_run(third, owner_id=OWNER).exchange_state == "closed"
        # Exactly one message per run: nothing was skipped and nothing doubled.
        assert len(wire.calls_to("SendMessage")) == 4

    def test_014_FR_006_the_confirmed_send_is_executed_on_an_exchange_worker(
        self,
        service: AgentRelayService,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """The invariant is about who *initiates* a send, not who executes it.

        `dispatch_run` returns after its courtesy wait while an exchange worker
        still holds the `SendMessage`, so a background thread does put the
        confirmed content on the wire. What no background thread ever does is
        *decide* to: this one is executing a hand-off a person confirmed, and
        nothing but that person's action ever puts work in the pool.
        """

        executor = DeferredExecutor()
        AgentObserver(service, exchange_executor=executor, clock=clock)
        connection_id = connect_ready(service)
        preview = service.preview_handoff(
            "task_1",
            AgentHandoffPreviewRequest(connection_id=connection_id),
            owner_id=OWNER,
        )
        a2a_client.script(
            "SendMessage",
            A2AResult(
                ok=True, correlation_id="c", task=agent_task("t1", preview.run_id)
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
            idempotency_key="idem-dispatch",
        )

        # The request thread finished the user's call having sent nothing.
        assert run.exchange_state == "queued"
        assert a2a_client.calls_to("SendMessage") == []

        # The worker is what emits it — a background thread, carrying out the
        # confirmation and never a decision of its own.
        executor.run_pending()

        assert len(a2a_client.calls_to("SendMessage")) == 1

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


class TestRestartRecoveryOfAReply:
    """A restart caught mid-*reply* is a different question from mid-hand-off.

    The start of such a run was delivered — that is what `dispatch_state ==
    "sent"` records — and only the owner's answer is in doubt. Treating the two
    the same would take a settled delivery back to **Delivery unconfirmed**,
    which is the one state whose resend path puts the *start* message on the
    wire a second time.
    """

    def _interrupted_reply(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> str:
        """A run whose reply exchange the process died inside of."""

        run_id = dispatched(service, a2a_client, clock)
        run = service.get_run(run_id, owner_id=OWNER)

        def die(*args: Any, **kwargs: Any) -> A2AResult:
            raise RuntimeError("the process stopped mid-send")

        a2a_client.send_message = die  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            service.reply_to_run(
                run_id,
                AgentReplyRequest(
                    message="Yes, go ahead", expected_revision=run.revision
                ),
                owner_id=OWNER,
                idempotency_key="idem-reply",
            )
        del a2a_client.send_message
        interrupted = repo.get_run(run_id, owner_id=OWNER)
        assert interrupted.exchange_state == "open"
        assert interrupted.exchange_kind == "reply"
        assert interrupted.dispatch_state == "sent"
        return run_id

    def test_014_FR_010_a_restart_during_a_reply_never_reopens_the_start(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-030, AC-032, 014-SC-008. The start was delivered; only the answer is in doubt.

        Marking a recovered *reply* `delivery_unconfirmed` would make the run
        eligible for **Check again**, whose resend path sends `_start_message` —
        a second copy of the hand-off the agent already has.
        """

        observer = AgentObserver(
            service, exchange_executor=SynchronousExecutor(), clock=clock
        )
        run_id = self._interrupted_reply(service, repo, clock, a2a_client)
        a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

        observer.recover_interrupted_exchanges()

        recovered = repo.get_run(run_id, owner_id=OWNER)
        assert recovered.exchange_state == "interrupted"
        assert recovered.dispatch_state == "sent"
        assert a2a_client.calls_to("SendMessage") == []

        # And the check that would have resent finds nothing to resolve.
        checked = service.check_delivery(
            run_id,
            AgentCheckDeliveryRequest(),
            owner_id=OWNER,
            idempotency_key="idem-check",
        )
        assert checked.dispatch_state == "sent"
        assert a2a_client.calls_to("SendMessage") == []

    def test_014_FR_010_a_recovered_reply_stays_unacknowledged_until_the_agent_says_so(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-030. The honest state: sent, not acknowledged, and answerable again."""

        observer = AgentObserver(
            service, exchange_executor=SynchronousExecutor(), clock=clock
        )
        run_id = self._interrupted_reply(service, repo, clock, a2a_client)
        a2a_client.script("ListTasks", A2AResult(ok=True, correlation_id="c"))

        observer.recover_interrupted_exchanges()

        run = service.get_run(run_id, owner_id=OWNER)
        assert run.reply_pending is True
        assert [
            command.delivery for command in run.commands if command.kind == "reply"
        ] == ["unconfirmed"]
        assert run.capabilities.reply is True
        assert [
            row.action
            for row in repo.list_audit(owner_id=OWNER)
            if row.action == "exchange_interrupted"
        ] == ["exchange_interrupted"]

    def test_014_FR_010_the_command_id_in_the_history_acknowledges_the_reply(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """The agent's own record of the message is the only evidence there is."""

        observer = AgentObserver(
            service, exchange_executor=SynchronousExecutor(), clock=clock
        )
        run_id = self._interrupted_reply(service, repo, clock, a2a_client)
        command_id = repo.get_run(run_id, owner_id=OWNER).reply_pending_command_id
        assert command_id is not None
        answered = Task.model_validate(
            {
                "id": "t1",
                "contextId": run_id,
                "status": {"state": "TASK_STATE_WORKING"},
                "history": [
                    {
                        "messageId": command_id,
                        "role": "ROLE_USER",
                        "parts": [{"text": "Yes, go ahead"}],
                    }
                ],
            }
        )
        a2a_client.script(
            "ListTasks", A2AResult(ok=True, correlation_id="c", tasks=(answered,))
        )

        observer.recover_interrupted_exchanges()

        run = service.get_run(run_id, owner_id=OWNER)
        assert run.reply_pending is False
        assert [
            command.delivery for command in run.commands if command.kind == "reply"
        ] == ["confirmed"]
        assert repo.get_run(run_id, owner_id=OWNER).dispatch_state == "sent"
        assert a2a_client.calls_to("SendMessage") == []


class TestBootTimeRecoveryIsNotABlockingScan:
    """Recovery is two steps, and only the first may run before the app serves.

    Marking what a restart interrupted is pure state: it needs nothing from the
    network and it is what makes the runs honest. Resolving them is one
    `ListTasks` per open exchange under the short-call deadline, and doing that
    at boot means an unreachable agent holds `/health` for as long as the
    deadline times the backlog — while `fly.backend.toml`'s health check gives
    up after five seconds and restarts the machine that is trying to recover.
    """

    def test_014_SC_007_the_boot_time_mark_asks_the_agent_nothing(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-032. Everything a restart can settle by itself, and nothing else."""

        observer = AgentObserver(
            service, exchange_executor=SynchronousExecutor(), clock=clock
        )
        connection_id = connect_ready(service)
        never_left = queue_handoff(service, connection_id, key="idem-d1")
        in_flight = queue_handoff(
            service, connection_id, task_id="task_2", key="idem-d2"
        )
        assert (
            repo.start_exchange(
                repo.get_run(in_flight, owner_id=OWNER),
                expected_version=0,
                started_at=clock.now,
                deadline_at=clock.now + timedelta(minutes=5),
            )
            is not None
        )
        a2a_client.calls.clear()

        pending = observer.mark_interrupted_exchanges()

        # Not one request: this step is what boot may do, so it may do no I/O.
        assert a2a_client.calls == []
        assert pending == [(OWNER, in_flight)]
        assert repo.get_run(never_left, owner_id=OWNER).dispatch_state == "not_sent"
        marked = repo.get_run(in_flight, owner_id=OWNER)
        assert marked.exchange_state == "interrupted"
        assert marked.dispatch_state == "delivery_unconfirmed"

    def test_014_FR_006_the_lookups_run_on_the_pool_and_settle_the_runs(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """The second step is ordinary pool work, once the app is serving."""

        control = SynchronousExecutor()
        observer = AgentObserver(
            service,
            exchange_executor=SynchronousExecutor(),
            control_executor=control,
            clock=clock,
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
                ok=True, correlation_id="c", tasks=(agent_task("t-adopted", run_id),)
            ),
        )

        pending = observer.mark_interrupted_exchanges()
        observer.resolve_interrupted_exchanges(pending)

        assert len(control.submitted) == 1
        resolved = repo.get_run(run_id, owner_id=OWNER)
        assert resolved.agent_task_id == "t-adopted"
        assert resolved.dispatch_state == "sent"
        assert a2a_client.calls_to("SendMessage") == []

    def test_014_FR_006_neither_step_touches_a_run_that_is_no_longer_in_flight(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """Both halves are safe to repeat, which is what makes them separable.

        Boot can run twice — a supervisor restart during startup is exactly
        that — and the resolver can arrive after the observer has already
        settled the run. Each step therefore checks the state it acts on.
        """

        connection_id = connect_ready(service)
        run_id = dispatched(service, a2a_client, clock)
        assert repo.get_run(run_id, owner_id=OWNER).exchange_state == "closed"
        settled = repo.get_run(run_id, owner_id=OWNER)
        a2a_client.calls.clear()

        service.mark_exchange_interrupted(run_id, owner_id=OWNER)
        service.resolve_interrupted_exchange(run_id, owner_id=OWNER)

        after = repo.get_run(run_id, owner_id=OWNER)
        assert after.exchange_state == "closed"
        assert after.revision == settled.revision
        assert a2a_client.calls == []
        assert connection_id

    def test_014_FR_006_a_run_purged_between_the_two_steps_is_left_alone(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """The gap between marking and resolving is real, so it is survivable."""

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
        pending = observer.mark_interrupted_exchanges()
        repo.delete_all_for_owner(owner_id=OWNER)
        a2a_client.calls.clear()

        observer.resolve_interrupted_exchanges(pending)

        assert a2a_client.calls == []


def test_014_SC_007_health_answers_before_the_boot_lookups_come_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-032. An unreachable agent must not be able to hold the app closed.

    `resolve_interrupted_exchange` is where the `ListTasks` happens, so a
    resolver held on an event is exactly an agent that never answers within the
    short-call deadline. If boot waited for it, `/health` would not answer here
    — and in production `fly.backend.toml`'s five-second check would restart the
    machine that is trying to recover.
    """

    from app import main as main_module
    from app.core import get_config
    from app.modules.agents.observer import AgentObserver as ObserverClass
    from app.modules.agents.service import AgentRelayService as ServiceClass

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "boot-data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST", "1")
    get_config.cache_clear()

    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    resolved: list[str] = []

    def block(self: Any, run_id: str, *, owner_id: str) -> None:
        entered.set()
        release.wait(timeout=5)
        resolved.append(run_id)
        finished.set()

    monkeypatch.setattr(
        ObserverClass,
        "mark_interrupted_exchanges",
        lambda self: [("user_a", "agentrun_stranded")],
    )
    monkeypatch.setattr(ServiceClass, "resolve_interrupted_exchange", block)
    monkeypatch.setattr(
        main_module, "_start_privacy_maintenance_thread", lambda *a, **k: None
    )
    monkeypatch.setattr(main_module, "_start_voice_sweep_thread", lambda *a, **k: None)

    try:
        app = main_module.create_app()
        with TestClient(app) as client:
            assert entered.wait(timeout=5), "the lookup never reached the pool"
            # Boot got this far with the lookup still held, which is the claim.
            assert release.is_set() is False
            assert client.get("/health").status_code == 200

            release.set()
            assert finished.wait(timeout=5), "the resolution never completed"
    finally:
        release.set()
        get_config.cache_clear()

    assert resolved == ["agentrun_stranded"]


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
    # The boot step is the *mark*, not the whole recovery: the lookups go to a
    # pool afterwards (`test_014_SC_007_health_answers_before_the_boot_lookups_
    # come_back`). This asserts the one-shot scan, whichever half it is.
    monkeypatch.setattr(
        ObserverClass,
        "mark_interrupted_exchanges",
        lambda self: calls.append(1) or [],
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


SPEC_ROOT = (
    Path(__file__).resolve().parents[2] / "specs" / "014-a2a-relay-wire-contract"
)

#: What the planning artifacts used to claim, in every form they claimed it.
#: Read literally each one is false — an exchange worker is a background thread
#: and it is the thing that emits the confirmed hand-off.
OVERCLAIMED_SEND_INVARIANT = (
    "no background thread ever emits a content-bearing message",
    "no background thread ever sends (",
    "no brainbuddy background thread ever emits",
    "no background thread — scheduler",
)


def test_014_FR_006_the_send_invariant_is_written_as_initiation_not_execution() -> None:
    """The documents state the invariant the code and these tests actually hold.

    `test_014_FR_006_the_confirmed_send_is_executed_on_an_exchange_worker` and
    `test_no_background_thread_ever_sends_content` are the two halves of it: a
    background worker *executes* every send, and nothing but a user action ever
    *initiates* one. A plan that promised the stronger, false thing would be
    read as a bug report against the pool that makes the reply window survivable.
    """

    documents = {
        "plan.md": SPEC_ROOT / "plan.md",
        "research.md": SPEC_ROOT / "research.md",
        "data-model.md": SPEC_ROOT / "data-model.md",
        "a2a-wire.md": SPEC_ROOT / "contracts" / "a2a-wire.md",
    }

    for name, path in documents.items():
        # Unwrapped: these are hard-wrapped prose files, so a sentence spans
        # lines and asserting on the raw text would only measure the margin.
        prose = " ".join(path.read_text(encoding="utf-8").lower().split())
        for claim in OVERCLAIMED_SEND_INVARIANT:
            assert claim not in prose, f"{name} overclaims: {claim}"
        assert "initiated without a user action" in prose, f"{name} omits the rule"


# --- the observation lane (spec 014, US3) ------------------------------------


def observed_task(
    task_id: str,
    context_id: str | None,
    state: str = "TASK_STATE_WORKING",
    *,
    text: str | None = None,
) -> Task:
    """A task whose state and text a test chooses, unlike `agent_task`."""

    status: dict[str, Any] = {"state": state, "timestamp": "2026-08-09T12:00:00Z"}
    if text is not None:
        status["message"] = {"role": "ROLE_AGENT", "parts": [{"text": text}]}
    return Task.model_validate(
        {"id": task_id, "contextId": context_id, "status": status}
    )


def dispatched(
    service: AgentRelayService,
    a2a_client: FakeA2AClient,
    clock: Clock,
    *,
    connection_id: str | None = None,
    task_id: str = "task_1",
    key: str = "idem-dispatch",
    owner_id: str = OWNER,
) -> str:
    """One confirmed hand-off whose exchange has closed with a live task."""

    connection_id = connection_id or connect_ready(
        service, owner_id=owner_id, key=f"{key}-create"
    )
    executor = SynchronousExecutor()
    observer = AgentObserver(service, exchange_executor=executor, clock=clock)
    a2a_client.script(
        "SendMessage", A2AResult(ok=True, correlation_id="c", task=agent_task("t1", ""))
    )
    preview = service.preview_handoff(
        task_id,
        AgentHandoffPreviewRequest(connection_id=connection_id),
        owner_id=owner_id,
    )
    a2a_client.script(
        "SendMessage",
        A2AResult(ok=True, correlation_id="c", task=agent_task("t1", preview.run_id)),
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
    assert observer is not None
    a2a_client.calls.clear()
    a2a_client.results.clear()
    return run.id


class TestObservationSchedule:
    def _observer(
        self,
        service: AgentRelayService,
        clock: Clock,
        *,
        observation_executor: Any | None = None,
    ) -> AgentObserver:
        return AgentObserver(
            service,
            exchange_executor=SynchronousExecutor(),
            observation_executor=observation_executor or SynchronousExecutor(),
            control_executor=SynchronousExecutor(),
            clock=clock,
        )

    def test_014_FR_008_run_once_observes_every_due_run_across_owners(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-014. The scheduler is process-wide; one owner never blocks another."""

        mine = dispatched(service, a2a_client, clock, key="idem-mine")
        theirs = dispatched(
            service, a2a_client, clock, key="idem-theirs", owner_id=OTHER_OWNER
        )
        observer = self._observer(service, clock)
        a2a_client.script(
            "GetTask",
            A2AResult(ok=True, correlation_id="c", task=observed_task("t1", mine)),
        )
        clock.advance(timedelta(seconds=61))

        assert observer.run_once() == 2

        assert repo.get_run(mine, owner_id=OWNER).last_observed_at == clock.now
        assert repo.get_run(theirs, owner_id=OTHER_OWNER).last_observed_at == clock.now

    def test_014_FR_008_one_probe_per_unreachable_connection_covers_its_runs(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """A dead agent costs one request per pass, not one per run."""

        connection_id = connect_ready(service, key="idem-shared")
        first = dispatched(
            service,
            a2a_client,
            clock,
            connection_id=connection_id,
            key="idem-run-a",
        )
        second = dispatched(
            service,
            a2a_client,
            clock,
            connection_id=connection_id,
            task_id="task_2",
            key="idem-run-b",
        )
        observer = self._observer(service, clock)
        a2a_client.script(
            "GetTask",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_unreachable"),
        )
        clock.advance(timedelta(seconds=61))

        observer.run_once()

        assert len(a2a_client.calls_to("GetTask")) == 1
        for run_id in (first, second):
            run = repo.get_run(run_id, owner_id=OWNER)
            assert run.next_observation_at is not None
            assert run.next_observation_at > clock.now

    def test_014_FR_008_an_in_flight_run_is_never_observed_twice_at_once(
        self,
        service: AgentRelayService,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """Coalescing: a slow observation must not stack up behind itself."""

        run_id = dispatched(service, a2a_client, clock)
        deferred = DeferredExecutor()
        observer = self._observer(service, clock, observation_executor=deferred)
        clock.advance(timedelta(seconds=61))

        assert observer.run_once() == 1
        assert observer.run_once() == 0

        deferred.run_pending()
        clock.advance(timedelta(seconds=61))
        assert observer.run_once() == 1
        assert run_id

    def test_014_FR_008_the_interval_backs_off_after_the_reporting_window(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-019. A silent agent is polled less, never abandoned."""

        run_id = dispatched(service, a2a_client, clock)
        observer = self._observer(service, clock)
        a2a_client.script(
            "GetTask",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_timeout"),
        )

        clock.advance(timedelta(seconds=61))
        observer.run_once()
        base = repo.get_run(run_id, owner_id=OWNER).next_observation_at
        assert base == clock.now + timedelta(seconds=60)

        clock.advance(timedelta(hours=2))
        observer.run_once()
        backed_off = repo.get_run(run_id, owner_id=OWNER).next_observation_at
        assert backed_off is not None
        assert backed_off > clock.now + timedelta(seconds=60)
        assert backed_off <= clock.now + timedelta(seconds=600), "capped at 10x"

    def test_014_FR_008_a_user_read_of_the_run_resets_the_backoff(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """Someone is watching, so BrainBuddy looks again at the base rate."""

        run_id = dispatched(service, a2a_client, clock)
        observer = self._observer(service, clock)
        a2a_client.script(
            "GetTask",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_timeout"),
        )
        clock.advance(timedelta(hours=3))
        observer.run_once()
        assert repo.get_run(run_id, owner_id=OWNER).next_observation_at is not None

        service.get_run(run_id, owner_id=OWNER)

        assert repo.get_run(run_id, owner_id=OWNER).next_observation_at == (
            clock.now + timedelta(seconds=60)
        )

    def test_014_FR_010_a_missing_task_stops_observation_for_good(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-020. There is nothing left to look for, so nothing looks again."""

        run_id = dispatched(service, a2a_client, clock)
        observer = self._observer(service, clock)
        a2a_client.script(
            "GetTask",
            A2AResult(
                ok=False,
                correlation_id="c",
                error_code="a2a_task_not_found",
                a2a_error_code=-32001,
            ),
        )
        clock.advance(timedelta(seconds=61))

        observer.run_once()

        run = repo.get_run(run_id, owner_id=OWNER)
        assert run.agent_task_missing_at == clock.now
        assert run.next_observation_at is None
        clock.advance(timedelta(hours=1))
        assert observer.run_once() == 0

    def test_014_FR_008_a_terminal_observation_stops_the_schedule(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        run_id = dispatched(service, a2a_client, clock)
        observer = self._observer(service, clock)
        a2a_client.script(
            "GetTask",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=observed_task(
                    "t1", run_id, "TASK_STATE_COMPLETED", text="All done."
                ),
            ),
        )
        clock.advance(timedelta(seconds=61))

        observer.run_once()

        run = repo.get_run(run_id, owner_id=OWNER)
        assert run.reported_state == "completed"
        assert run.next_observation_at is None

    def test_014_SC_006_a_delayed_agent_shows_sent_then_a_true_terminal_state(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """014-SC-006. Five minutes of silence is not a failure BrainBuddy invents."""

        run_id = dispatched(service, a2a_client, clock)
        observer = self._observer(service, clock)
        a2a_client.script(
            "GetTask",
            A2AResult(ok=True, correlation_id="c", task=observed_task("t1", run_id)),
        )

        for _ in range(5):
            clock.advance(timedelta(seconds=60))
            observer.run_once()
            projection = service.get_run(run_id, owner_id=OWNER)
            assert projection.primary_state_label in {"Sent", "Running"}
            assert projection.reported_state != "failed"

        a2a_client.script(
            "GetTask",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=observed_task("t1", run_id, "TASK_STATE_COMPLETED", text="Done."),
            ),
        )
        clock.advance(timedelta(seconds=60))
        observer.run_once()

        assert service.get_run(run_id, owner_id=OWNER).primary_state_label == (
            "Agent reported complete"
        )
        assert repo.get_run(run_id, owner_id=OWNER).last_observed_at == clock.now

    def test_ambiguous_reply_exchange_resumes_observation_at_the_deadline(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-033. The suspension has an exit, so no run is left unobserved."""

        run_id = dispatched(service, a2a_client, clock)
        observer = self._observer(service, clock)
        run = repo.get_run(run_id, owner_id=OWNER)
        repo.save_run(
            run.model_copy(
                update={
                    "exchange_state": "open",
                    "exchange_kind": "reply",
                    "exchange_started_at": clock.now,
                    "exchange_deadline_at": clock.now + timedelta(seconds=315),
                    "next_observation_at": clock.now,
                }
            )
        )
        a2a_client.script(
            "GetTask",
            A2AResult(ok=True, correlation_id="c", task=observed_task("t1", run_id)),
        )

        observer.run_once()
        assert a2a_client.calls_to("GetTask") == []

        clock.advance(timedelta(seconds=316))
        observer.run_once()

        assert len(a2a_client.calls_to("GetTask")) == 1

    def test_no_background_thread_ever_sends_content(
        self,
        service: AgentRelayService,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-032. Only a person's own confirmation may put content on the wire.

        The name is about *initiation*, which is the invariant: an exchange
        worker is a background thread and it does emit the confirmed hand-off
        (`test_014_FR_006_the_confirmed_send_is_executed_on_an_exchange_worker`).
        What no background entry point ever does is start one — and these four
        are every entry point there is.
        """

        run_id = dispatched(service, a2a_client, clock)
        observer = self._observer(service, clock)
        a2a_client.script(
            "GetTask",
            A2AResult(ok=False, correlation_id="c", error_code="a2a_timeout"),
        )
        clock.advance(timedelta(seconds=61))

        observer.run_once()
        observer.recover_interrupted_exchanges()
        observer.drain_queued_exchanges()
        service.run_retention_sweep()

        assert a2a_client.calls_to("SendMessage") == []
        assert run_id

    def test_purge_during_observation_writes_no_row(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """FR-016. A worker that outlived a purge must not recreate its run."""

        run_id = dispatched(service, a2a_client, clock)
        deferred = DeferredExecutor()
        observer = self._observer(service, clock, observation_executor=deferred)
        a2a_client.script(
            "GetTask",
            A2AResult(ok=True, correlation_id="c", task=observed_task("t1", run_id)),
        )
        clock.advance(timedelta(seconds=61))
        observer.run_once()

        service.delete_all_for_owner(owner_id=OWNER)
        deferred.run_pending()

        assert repo.list_runs_for_owner(owner_id=OWNER) == []
        assert service.list_audit(owner_id=OWNER) == []

    def test_014_FR_008_a_verified_push_wakes_an_observation_at_once(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """A push only accelerates the pass the schedule would run anyway."""

        run_id = dispatched(service, a2a_client, clock)
        observer = self._observer(service, clock)
        a2a_client.script(
            "GetTask",
            A2AResult(ok=True, correlation_id="c", task=observed_task("t1", run_id)),
        )

        observer.wake(run_id)
        assert observer.run_once() == 1

        assert repo.get_run(run_id, owner_id=OWNER).last_observed_at == clock.now
        assert len(a2a_client.calls_to("GetTask")) == 1

    def test_014_FR_008_a_control_call_never_waits_behind_an_exchange(
        self,
        service: AgentRelayService,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """AC-035. Cancel has its own lane, because cancel is what ends a hold."""

        run_id = dispatched(service, a2a_client, clock)
        held = DeferredExecutor()
        control = SynchronousExecutor()
        AgentObserver(
            service,
            exchange_executor=held,
            observation_executor=SynchronousExecutor(),
            control_executor=control,
            clock=clock,
        )
        a2a_client.script(
            "CancelTask",
            A2AResult(
                ok=True,
                correlation_id="c",
                task=observed_task("t1", run_id, "TASK_STATE_CANCELED"),
            ),
        )

        run = service.cancel_run(run_id, owner_id=OWNER, idempotency_key="idem-cancel")

        assert run.cancel_outcome == "accepted"
        assert control.submitted, "the cancel ran on the control pool"
        assert held.pending == [], "and never on the held exchange pool"


def test_014_FR_008_main_starts_and_stops_the_observer_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T092's guardrail: one scheduler per app, and none under TEST.

    The suite builds many short-lived apps in one process over a process-wide
    lock, so a scheduler started per app would race unrelated tests — which is
    why the same gate that holds back the maintenance sweeps holds this back
    too, and why the opt-in has to be explicit.
    """

    from app import main as main_module

    starts: list[str] = []
    stops: list[str] = []

    class RecordingObserver:
        def mark_interrupted_exchanges(self) -> list[tuple[str, str]]:
            return []

        def resolve_interrupted_exchanges(self, pending: Any) -> int:
            return 0

        def start(self) -> bool:
            starts.append("start")
            return True

        def shutdown(self) -> None:
            stops.append("stop")

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        main_module, "build_container", _container_with(RecordingObserver())
    )

    monkeypatch.setenv("BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST", "1")
    app = main_module.create_app()
    assert starts == ["start"]
    assert stops == []

    # The lifespan is the one supported way to run the shutdown hooks: the
    # `Router.shutdown()` and `on_shutdown` accessors are gone in Starlette
    # 1.x, which an unpinned install (CI's) resolves. Entering the client runs
    # startup, which must not start a second scheduler; leaving it runs
    # `_stop_maintenance_sweeps`, which must stop the one there is, once.
    with TestClient(app):
        assert starts == ["start"]
        assert stops == []
    assert starts == ["start"]
    assert stops == ["stop"]


def _container_with(observer: Any) -> Any:
    """Wrap the real container builder, swapping in a recording observer."""

    from app.container import build_container as real_build_container

    def build(config: Any) -> Any:
        container = real_build_container(config)
        container.agent_observer.shutdown()
        return replace(container, agent_observer=observer)

    return build


class TestObserverLifecycle:
    def test_observer_scheduler_starts_and_stops_once(
        self, service: AgentRelayService, clock: Clock
    ) -> None:
        """The scheduler is a tracked thread, joined at shutdown with a bound."""

        executor = SynchronousExecutor()
        observer = AgentObserver(
            service,
            exchange_executor=executor,
            observation_executor=SynchronousExecutor(),
            control_executor=SynchronousExecutor(),
            clock=clock,
            observation_interval=timedelta(seconds=0.01),
        )

        assert observer.start() is True
        assert observer.start() is False, "starting twice would double every pass"

        observer.shutdown()

        assert observer.scheduler_thread is not None
        assert observer.scheduler_thread.is_alive() is False
        assert executor.shutdowns == [{"wait": False, "cancel_futures": True}]
        observer.shutdown()


class TestObservationEdges:
    """What the scheduler does when the world moves under it."""

    def _observer(
        self, service: AgentRelayService, clock: Clock, **kwargs: Any
    ) -> AgentObserver:
        return AgentObserver(
            service,
            exchange_executor=SynchronousExecutor(),
            observation_executor=SynchronousExecutor(),
            control_executor=SynchronousExecutor(),
            clock=clock,
            **kwargs,
        )

    def test_014_FR_016_a_run_purged_between_selection_and_read_is_skipped(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """The pass takes responsibility for nothing that no longer exists."""

        run_id = dispatched(service, a2a_client, clock, key="idem-vanish")
        observer = self._observer(service, clock)
        clock.advance(timedelta(seconds=61))
        due = repo.due_observations(now=clock.now)
        assert [pair[1] for pair in due] == [run_id]
        service.delete_all_for_owner(owner_id=OWNER)

        assert observer.run_once() == 0
        assert a2a_client.calls_to("GetTask") == []

    def test_014_FR_008_a_wake_for_a_run_nobody_owns_drains_harmlessly(
        self, service: AgentRelayService, clock: Clock
    ) -> None:
        """The push route's own lookup is the gate; this one refuses to guess."""

        observer = self._observer(service, clock)

        observer.wake("agentrun_never_existed")

        assert observer.run_once() == 0

    def test_014_FR_008_an_observation_with_no_wire_writes_nothing(
        self,
        service: AgentRelayService,
        repo: AgentRepository,
        clock: Clock,
        a2a_client: FakeA2AClient,
    ) -> None:
        """Absent is not empty: a service with no client learns nothing."""

        run_id = dispatched(service, a2a_client, clock, key="idem-nowire")
        observer = self._observer(service, clock)
        before = repo.get_run(run_id, owner_id=OWNER)
        service.a2a_client = None
        clock.advance(timedelta(seconds=61))

        observer.run_once()

        after = repo.get_run(run_id, owner_id=OWNER)
        assert after.last_observed_at == before.last_observed_at
        assert after.reported_state == before.reported_state

    def test_014_FR_008_one_failing_pass_does_not_end_the_scheduler(
        self, service: AgentRelayService, clock: Clock
    ) -> None:
        """A scheduler that dies on one bad pass stops every run in the deployment."""

        observer = self._observer(
            service, clock, observation_interval=timedelta(seconds=0.01)
        )
        passes: list[int] = []

        def explode() -> int:
            passes.append(1)
            if len(passes) == 1:
                raise RuntimeError("one bad pass")
            observer.shutdown()
            return 0

        observer.run_once = explode  # type: ignore[method-assign]

        assert observer.start() is True
        for _ in range(200):
            if len(passes) >= 2:
                break
            time.sleep(0.01)
        observer.shutdown()

        assert len(passes) >= 2, "the loop kept going after the failure"
