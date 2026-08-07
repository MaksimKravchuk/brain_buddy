"""Very small in-memory per-key rate limiter.

Used by `/auth/login` (per source IP) and the sensitive account actions
(per user id). Intentionally simple:

- Per-key (source IP) sliding window.
- In-memory — loses state on restart.
- Not concurrency-safe across multiple workers; for this scale that's fine.
  A persistent / cross-process limiter is listed as a follow-up in the auth
  design doc.

Do not use this for anything else without thinking about the tradeoffs.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class InMemoryRateLimiter:
    """Sliding-window limiter: at most `max_attempts` per `window_seconds`."""

    def __init__(self, *, max_attempts: int, window_seconds: float) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> bool:
        """Record an attempt for `key`. Return True if allowed, False if over limit."""

        now = time.monotonic()
        cutoff = now - self._window
        bucket = self._hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._max:
            return False
        bucket.append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        """Reset a single key or the entire store (used by tests)."""

        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


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


__all__ = [
    "InMemoryRateLimiter",
    "LOGIN_MAX_ATTEMPTS",
    "LOGIN_WINDOW_SECONDS",
    "SENSITIVE_ACTION_MAX_ATTEMPTS",
    "SENSITIVE_ACTION_WINDOW_SECONDS",
    "login_rate_limiter",
    "sensitive_action_rate_limiter",
]
