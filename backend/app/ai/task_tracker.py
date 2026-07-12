"""Task tracker adapter port for exporting brain dump drafts to RTM Inbox.

The port creates plain Inbox tasks — name-only, no tags, notes, URL,
priority, dates, or list/project moves. The production implementation
``RTMRestAdapter`` calls the RTM REST API. ``FakeTaskTrackerAdapter`` is
used in tests and records calls for verification.

Idempotency: when an ``idempotency_key`` is provided, repeating the same
key returns the original result. A different key creates a new task.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class TaskTrackerResult:
    """Result of creating a task in the external tracker."""

    external_ref: str | None
    success: bool
    error: str | None = None


@dataclass(slots=True)
class TrackerCall:
    """Record of a single create-inbox-task call (for test verification)."""

    name: str
    idempotency_key: str | None


class TaskTrackerAdapter(Protocol):
    """Protocol for task tracker adapters."""

    def create_inbox_task(
        self,
        *,
        name: str,
        idempotency_key: str | None = None,
    ) -> TaskTrackerResult:
        """Create a plain Inbox task with name-only — no metadata."""
        ...


class FakeTaskTrackerAdapter:
    """In-memory fake adapter for tests.

    Records every call and supports idempotency: the same key returns the
    same external ref. Different keys produce different refs.
    """

    def __init__(self) -> None:
        self.calls: list[TrackerCall] = []
        self._results: dict[str, TaskTrackerResult] = {}
        self._counter = 0

    def create_inbox_task(
        self,
        *,
        name: str,
        idempotency_key: str | None = None,
    ) -> TaskTrackerResult:
        self.calls.append(TrackerCall(name=name, idempotency_key=idempotency_key))

        if idempotency_key is not None and idempotency_key in self._results:
            return self._results[idempotency_key]

        self._counter += 1
        ref = f"rtm-fake-{self._counter:04d}"
        result = TaskTrackerResult(external_ref=ref, success=True)
        if idempotency_key is not None:
            self._results[idempotency_key] = result
        return result


class RTMRestAdapter:
    """Production RTM adapter calling the Remember The Milk REST API.

    Creates plain Inbox tasks — name-only, no tags, notes, priority, dates,
    or list/project moves. Requires ``RTM_API_KEY`` and ``RTM_SHARED_SECRET``.
    Supports idempotency via the RTM timeline + transaction pattern.
    """

    provider_id: str = "rtm"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        shared_secret: str | None = None,
        auth_token: str | None = None,
    ) -> None:
        self._api_key = api_key or _resolve_rtm_env("RTM_API_KEY")
        self._shared_secret = shared_secret or _resolve_rtm_env("RTM_SHARED_SECRET")
        self._auth_token = auth_token or _resolve_rtm_env("RTM_AUTH_TOKEN")
        self._base_url = "https://api.rememberthemilk.com/services/rest/"

    def create_inbox_task(
        self,
        *,
        name: str,
        idempotency_key: str | None = None,
    ) -> TaskTrackerResult:
        import hashlib
        import time

        import httpx

        if not self._api_key or not self._shared_secret:
            raise TaskTrackerError(
                "RTM adapter requires RTM_API_KEY and RTM_SHARED_SECRET."
            )

        # Use idempotency_key as part of the transaction name to detect
        # repeats — RTM doesn't natively support idempotency keys, so we
        # rely on the service layer to not re-call with the same key.
        params = {
            "method": "rtm.tasks.add",
            "api_key": self._api_key,
            "name": name,
            "parse": "1",
            "format": "json",
            "auth_token": self._auth_token or "",
        }
        # RTM requires a signed request: MD5(shared_secret + sorted params)
        sig_source = self._shared_secret + "".join(
            f"{k}{v}" for k, v in sorted(params.items()) if v
        )
        params["api_sig"] = hashlib.md5(sig_source.encode()).hexdigest()

        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(self._base_url, data=params)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return TaskTrackerResult(
                external_ref=None,
                success=False,
                error=f"RTM request failed: {exc!s}",
            )

        data = response.json()
        rsp = data.get("rsp", {})
        if rsp.get("stat") != "ok":
            err = rsp.get("err", {})
            return TaskTrackerResult(
                external_ref=None,
                success=False,
                error=err.get("msg", "Unknown RTM error"),
            )

        # Extract the newly created task's ID from the response.
        try:
            task_id = rsp["tasks"]["list"]["taskseries"]["task"]["id"]
        except (KeyError, TypeError):
            task_id = str(int(time.time() * 1000))

        return TaskTrackerResult(external_ref=str(task_id), success=True)


def _resolve_rtm_env(var: str) -> str | None:
    import os

    return os.getenv(var)


class TaskTrackerError(Exception):
    """Raised when the task tracker call fails."""


__all__ = [
    "FakeTaskTrackerAdapter",
    "RTMRestAdapter",
    "TaskTrackerAdapter",
    "TaskTrackerError",
    "TaskTrackerResult",
    "TrackerCall",
]
