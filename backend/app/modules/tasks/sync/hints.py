"""Content-free SSE wake-ups for committed scope changes (spec 026 PR-58).

Contract: ``specs/026-rust-core-sync/contracts/sync-v1.md`` section 11, "Foreground
SSE hints". A hint only asks an authorized client to pull; it carries no task
content, command ID or cursor, and there is no replay history.

Publication reads the *committed* per-scope sequence from the shared SQLite file
(``sync_scopes.commit_seq``) at most ``poll`` seconds apart while a scope has a
listener. Because it reads the database, a commit from another worker, process or
legacy writer is seen without any in-process callback or broker, and a rollback
never moves the counter. One watcher serves every connection of a scope in this
process, but each connection re-runs its own admission on every pass: sharing the
watcher shares no authentication. Each connection holds one wake flag, so any
number of commits between two passes coalesces to one event and nothing queues.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)

POLL_SECONDS = 0.25
HEARTBEAT_SECONDS = 15.0
MAX_AGE_SECONDS = 15 * 60.0
HEARTBEAT = b": keep-alive\n\n"
# Neither the server nor a proxy may hold events until the stream closes.
STREAM_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


class Generations(NamedTuple):
    """The server-minted identity of a scope; any change closes open streams."""

    server: str
    feed: str
    access: str
    storage: str


# Per connection: the current generations, or ``None`` once it may no longer be served.
Admission = Callable[[], Generations | None]
# Shared: the committed sequence of a scope, ``None`` while it has no scope row.
Counter = Callable[[str], str | None]


class SqliteCommitCounter:
    """The committed scope sequence, read through a short-lived connection."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def __call__(self, scope_id: str) -> str | None:
        with closing(sqlite3.connect(self._db_path, timeout=5)) as conn:
            row = conn.execute(
                "SELECT commit_seq FROM sync_scopes WHERE owner_id = ?", (scope_id,)
            ).fetchone()
        return None if row is None else str(row[0])


@dataclass(eq=False, slots=True)
class _Listener:
    admission: Admission
    opened: Generations
    delivered: str | None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    closed: bool = False

    def close(self) -> None:
        self.closed = True
        self.wake.set()


@dataclass(eq=False, slots=True)
class _Watcher:
    listeners: set[_Listener] = field(default_factory=set)
    task: asyncio.Task[None] | None = None


class HintHub:
    """Per-process fan-out of committed-change wake-ups; one watcher per scope."""

    def __init__(  # noqa: PLR0913 - the three bounds are injected for tests
        self,
        counter: Counter,
        now: Callable[[], datetime],
        *,
        poll: float = POLL_SECONDS,
        heartbeat: float = HEARTBEAT_SECONDS,
        max_age: float = MAX_AGE_SECONDS,
    ) -> None:
        self._counter = counter
        self._now = now
        self._poll, self._heartbeat, self._max_age = poll, heartbeat, max_age
        self._watchers: dict[str, _Watcher] = {}

    @property
    def watched_scopes(self) -> int:
        return len(self._watchers)

    def close(self) -> None:
        """End every open stream (application shutdown)."""
        for watcher in self._watchers.values():
            for listener in watcher.listeners:
                listener.close()

    def _event(
        self, scope_id: str, generations: Generations, correlation: str
    ) -> bytes:
        data = {
            "scope_id": scope_id,
            "server_generation": generations.server,
            "feed_generation": generations.feed,
            "server_now": self._now().isoformat(),
            "correlation_id": correlation,
        }
        body = json.dumps(data, separators=(",", ":"))
        return f"event: scope_changed\ndata: {body}\n\n".encode()

    async def stream(
        self, scope_id: str, admission: Admission, correlation_id: str
    ) -> AsyncIterator[bytes]:
        """SSE frames for one connection until it is closed, revoked or too old."""
        opened = await asyncio.to_thread(admission)
        if opened is None:
            return
        # The baseline precedes the initial event, so a commit after it is a
        # later event and none can fall between subscribing and the first pull.
        baseline = await asyncio.to_thread(self._counter, scope_id)
        listener = _Listener(admission, opened, baseline)
        self._attach(scope_id, listener)
        try:
            yield self._event(scope_id, opened, correlation_id)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._max_age
            while not listener.closed and (remaining := deadline - loop.time()) > 0:
                try:
                    await asyncio.wait_for(
                        listener.wake.wait(), min(self._heartbeat, remaining)
                    )
                except TimeoutError:
                    yield HEARTBEAT
                    continue
                if listener.closed:
                    break
                listener.wake.clear()
                yield self._event(scope_id, opened, correlation_id)
        finally:
            self._detach(scope_id, listener)

    def _attach(self, scope_id: str, listener: _Listener) -> None:
        watcher = self._watchers.get(scope_id)
        if watcher is None:
            watcher = self._watchers[scope_id] = _Watcher()
            watcher.task = asyncio.create_task(self._watch(scope_id, watcher))
        watcher.listeners.add(listener)

    def _detach(self, scope_id: str, listener: _Listener) -> None:
        watcher = self._watchers.get(scope_id)
        if watcher is not None:
            watcher.listeners.discard(listener)

    async def _watch(self, scope_id: str, watcher: _Watcher) -> None:
        # The emptiness check and the removal share no await, so a listener that
        # attaches always finds a live watcher or starts its own.
        while watcher.listeners:
            await asyncio.sleep(self._poll)
            listeners = list(watcher.listeners)
            try:
                sequence = await asyncio.to_thread(self._counter, scope_id)
                current = await asyncio.gather(
                    *(asyncio.to_thread(item.admission) for item in listeners)
                )
            except Exception:
                # Fail closed: clients reconnect under fresh authorization.
                logger.warning("sync_hint_watch_failed", exc_info=True)
                for item in listeners:
                    item.close()
                break
            for item, generations in zip(listeners, current, strict=True):
                if generations != item.opened:
                    item.close()
                elif sequence != item.delivered:
                    item.delivered = sequence
                    item.wake.set()
        if self._watchers.get(scope_id) is watcher:
            del self._watchers[scope_id]
