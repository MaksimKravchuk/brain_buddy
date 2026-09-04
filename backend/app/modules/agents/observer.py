"""The exchange lane: who gets a worker, when, and what a restart owes them.

The service knows what one exchange *means*; this knows how many may run at
once and in whose order. Keeping the two apart is what lets the wire rules be
tested without threads and the concurrency rules without a socket.

Scheduling, the observation and control pools and the wake port arrive with
User Story 3; this module is deliberately only the exchange half.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from app.utils.time import utcnow

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .service import AgentRelayService

#: Exchange workers one connection may hold at once, when the caller says
#: nothing. Mirrors ``AgentRelaySettings.max_exchanges_per_connection``.
DEFAULT_MAX_EXCHANGES_PER_CONNECTION = 2


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
        clock: Callable[[], datetime] = utcnow,
        probe_delay: float = 0.0,
        max_exchanges_per_connection: int = DEFAULT_MAX_EXCHANGES_PER_CONNECTION,
    ) -> None:
        self.service = service
        self.exchange_executor = exchange_executor
        self.max_exchanges_per_connection = max_exchanges_per_connection
        self._now = clock
        self.probe_delay = probe_delay
        # The service submits through here, so the bound below is not something
        # a dispatch can route around.
        service.exchange_pump = self.submit_exchange

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
          resends here, because no background thread ever resends (AC-032).
        """

        recovered = 0
        for owner_id, run_id, state in self.service.agent_repo.interrupted_exchanges():
            if state == "queued":
                self.service.settle_restarted_before_send(run_id, owner_id=owner_id)
            else:
                self.service.recover_open_exchange(run_id, owner_id=owner_id)
            recovered += 1
        return recovered

    # --- lifecycle ----------------------------------------------------------

    def shutdown(self) -> None:
        """Stop taking new exchanges; leave the started ones alone.

        ``cancel_futures=True`` cancels only what has not begun. An exchange
        already in flight is a message that may be at the agent, and dropping it
        would leave a run nobody will ever settle.
        """

        self.exchange_executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["DEFAULT_MAX_EXCHANGES_PER_CONNECTION", "AgentObserver", "ExchangePool"]
