"""Spec 020 slice PR-02: one injected clock seam for the task module (R21).

``TaskService`` reads time only through the ``clock`` the container injects, so
every time-based review test drives one ``frozen_clock`` instead of patching a
module's ``utcnow`` binding.
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.exceptions import ConflictError
from app.modules.tasks.repository import IDEMPOTENCY_RETENTION
from app.schemas.tasks import TaskCreateRequest
from app.utils.time import from_isoformat, utcnow

from .conftest import FrozenClock

_BACKEND = Path(__file__).resolve().parents[1]
_OWNER = "user_clock_seam"


def test_020_FR_001_container_injects_utcnow_as_task_service_clock(
    container: Container,
) -> None:
    """The container builds TaskService with app.utils.time.utcnow as its clock."""

    assert container.task_service.clock is utcnow


def test_020_FR_001_frozen_clock_drives_created_and_updated_timestamps(
    api_client: TestClient, frozen_clock: FrozenClock
) -> None:
    """A created task carries the frozen instant; a later PATCH the advanced one."""

    created_at = datetime(2026, 9, 24, 9, 14, tzinfo=UTC)
    frozen_clock.set(created_at)
    response = api_client.post(
        "/api/tasks",
        json={"title": "Call Bob", "state": "next"},
        headers={"Idempotency-Key": "seam-create"},
    )
    assert response.status_code == 201, response.text
    task = response.json()
    assert from_isoformat(task["created_at"]) == created_at
    assert from_isoformat(task["updated_at"]) == created_at

    frozen_clock.advance(days=3, minutes=5)
    patched = api_client.patch(
        f"/api/tasks/{task['id']}",
        json={"details": "Ask about the quote", "expected_revision": task["revision"]},
        headers={"Idempotency-Key": "seam-patch"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert from_isoformat(body["created_at"]) == created_at
    assert from_isoformat(body["updated_at"]) == created_at + timedelta(
        days=3, minutes=5
    )


def _create(container: Container, *, key: str, title: str) -> str:
    task = container.task_service.create_task(
        TaskCreateRequest(title=title, state="next"),
        owner_id=_OWNER,
        idempotency_key=key,
    )
    return task.id


def test_020_FR_001_idempotency_purge_keeps_records_until_frozen_retention(
    container: Container, frozen_clock: FrozenClock
) -> None:
    """One second before the retention ends, a reused key still conflicts."""

    _create(container, key="seam-key", title="Call Bob")
    frozen_clock.advance(IDEMPOTENCY_RETENTION - timedelta(seconds=1))
    _create(container, key="seam-other", title="Email Ann")

    assert container.task_repo.get_idempotency(owner_id=_OWNER, key="seam-key")
    with pytest.raises(ConflictError):
        _create(container, key="seam-key", title="Something else")


def test_020_FR_001_idempotency_purge_uses_the_frozen_instant(
    container: Container, frozen_clock: FrozenClock
) -> None:
    """Past the retention by the frozen clock alone, the record is purged."""

    _create(container, key="seam-key", title="Call Bob")
    frozen_clock.advance(IDEMPOTENCY_RETENTION + timedelta(seconds=1))
    _create(container, key="seam-other", title="Email Ann")

    assert container.task_repo.get_idempotency(owner_id=_OWNER, key="seam-key") is None
    replacement = _create(container, key="seam-key", title="Something else")
    assert replacement


def test_020_FR_001_task_service_never_calls_utcnow_directly() -> None:
    """service.py reads time only through the injected clock (no utcnow() call)."""

    source = (_BACKEND / "app" / "modules" / "tasks" / "service.py").read_text(
        encoding="utf-8"
    )
    calls = [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "utcnow"
    ]
    assert calls == []


def test_020_FR_001_no_review_test_patches_a_module_utcnow() -> None:
    """Review tests control time with frozen_clock, never by patching utcnow."""

    patching = re.compile(r"setattr\([^)]*utcnow")
    offenders = [
        path.name
        for path in sorted((_BACKEND / "tests").glob("test_review_*.py"))
        if patching.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
