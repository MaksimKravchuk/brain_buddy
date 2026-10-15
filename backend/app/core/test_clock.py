"""The one test clock seam (spec 027 PR-07, contracts/test-control.md).

Black-box suites move server time through ``POST /api/__test__/clock``. Untouched,
the clock is the wall clock, so installing the seam changes nothing observable.
Many services bind ``utcnow`` by name at import, so ``install_clock_seam``
rebinds that name in every loaded ``app`` module (test environment only), and
points the injected ``clock`` fields of the task, sync-retention and mail
services at the same object. Production never imports or installs this.
"""

from __future__ import annotations

import sys
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from app.utils.time import ensure_utc
from app.utils.time import utcnow as _wall_clock

_ORIGINAL = _wall_clock


class TestClock:
    """Wall clock plus an offset, or a pinned instant once ``set`` is called."""

    __test__ = False  # not a pytest class

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pinned: datetime | None = None
        self._offset = timedelta()

    def __call__(self) -> datetime:
        with self._lock:
            if self._pinned is not None:
                return self._pinned
            return datetime.now(tz=UTC) + self._offset

    def advance(self, seconds: float) -> None:
        delta = timedelta(seconds=seconds)
        with self._lock:
            if self._pinned is not None:
                self._pinned = self._pinned + delta
            else:
                self._offset += delta

    def set(self, instant: datetime) -> None:
        with self._lock:
            self._pinned = ensure_utc(instant)

    def reset(self) -> None:
        with self._lock:
            self._pinned = None
            self._offset = timedelta()

    def describe(self) -> dict[str, str]:
        with self._lock:
            mode = (
                "pinned"
                if self._pinned is not None
                else ("offset" if self._offset else "wall")
            )
        return {"mode": mode, "now": self().isoformat().replace("+00:00", "Z")}


CLOCK = TestClock()


def _rebind(target: Any) -> None:
    for name, loaded in list(sys.modules.items()):
        module: Any = loaded
        if (
            module is not None
            and name.startswith("app.")
            and name != __name__
            and getattr(module, "utcnow", None) in (_ORIGINAL, CLOCK)
        ):
            module.utcnow = target


def install_clock_seam(container: Any) -> TestClock:
    """Route every time read of the running process through ``CLOCK``."""

    _rebind(CLOCK)
    container.task_service.clock = CLOCK
    container.sync_retention._clock = CLOCK
    mail = getattr(container.modern_auth_service, "mail", None)
    if mail is not None:
        mail._clock = CLOCK
    return CLOCK


def uninstall_clock_seam() -> None:
    """Restore wall-clock bindings and clear the offset (test teardown)."""

    _rebind(_ORIGINAL)
    CLOCK.reset()
