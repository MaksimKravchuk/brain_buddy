"""Who gets a worker, when, and what a restart owes them.

The service knows what one exchange or observation *means*; this knows how many
may run at once, in whose order, and how soon. Keeping the two apart is what
lets the wire rules be tested without threads and the concurrency rules without
a socket.

Three separately bounded pools, not one, and the separation is a correctness
property rather than tuning. A held ``SendMessage`` occupies its worker for up
to the reply window; an observation is short but constant; and a cancel is what
*resolves* a held exchange on some runtimes, so a cancel queued behind the
exchanges it ends would wait out the entire window while the surface could not
tell pool saturation from an agent that simply ignores cancellation.

Nothing here decides what a run means. It schedules, it drains wakes, it makes
the call, and it hands the answer to the service — which is why a state machine
bug can never hide in a thread.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from app.exceptions import NotFoundError
from app.utils.time import utcnow

from .a2a.client import A2A_TASK_NOT_FOUND
from .domain import observation_is_suspended

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .service import AgentRelayService

logger = logging.getLogger(__name__)

#: Exchange workers one connection may hold at once, when the caller says
#: nothing. Mirrors ``AgentRelaySettings.max_exchanges_per_connection``.
DEFAULT_MAX_EXCHANGES_PER_CONNECTION = 2

#: The base schedule when the caller says nothing. Mirrors
#: ``AgentRelaySettings.observation_interval_seconds``.
DEFAULT_OBSERVATION_INTERVAL = timedelta(seconds=60)

#: How long shutdown waits for the scheduler to notice the stop event. Bounded
#: because a shutdown that hangs is indistinguishable from a crash to whatever
#: is restarting the process.
SCHEDULER_JOIN_SECONDS = 5.0


class ExchangePool(Protocol):
    """The two methods the exchange lane needs from a pool.

    ``shutdown`` is part of the port because how a pool is *stopped* is a
    correctness property here, not housekeeping: an exchange that has already
    started may be at the agent, and cancelling it would leave a run whose
    state nobody will ever settle.
    """

    def submit(
        self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any
    ) -> Future[Any]: ...

    def shutdown(self, wait: bool = ..., *, cancel_futures: bool = ...) -> None: ...


class AgentObserver:
    """Owns the exchange pool, its bounds, and recovery after a restart."""

    def __init__(
        self,
        service: AgentRelayService,
        *,
        exchange_executor: ExchangePool,
        observation_executor: ExchangePool | None = None,
        control_executor: ExchangePool | None = None,
        clock: Callable[[], datetime] = utcnow,
        probe_delay: float = 0.0,
        max_exchanges_per_connection: int = DEFAULT_MAX_EXCHANGES_PER_CONNECTION,
        observation_interval: timedelta = DEFAULT_OBSERVATION_INTERVAL,
    ) -> None:
        self.service = service
        self.exchange_executor = exchange_executor
        # Falls back to the exchange pool only so a test can construct the
        # exchange half alone; a real deployment gives all three (container.py).
        self.observation_executor: ExchangePool = (
            observation_executor or exchange_executor
        )
        self.control_executor = control_executor
        self.max_exchanges_per_connection = max_exchanges_per_connection
        self.observation_interval = observation_interval
        self._now = clock
        self.probe_delay = probe_delay
        self._lock = threading.Lock()
        self._in_flight: set[str] = set()
        self._woken: set[str] = set()
        self._wake_event = threading.Event()
        self._stop = threading.Event()
        self.scheduler_thread: threading.Thread | None = None
        # The service submits through here, so the bound below is not something
        # a dispatch can route around.
        service.exchange_pump = self.submit_exchange
        # And the bound itself goes with it. `_slot_available` counts *open*
        # exchanges, so it cannot see submissions that have not started yet;
        # the service re-checks this same number at the queued → open
        # transition, under the lock that serialises it, which is the only
        # place the count is authoritative. One value, published once, so the
        # pre-check and the admission can never disagree about the bound.
        service.max_exchanges_per_connection = self.max_exchanges_per_connection
        service.observer_wake = self.wake
        if control_executor is not None:
            service.control_pump = self.submit_control

    # --- submission ---------------------------------------------------------

    def submit_exchange(self, owner_id: str, run_id: str) -> Future[Any] | None:
        """Give one queued exchange a worker, if its connection may have one.

        Returns ``None`` when the connection is already holding its share. That
        is not a failure and nothing is retried on the caller's behalf: the run
        stays **Queued**, which is a true statement about it, and the next
        worker to finish drains it.
        """

        run = self.service.agent_repo.get_run(run_id, owner_id=owner_id)
        if run.exchange_state != "queued":
            return None
        if not self._slot_available(run.connection_id, owner_id=owner_id):
            return None
        return self.exchange_executor.submit(self._work, owner_id, run_id)

    def _slot_available(self, connection_id: str, *, owner_id: str) -> bool:
        held = self.service.agent_repo.open_exchange_count(
            connection_id, owner_id=owner_id
        )
        return held < self.max_exchanges_per_connection

    def _work(self, owner_id: str, run_id: str) -> None:
        """One worker's whole life: run the exchange, then let the queue move."""

        try:
            self.service.perform_exchange(run_id, owner_id=owner_id)
        finally:
            # Even a failed exchange freed a slot, so the drain runs regardless:
            # otherwise one broken agent would strand every hand-off behind it.
            self.drain_queued_exchanges()

    def drain_queued_exchanges(self) -> int:
        """Start as many waiting exchanges as the bounds allow, fairly.

        Owner round robin rather than plain FIFO: one owner with a backlog of
        hand-offs must not be able to push another owner's first one to the back
        of the queue, which is the difference between a slow queue and an
        unusable product for everybody else.
        """

        queued = self.service.agent_repo.queued_exchanges()
        by_owner: dict[str, list[tuple[str, str]]] = {}
        for owner_id, run_id, connection_id in queued:
            by_owner.setdefault(owner_id, []).append((run_id, connection_id))

        started = 0
        while by_owner:
            for owner_id in list(by_owner):
                pending = by_owner[owner_id]
                if not pending:
                    del by_owner[owner_id]
                    continue
                run_id, connection_id = pending.pop(0)
                if self._slot_available(connection_id, owner_id=owner_id):
                    self.exchange_executor.submit(self._work, owner_id, run_id)
                    started += 1
                if not pending:
                    del by_owner[owner_id]
        return started

    # --- restart recovery ---------------------------------------------------

    def recover_interrupted_exchanges(self) -> int:
        """Settle every exchange a restart left mid-flight. Called once, at boot.

        A queued exchange and an open one get opposite treatment, and the whole
        point of keeping the two states apart is that this is decidable at all:

        - **queued** — the worker never started, so nothing left BrainBuddy. The
          run is **Not sent** and the hand-off is offered again with the same
          run ID and message ID. Calling it **Delivery unconfirmed** would ask
          the user to worry about a message that provably does not exist.
        - **open** — the send may already be at the agent. BrainBuddy looks the
          run up by its correlation ID and adopts what it finds; it never
          resends here, because a resend is a send and no send is ever
          initiated without a user action (AC-032).
        """

        recovered = 0
        for owner_id, run_id, state in self.service.agent_repo.interrupted_exchanges():
            if state == "queued":
                self.service.settle_restarted_before_send(run_id, owner_id=owner_id)
            else:
                self.service.recover_open_exchange(run_id, owner_id=owner_id)
            recovered += 1
        return recovered

    # --- the observation lane -----------------------------------------------

    def run_once(self, now: datetime | None = None) -> int:
        """One scheduling pass: every due run, grouped by its connection.

        Grouping is not an optimisation, it is the difference between one
        request to a dead agent and one request per run it holds. When the
        first observation of a group cannot reach the agent, the rest of that
        group are settled as failed contact without asking again — an
        unreachable connection is a fact about the connection, and re-proving
        it per run would multiply the load exactly when the agent is least able
        to take it.

        Returns the number of runs this pass took responsibility for.
        """

        moment = now if now is not None else self._now()
        due = list(self.service.agent_repo.due_observations(now=moment))
        due.extend(self._drain_wakes())

        groups: dict[tuple[str, str], list[str]] = {}
        claimed = 0
        for owner_id, run_id in due:
            if not self._claim(run_id):
                continue
            connection_id = self._connection_of(owner_id, run_id)
            if connection_id is None:
                self._release(run_id)
                continue
            groups.setdefault((owner_id, connection_id), []).append(run_id)
            claimed += 1

        for (owner_id, _connection_id), run_ids in groups.items():
            self.observation_executor.submit(self._observe_group, owner_id, run_ids)
        return claimed

    def wake(self, run_id: str) -> None:
        """The narrow port a verified push calls (FR-008).

        A run id and nothing else: a push may only make BrainBuddy *look*
        sooner, never tell it what it would have seen.
        """

        with self._lock:
            self._woken.add(run_id)
        self._wake_event.set()

    def _drain_wakes(self) -> list[tuple[str, str]]:
        with self._lock:
            woken, self._woken = self._woken, set()
        self._wake_event.clear()
        pairs: list[tuple[str, str]] = []
        for run_id in woken:
            owner_id = self.service.agent_repo.owner_of_run(run_id)
            if owner_id is not None:
                pairs.append((owner_id, run_id))
        return pairs

    def _claim(self, run_id: str) -> bool:
        """Take responsibility for one run, or leave it to whoever has it.

        Coalescing per in-flight run: an observation that is taking a while
        must not have a second one stacked behind it, or a slow agent would
        accumulate one worker per elapsed interval until the pool is gone.
        """

        with self._lock:
            if run_id in self._in_flight:
                return False
            self._in_flight.add(run_id)
            return True

    def _release(self, run_id: str) -> None:
        with self._lock:
            self._in_flight.discard(run_id)

    def _connection_of(self, owner_id: str, run_id: str) -> str | None:
        try:
            return self.service.agent_repo.get_run(
                run_id, owner_id=owner_id
            ).connection_id
        except NotFoundError:  # pragma: no cover - purged between select and read
            return None

    def _observe_group(self, owner_id: str, run_ids: list[str]) -> None:
        """Observe one connection's due runs, stopping at the first silence."""

        unreachable = False
        try:
            for run_id in run_ids:
                if unreachable:
                    self.service.record_failed_contact(run_id, owner_id=owner_id)
                    continue
                unreachable = self._observe(owner_id, run_id) is False
        finally:
            for run_id in run_ids:
                self._release(run_id)

    def _observe(self, owner_id: str, run_id: str) -> bool | None:
        """One authenticated read of one run. ``False`` means "could not reach".

        ``None`` means there was nothing to ask — a suspended or unobservable
        run — which is deliberately not the same as an unreachable agent and
        must not silence the rest of its connection's group.
        """

        try:
            run = self.service.agent_repo.get_run(run_id, owner_id=owner_id)
        except NotFoundError:
            return None
        now = self._now()
        if observation_is_suspended(run, now=now):
            # The reply exchange holds the conversation; observing the
            # predecessor now could lock a run the agent is about to continue
            # in a new task. Bounded: the deadline is the exit (AC-033).
            return None
        result = self.service.read_agent_task(run)
        if result is None:
            return None
        if result.error_code == A2A_TASK_NOT_FOUND:
            self.service.record_task_missing(run_id, owner_id=owner_id)
            return None
        if not result.ok:
            self.service.record_failed_contact(run_id, owner_id=owner_id)
            return False
        self.service.apply_agent_task(
            run, result, trigger=run.observation_trigger_pending or "schedule"
        )
        return True

    # --- the control lane ---------------------------------------------------

    def submit_control(self, call: Callable[[], Any]) -> Future[Any]:
        """Run one short control call on the lane that is never held open.

        A cancel is what *resolves* a blocked exchange on some runtimes, so
        sharing the exchange pool with it would mean waiting out the very hold
        the cancel was meant to end (AC-035).
        """

        assert self.control_executor is not None
        return self.control_executor.submit(call)

    # --- the scheduler thread -----------------------------------------------

    def start(self) -> bool:
        """Start the periodic pass. ``False`` if it is already running.

        Answering rather than raising, because "already started" is what a
        second boot path looks like and starting twice would double every
        observation the deployment makes.
        """

        if self.scheduler_thread is not None and self.scheduler_thread.is_alive():
            return False

        def _loop() -> None:
            interval = self.observation_interval.total_seconds()
            while not self._stop.is_set():
                # Woken early by a push, or on the interval otherwise.
                self._wake_event.wait(interval)
                if self._stop.is_set():
                    break
                try:
                    self.run_once()
                except Exception:  # noqa: BLE001 - one bad pass must not end them
                    logger.exception("Agent observation pass failed")

        self._stop.clear()
        self.scheduler_thread = threading.Thread(
            target=_loop, name="agent-observer", daemon=True
        )
        self.scheduler_thread.start()
        return True

    def shutdown(self) -> None:
        """Stop taking new work; leave the started exchanges alone.

        ``cancel_futures=True`` cancels only what has not begun. An exchange
        already in flight is a message that may be at the agent, and dropping
        it would leave a run nobody will ever settle.
        """

        self._stop.set()
        self._wake_event.set()
        if self.scheduler_thread is not None:
            # The reference is kept rather than cleared: shutdown is also what
            # an operator inspects afterwards, and a thread that would not stop
            # is exactly what they need to be able to see.
            self.scheduler_thread.join(timeout=SCHEDULER_JOIN_SECONDS)
        self.exchange_executor.shutdown(wait=False, cancel_futures=True)
        for pool in (self.observation_executor, self.control_executor):
            if pool is not None and pool is not self.exchange_executor:
                pool.shutdown(wait=False, cancel_futures=True)


__all__ = [
    "DEFAULT_MAX_EXCHANGES_PER_CONNECTION",
    "DEFAULT_OBSERVATION_INTERVAL",
    "SCHEDULER_JOIN_SECONDS",
    "AgentObserver",
    "ExchangePool",
]
