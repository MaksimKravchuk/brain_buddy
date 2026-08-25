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
from collections import defaultdict, deque
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
    "InMemoryRateLimiter",
    "LOGIN_MAX_ATTEMPTS",
    "LOGIN_WINDOW_SECONDS",
    "SENSITIVE_ACTION_MAX_ATTEMPTS",
    "SENSITIVE_ACTION_WINDOW_SECONDS",
    "login_rate_limiter",
    "sensitive_action_rate_limiter",
    "title_completion_rate_limiter",
]
