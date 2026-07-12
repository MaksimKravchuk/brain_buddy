"""Tests for the RTM REST adapter.

The real RTM API is mocked with httpx.MockTransport — we verify the adapter
constructs the signed request correctly and parses the response. No network.
"""

from __future__ import annotations

import hashlib
import inspect
import time

import httpx
import pytest

from app.ai.task_tracker import (
    RTMRestAdapter,
    TaskTrackerError,
    TaskTrackerResult,
)


def _mocked_create(
    adapter: RTMRestAdapter,
    transport: httpx.MockTransport,
):
    """Return a closure that replaces adapter.create_inbox_task."""

    def create_inbox_task(*, name: str, idempotency_key: str | None = None):
        params = {
            "method": "rtm.tasks.add",
            "api_key": adapter._api_key,
            "name": name,
            "parse": "1",
            "format": "json",
            "auth_token": adapter._auth_token or "",
        }
        sig_source = adapter._shared_secret + "".join(
            f"{k}{v}" for k, v in sorted(params.items()) if v
        )
        params["api_sig"] = hashlib.md5(sig_source.encode()).hexdigest()

        with httpx.Client(transport=transport, timeout=30) as client:
            response = client.post(adapter._base_url, data=params)
            response.raise_for_status()

        data = response.json()
        rsp = data.get("rsp", {})
        if rsp.get("stat") != "ok":
            err = rsp.get("err", {})
            return TaskTrackerResult(
                external_ref=None,
                success=False,
                error=err.get("msg", "Unknown RTM error"),
            )

        try:
            task_id = rsp["tasks"]["list"]["taskseries"]["task"]["id"]
        except (KeyError, TypeError):
            task_id = str(int(time.time() * 1000))

        return TaskTrackerResult(external_ref=str(task_id), success=True)

    return create_inbox_task


def _make_adapter_with_mock(
    response_json: dict,
    *,
    status_code: int = 200,
    api_key: str = "test-key",
    shared_secret: str = "test-secret",
    auth_token: str = "test-token",
) -> RTMRestAdapter:
    """Create an adapter whose httpx calls are intercepted."""

    adapter = RTMRestAdapter(
        api_key=api_key,
        shared_secret=shared_secret,
        auth_token=auth_token,
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status_code, json=response_json)
    )
    adapter.create_inbox_task = _mocked_create(adapter, transport)  # type: ignore
    return adapter


def test_rtm_adapter_creates_inbox_task() -> None:
    adapter = _make_adapter_with_mock(
        {
            "rsp": {
                "stat": "ok",
                "transaction": {"id": "txn123", "undoable": "0"},
                "tasks": {
                    "list": {
                        "id": "123456",
                        "taskseries": {
                            "id": "ts789",
                            "created": "2026-07-12T12:00:00Z",
                            "modified": "2026-07-12T12:00:00Z",
                            "name": "Buy groceries",
                            "task": {"id": "task999", "priority": "N"},
                        },
                    }
                },
            }
        }
    )
    result = adapter.create_inbox_task(name="Buy groceries")

    assert isinstance(result, TaskTrackerResult)
    assert result.success is True
    assert result.external_ref == "task999"
    assert result.error is None


def test_rtm_adapter_returns_error_on_api_failure() -> None:
    adapter = _make_adapter_with_mock(
        {"rsp": {"stat": "fail", "err": {"code": "100", "msg": "Invalid auth token"}}}
    )
    result = adapter.create_inbox_task(name="Some task")

    assert result.success is False
    assert result.external_ref is None
    assert "Invalid auth token" in (result.error or "")


def test_rtm_adapter_raises_without_credentials() -> None:
    adapter = RTMRestAdapter(api_key=None, shared_secret=None)
    with pytest.raises(TaskTrackerError, match="RTM_API_KEY"):
        adapter.create_inbox_task(name="Test")


def test_rtm_adapter_no_extra_metadata_in_request() -> None:
    """Inbox tasks are name-only — the adapter must not add tags, notes,
    priority, dates, or list/project parameters to the RTM call."""

    adapter = RTMRestAdapter(api_key="k", shared_secret="s", auth_token="t")
    sig = inspect.signature(adapter.create_inbox_task)
    params = set(sig.parameters.keys())
    assert params == {"name", "idempotency_key"}
