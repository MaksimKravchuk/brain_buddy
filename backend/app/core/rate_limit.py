"""Very small in-memory per-key rate limiter.

Used by `/auth/login` (per source IP) and the sensitive account actions
(per user id). Intentionally simple:

- Per-key (source IP) sliding window.
- In-memory — loses state on restart.
- Thread-safe within a process; a persistent / cross-process limiter is listed
  as a follow-up in the auth design doc.

Do not use this for anything else without thinking about the tradeoffs.
"""

from __future__ import annotations

import time
from collections import OrderedDict, defaultdict, deque
from threading import Lock


class InMemoryRateLimiter:
    """Sliding-window limiter: at most `max_attempts` per `window_seconds`."""

    def __init__(self, *, max_attempts: int, window_seconds: float) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._reservations: dict[str, dict[int, float]] = defaultdict(dict)
        self._next_reservation = 0
        self._lock = Lock()

    def _prune(self, key: str, cutoff: float) -> deque[float]:
        bucket = self._hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        reservations = self._reservations[key]
        for token, timestamp in list(reservations.items()):
            if timestamp < cutoff:
                del reservations[token]
        return bucket

    def _new_reservation(self, key: str, now: float) -> int:
        self._next_reservation += 1
        token = self._next_reservation
        self._reservations[key][token] = now
        return token

    def check(self, key: str) -> bool:
        """Record an attempt for `key`. Return True if allowed, False if over limit."""

        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now - self._window)
            if len(bucket) + len(self._reservations[key]) >= self._max:
                return False
            bucket.append(now)
            return True

    def is_allowed(self, key: str) -> bool:
        """Return whether a key is below the limit without recording an attempt."""

        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now - self._window)
            return len(bucket) + len(self._reservations[key]) < self._max

    def record(self, key: str, reservation: int | None = None) -> bool:
        """Record a failed attempt, optionally settling a reservation."""

        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now - self._window)
            if reservation is not None:
                if reservation not in self._reservations[key]:
                    return False
                del self._reservations[key][reservation]
                bucket.append(now)
                return True
            if len(bucket) + len(self._reservations[key]) >= self._max:
                return False
            bucket.append(now)
            return True

    def reserve(self, key: str) -> int | None:
        """Atomically admit an attempt and return its settlement token."""

        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now - self._window)
            if len(bucket) + len(self._reservations[key]) >= self._max:
                return None
            return self._new_reservation(key, now)

    def release(self, key: str, reservation: int) -> bool:
        """Release one admitted attempt without changing failed-attempt history."""

        with self._lock:
            return self._reservations[key].pop(reservation, None) is not None

    def reset(self, key: str | None = None) -> None:
        """Reset a single key or the entire store (used by tests)."""

        with self._lock:
            if key is None:
                self._hits.clear()
                self._reservations.clear()
            else:
                self._hits.pop(key, None)
                self._reservations.pop(key, None)


class BoundedKeyRateLimiter:
    """A sliding-window limiter that also forgets keys (spec 014, FR-008).

    ``InMemoryRateLimiter`` above never forgets a key: its buckets are
    ``defaultdict``s and ``_prune`` only trims timestamps *inside* a key. Keyed
    by source IP on a login route that is a considered trade. Keyed by a
    caller-supplied run id on the A2A push callback — a route anyone who guesses
    the URL shape can reach — it is a remote memory-growth primitive, so this
    variant exists rather than a change to the class those routes share.

    Two bounds, and the second matters as much as the first:

    * ``max_keys`` caps how many buckets exist at once. At the cap the
      least-recently-used key is displaced rather than the new one refused:
      refusing at the cap would let a flood of stale ids deny push acceleration
      to every legitimate run, making the limiter the outage it prevents.
    * ``evict`` drops a key outright, which the route calls when a run goes
      terminal or its connection is disconnected. Such a run can never be
      pushed for again, so keeping its bucket retains something with no use.

    Displacement is not a bypass: the caller only evicts a key it will never
    honour again, and a displaced key starts a fresh window under a cap the
    attacker does not control.
    """

    def __init__(
        self, *, max_attempts: int, window_seconds: float, max_keys: int
    ) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._max_keys = max_keys
        # Insertion-ordered, and re-inserted on touch, so the first key is the
        # least recently used one.
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    @property
    def key_count(self) -> int:
        """How many buckets are currently held. Bounded by ``max_keys``."""

        with self._lock:
            return len(self._hits)

    def check(self, key: str) -> bool:
        """Record an attempt for ``key``; ``True`` when it is within the limit."""

        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                bucket = deque()
                self._hits[key] = bucket
            else:
                self._hits.move_to_end(key)
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            while len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)
            if len(bucket) >= self._max:
                return False
            bucket.append(now)
            return True

    def evict(self, key: str) -> bool:
        """Forget one key. ``True`` when it existed."""

        with self._lock:
            return self._hits.pop(key, None) is not None

    def reset(self) -> None:
        """Drop every bucket (used by tests)."""

        with self._lock:
            self._hits.clear()


class FixedWindowCounter:
    """A process-wide event counter with no per-key state at all.

    Step 2 of the push-callback check order: consulted **before** any database
    read, so a flood costs one integer comparison rather than a lookup per
    request. It deliberately cannot be keyed — a per-caller or per-id counter
    here would reintroduce exactly the unbounded growth
    :class:`BoundedKeyRateLimiter` exists to cap, and rejections of *unknown*
    ids are counted only in aggregate, for alerting.
    """

    def __init__(self, *, max_events: int, window_seconds: float) -> None:
        self._max = max_events
        self._window = window_seconds
        self._window_started = time.monotonic()
        self._count = 0
        self._rejected = 0
        self._lock = Lock()

    @property
    def rejected(self) -> int:
        """How many events this counter has refused since process start."""

        with self._lock:
            return self._rejected

    def check(self) -> bool:
        """Record one event; ``True`` when it is within the window's budget."""

        now = time.monotonic()
        with self._lock:
            if now - self._window_started >= self._window:
                self._window_started = now
                self._count = 0
            if self._count >= self._max:
                self._rejected += 1
                return False
            self._count += 1
            return True

    def reset(self) -> None:
        with self._lock:
            self._window_started = time.monotonic()
            self._count = 0
            self._rejected = 0


LOGIN_MAX_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 10 * 60

login_rate_limiter = InMemoryRateLimiter(
    max_attempts=LOGIN_MAX_ATTEMPTS,
    window_seconds=LOGIN_WINDOW_SECONDS,
)

SENSITIVE_ACTION_MAX_ATTEMPTS = 10
SENSITIVE_ACTION_WINDOW_SECONDS = 10 * 60

# Guards the password-re-auth account endpoints (email/password change,
# deletion request). Keyed by user id — the caller already holds a valid
# session, so the identity to slow down is the account, not the source IP.
sensitive_action_rate_limiter = InMemoryRateLimiter(
    max_attempts=SENSITIVE_ACTION_MAX_ATTEMPTS,
    window_seconds=SENSITIVE_ACTION_WINDOW_SECONDS,
)

TITLE_COMPLETION_MAX_ATTEMPTS = 20
TITLE_COMPLETION_WINDOW_SECONDS = 60
title_completion_rate_limiter = InMemoryRateLimiter(
    max_attempts=TITLE_COMPLETION_MAX_ATTEMPTS,
    window_seconds=TITLE_COMPLETION_WINDOW_SECONDS,
)


__all__ = [
    "BoundedKeyRateLimiter",
    "FixedWindowCounter",
    "InMemoryRateLimiter",
    "LOGIN_MAX_ATTEMPTS",
    "LOGIN_WINDOW_SECONDS",
    "SENSITIVE_ACTION_MAX_ATTEMPTS",
    "SENSITIVE_ACTION_WINDOW_SECONDS",
    "login_rate_limiter",
    "sensitive_action_rate_limiter",
    "title_completion_rate_limiter",
]
