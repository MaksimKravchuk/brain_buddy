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

import functools
import logging
import threading
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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


class SchedulerOverlapError(RuntimeError):
    """The observer's own scheduler thread and a durable job would both observe."""


class AuthorityLostError(RuntimeError):
    """A durable job lost its lease between a read and the write it would feed."""


#: The authority check of the durable job running on this thread, if any. The
#: legacy scheduler and the request path never set it, so for them the guard
#: installed by `_guard_repo_writes` is a plain pass-through.
_WRITE_AUTHORITY: ContextVar[Callable[[], bool] | None] = ContextVar(
    "agent_write_authority", default=None
)
_GUARDED = "_bb_authority_guarded"


def _assert_authority() -> None:
    check = _WRITE_AUTHORITY.get()
    if check is not None and not check():
        raise AuthorityLostError("The job no longer holds authority for this write.")


@contextmanager
def _write_authority(keep_going: Callable[[], bool] | None) -> Iterator[None]:
    token = _WRITE_AUTHORITY.set(keep_going)
    try:
        yield
    finally:
        _WRITE_AUTHORITY.reset(token)


def _guard_repo_writes(repo: Any) -> None:
    """Make the repository's write entry points re-check a bound job's authority.

    Every relay write funnels through ``command_lock`` (observation, failed
    contact, task-missing, recovery) or the two audit appenders. The check runs
    *inside* the lock, after the write transaction is open, so it cannot be
    overtaken by a reclaimed worker between the check and the commit; raising
    there rolls the transaction back and writes nothing. Idempotent.
    """

    if getattr(repo, _GUARDED, False):
        return
    command_lock = repo.command_lock

    @contextmanager
    def guarded_lock(owner_id: str) -> Iterator[None]:
        with command_lock(owner_id):
            _assert_authority()
            yield

    def guarded(method: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(method)
        def call(*args: Any, **kwargs: Any) -> Any:
            _assert_authority()
            return method(*args, **kwargs)

        return call

    repo.command_lock = guarded_lock
    repo.append_audit = guarded(repo.append_audit)
    repo.append_bounded_audit = guarded(repo.append_bounded_audit)
    setattr(repo, _GUARDED, True)


@dataclass(frozen=True, slots=True)
class ObservationPass:
    """What one synchronous observation pass did.

    ``claimed`` runs were taken from the due list; ``handled`` of them were
    actually read before the pass was told to stop. The rest are left exactly as
    they were -- still due -- so a pass that lost its authority costs time, never
    state.
    """

    claimed: int
    handled: int

    @property
    def complete(self) -> bool:
        return self.handled == self.claimed


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
        # Set once the periodic pass belongs to a durable job: `start` then
        # refuses, so the thread below and the job can never both observe.
        self._scheduling_delegated = False
        #: Told after a verified push queues a wake, so a durable owner of the
        #: periodic pass can make its next occurrence due now.
        self.wake_listener: Callable[[], None] | None = None
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

    def mark_interrupted_exchanges(
        self, *, before_marking: Callable[[str, str], None] | None = None
    ) -> list[tuple[str, str]]:
        """Settle what a restart can settle by itself. Called once, at boot.

        Pure state and no network, which is what makes it safe to run before the
        app serves its first request. A queued exchange and an open one get
        opposite treatment, and the whole point of keeping the two states apart
        is that this is decidable at all:

        - **queued** — the worker never started, so nothing left BrainBuddy. The
          run is **Not sent** and the hand-off is offered again with the same
          run ID and message ID. Calling it **Delivery unconfirmed** would ask
          the user to worry about a message that provably does not exist.
        - **open** — the send may already be at the agent, so the run is marked
          `interrupted`, which is the honest thing to say about it without
          asking anyone. What it *means* still has to be looked up, and that is
          `resolve_interrupted_exchanges`.

        ``before_marking`` is told each open exchange *before* it is marked, so a
        durable follow-up for its lookup can be recorded first: once marked, the
        exchange is no longer listed here and a crash would orphan the lookup.

        Returns the `(owner_id, run_id)` pairs still owing a lookup.
        """

        pending: list[tuple[str, str]] = []
        for owner_id, run_id, state in self.service.agent_repo.interrupted_exchanges():
            if state == "queued":
                self.service.settle_restarted_before_send(run_id, owner_id=owner_id)
            else:
                if before_marking is not None:
                    before_marking(owner_id, run_id)
                self.service.mark_exchange_interrupted(run_id, owner_id=owner_id)
                pending.append((owner_id, run_id))
        return pending

    def resolve_interrupted_exchanges(self, pending: Iterable[tuple[str, str]]) -> int:
        """Look up what the marked exchanges became, on a pool, off the boot path.

        One `ListTasks` per open exchange under the short-call deadline. Doing
        that at boot means an unreachable agent holds the process closed for the
        deadline times the backlog, while the platform's health check gives up
        in five seconds and restarts the machine that is trying to recover — so
        it is submitted after the app is serving instead.

        The control lane by preference: it is the one that is never held open,
        and these calls are short by construction. "No send is ever initiated
        without a user action" is untouched, because the resolver only looks.
        """

        pool = self.control_executor or self.observation_executor
        submitted = 0
        for owner_id, run_id in pending:
            pool.submit(
                self.service.resolve_interrupted_exchange, run_id, owner_id=owner_id
            )
            submitted += 1
        return submitted

    def resolve_interrupted_exchange(
        self,
        owner_id: str,
        run_id: str,
        *,
        keep_going: Callable[[], bool] | None = None,
    ) -> bool:
        """The lookup for one marked exchange, on the caller's own thread.

        The same ``ListTasks`` the pooled resolver makes, for a caller that has to
        know how it ended. ``True`` once the exchange is no longer interrupted
        (the lookup settled it, or the run is gone); ``False`` while the agent
        gave no proof, which is the state the run honestly keeps.

        With ``keep_going``, authority is re-checked after the lookup returns and
        again inside every write it would make; a lookup that finishes without it
        is discarded: `AuthorityLostError` is raised, and any write it would have made
        was refused inside the write transaction.
        """

        if keep_going is not None:
            _guard_repo_writes(self.service.agent_repo)
        with _write_authority(keep_going):
            self.service.resolve_interrupted_exchange(run_id, owner_id=owner_id)
        if keep_going is not None and not keep_going():
            raise AuthorityLostError("The lookup finished after the lease was lost.")
        try:
            run = self.service.agent_repo.get_run(run_id, owner_id=owner_id)
        except NotFoundError:
            return True
        return run.exchange_state != "interrupted"

    def recover_interrupted_exchanges(self) -> int:
        """Both halves of restart recovery, in one synchronous call.

        Kept for callers that want the whole thing to have happened by the time
        it returns. Boot is deliberately not one of them (`main.py`).
        """

        pending = self.mark_interrupted_exchanges()
        for owner_id, run_id in pending:
            self.service.resolve_interrupted_exchange(run_id, owner_id=owner_id)
        return len(pending)

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

        groups = self._claim_due(now if now is not None else self._now())
        for (owner_id, _connection_id), run_ids in groups.items():
            self.observation_executor.submit(self._observe_group, owner_id, run_ids)
        return sum(len(run_ids) for run_ids in groups.values())

    def observe_due(
        self,
        now: datetime | None = None,
        *,
        keep_going: Callable[[], bool] | None = None,
    ) -> ObservationPass:
        """One observation pass that ends before it returns, for a durable job.

        The same selection, claiming and per-run observation as `run_once`, so
        the lookup and retry rules are untouched; what differs is who waits. A
        job must know when its effect has finished, and must stop starting reads
        once its lease is gone, so this runs the groups one after another on the
        caller's thread and asks ``keep_going`` before each read. Whatever it did
        not reach stays due and is woken again for the next pass.

        Refused while this observer's own scheduler thread is alive: that thread
        and a job would observe the same runs twice (`SchedulerOverlapError`).
        """

        if self._scheduler_alive():
            raise SchedulerOverlapError(
                "The observer's own scheduler is running; one owner at a time."
            )
        if keep_going is not None:
            _guard_repo_writes(self.service.agent_repo)
        groups = self._claim_due(now if now is not None else self._now())
        claimed = sum(len(run_ids) for run_ids in groups.values())
        handled = 0
        stopped = False
        for (owner_id, _connection_id), run_ids in groups.items():
            if stopped or (keep_going is not None and not keep_going()):
                stopped = True
                self._requeue_wakes(run_ids)
                for run_id in run_ids:
                    self._release(run_id)
                continue
            done = self._observe_group(owner_id, run_ids, keep_going)
            handled += done
            if done < len(run_ids):
                stopped = True
                self._requeue_wakes(run_ids[done:])
        return ObservationPass(claimed=claimed, handled=handled)

    def _claim_due(self, moment: datetime) -> dict[tuple[str, str], list[str]]:
        due = list(self.service.agent_repo.due_observations(now=moment))
        due.extend(self._drain_wakes())

        groups: dict[tuple[str, str], list[str]] = {}
        for owner_id, run_id in due:
            if not self._claim(run_id):
                continue
            connection_id = self._connection_of(owner_id, run_id)
            if connection_id is None:
                self._release(run_id)
                continue
            groups.setdefault((owner_id, connection_id), []).append(run_id)
        return groups

    def _requeue_wakes(self, run_ids: Iterable[str]) -> None:
        with self._lock:
            self._woken.update(run_ids)

    def wake(self, run_id: str) -> None:
        """The narrow port a verified push calls (FR-008).

        A run id and nothing else: a push may only make BrainBuddy *look*
        sooner, never tell it what it would have seen.
        """

        with self._lock:
            self._woken.add(run_id)
        self._wake_event.set()
        if self.wake_listener is not None:
            self.wake_listener()

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

    def _observe_group(
        self,
        owner_id: str,
        run_ids: list[str],
        keep_going: Callable[[], bool] | None = None,
    ) -> int:
        """Observe one connection's due runs, stopping at the first silence.

        Returns how many runs it got through; fewer than all only when
        ``keep_going`` said stop, and then the rest are untouched. It is asked
        before each read and again inside the write the read would feed, so a
        lease lost during the network call discards that result: the run is
        neither updated nor counted, and stays due for the next pass.
        """

        unreachable = False
        handled = 0
        try:
            with _write_authority(keep_going):
                for run_id in run_ids:
                    if keep_going is not None and not keep_going():
                        break
                    if unreachable:
                        self.service.record_failed_contact(run_id, owner_id=owner_id)
                    else:
                        unreachable = self._observe(owner_id, run_id) is False
                    handled += 1
        except AuthorityLostError:
            logger.warning("Agent observation discarded: job authority lost")
        finally:
            for run_id in run_ids:
                self._release(run_id)
        return handled

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

    def _scheduler_alive(self) -> bool:
        return self.scheduler_thread is not None and self.scheduler_thread.is_alive()

    def delegate_scheduling(self) -> None:
        """Hand the periodic pass to a durable job, for good.

        After this `start` never starts the thread, so exactly one mechanism
        observes. Refused while the thread is already running: the caller must
        stop it first, because a handoff that overlapped would double-observe.
        """

        if self._scheduler_alive():
            raise SchedulerOverlapError(
                "The observer's own scheduler is running; stop it before handing over."
            )
        self._scheduling_delegated = True

    def start(self) -> bool:
        """Start the periodic pass. ``False`` if it is already running.

        Answering rather than raising, because "already started" is what a
        second boot path looks like and starting twice would double every
        observation the deployment makes.
        """

        if self._scheduler_alive():
            return False
        if self._scheduling_delegated:
            logger.warning("Agent observer scheduler not started: owned by a job")
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
    "AuthorityLostError",
    "ExchangePool",
    "ObservationPass",
    "SchedulerOverlapError",
]
