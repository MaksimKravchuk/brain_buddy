"""Spec 020 (FR-044): review logs hold ids, codes, counts and timings only.

Decisions, undo, settings, the explainer acknowledgement, a device auto-park
and the sweep run with sentinel strings in title, notes, waiting-for and the
extension reason and with stall reasons set; no captured log record may hold a
sentinel or a stall-reason value. A content-bearing client id is refused with
422 before it can reach a log, and the sweep over an invalid task payload logs
only the exception type and a reason code (contracts/http.md "Logs", §9).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import timedelta
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.container import Container

from .conftest import FrozenClock


def _run_review_maintenance_sweep(container: Container) -> Any:
    """One sweep run, as if the 60 s loop had kept running (no gap floor)."""

    repo = container.task_repo
    just_now = container.task_service.clock() - timedelta(minutes=1)
    for settings in repo.list_review_settings():
        if settings.activated_at is not None:
            repo.save_review_settings(
                settings.model_copy(update={"last_effective_sweep_at": just_now})
            )
    return app_main._run_review_maintenance_sweep(container)


TITLE = "SENTINEL-TITLE-q7Zr"
NOTES = "SENTINEL-NOTES-k2Vw"
WAITING_FOR = "SENTINEL-WAITING-p9Lm"
REASON = "SENTINEL-REASON-x4Tb"
ID_TEXT = "SENTINEL-IDTEXT-h8Qc"
PAYLOAD_TEXT = "SENTINEL-PAYLOAD-n3Je"
SENTINELS = (TITLE, NOTES, WAITING_FOR, REASON, ID_TEXT, PAYLOAD_TEXT)
STALL_REASONS = (
    "unclear",
    "too_big",
    "missing_info",
    "waiting_on_someone",
    "no_energy",
    "no_longer_matters",
)


def _container(client: TestClient) -> Container:
    return client.app.state.container  # type: ignore[attr-defined]


class _Keys:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> dict[str, str]:
        self.count += 1
        return {"Idempotency-Key": f"privacy-{self.count}"}


def _ok(response: Any, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    return response.json() if response.content else {}


def _assert_clean(caplog: pytest.LogCaptureFixture) -> None:
    texts = [caplog.text]
    for record in caplog.records:
        texts.append(record.getMessage())
        if record.exc_text:
            texts.append(record.exc_text)
    blob = "\n".join(texts)
    for sentinel in SENTINELS:
        assert sentinel not in blob, sentinel
    for code in STALL_REASONS:
        assert code not in blob, code


def test_020_FR_044_review_commands_and_sweep_log_no_content_or_stall_reason(
    api_client: TestClient,
    frozen_clock: FrozenClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every review path runs with sentinels; none reaches a log record."""

    keys = _Keys()
    container = _container(api_client)
    container.feature_flag_service.set_mode(
        "weekly_review", "on", operator_id="test-operator"
    )
    caplog.set_level(logging.DEBUG)

    with allure.step("Activate and create sentinel-bearing Next tasks"):
        _ok(
            api_client.post(
                "/api/review/explainer/acknowledge",
                json={"time_zone": "Europe/Berlin"},
                headers=keys(),
            )
        )
        tasks = [
            _ok(
                api_client.post(
                    "/api/tasks",
                    json={"title": f"{TITLE} {n}", "details": NOTES, "state": "next"},
                    headers=keys(),
                ),
                201,
            )
            for n in range(3)
        ]
        frozen_clock.advance(days=15)

    with allure.step("Decide extend and waiting with stall reasons, then undo"):
        extend = _ok(
            api_client.post(
                f"/api/tasks/{tasks[0]['id']}/decisions",
                json={
                    "type": "extend",
                    "expected_revision": tasks[0]["revision"],
                    "formulation_id": tasks[0]["formulation"]["id"],
                    "reason": REASON,
                    "stall_reason": "too_big",
                },
                headers=keys(),
            )
        )
        assert extend["decision"]["type"] == "extend"
        waiting = _ok(
            api_client.post(
                f"/api/tasks/{tasks[1]['id']}/decisions",
                json={
                    "type": "waiting",
                    "expected_revision": tasks[1]["revision"],
                    "formulation_id": tasks[1]["formulation"]["id"],
                    "waiting_for": WAITING_FOR,
                    "stall_reason": "no_energy",
                },
                headers=keys(),
            )
        )
        _ok(
            api_client.post(
                f"/api/review/decisions/{waiting['decision']['id']}/undo",
                json={"expected_task_revision": waiting["task"]["revision"]},
                headers=keys(),
            )
        )

    with allure.step("Settings, device auto-park and a content-bearing id"):
        _ok(
            api_client.put(
                "/api/review/settings",
                # The activating acknowledgement made revision 2.
                json={"threshold_days": 21, "expected_revision": 2},
                headers=keys(),
            )
        )
        _ok(
            api_client.post(
                f"/api/tasks/{tasks[2]['id']}/auto-park",
                json={"formulation_id": tasks[2]["formulation"]["id"]},
                headers=keys(),
            )
        )
        refused = api_client.post(
            f"/api/tasks/{tasks[2]['id']}/decisions",
            json={
                "decision_id": f"decision_{ID_TEXT}",
                "type": "complete",
                "expected_revision": tasks[2]["revision"],
            },
            headers=keys(),
        )
        assert refused.status_code == 422
        assert ID_TEXT not in refused.text

    with allure.step("The sweep parks a due task"):
        frozen_clock.advance(days=40)
        _run_review_maintenance_sweep(container)
        assert any("review_auto_park" in r.getMessage() for r in caplog.records)

    _assert_clean(caplog)


def test_020_FR_044_sweep_over_an_invalid_payload_logs_only_the_exception_type(
    api_client: TestClient,
    frozen_clock: FrozenClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A broken task payload fails its owner's pass; the log names the type."""

    keys = _Keys()
    container = _container(api_client)
    container.feature_flag_service.set_mode(
        "weekly_review", "on", operator_id="test-operator"
    )
    _ok(api_client.post("/api/review/explainer/acknowledge", json={}, headers=keys()))
    task = _ok(
        api_client.post(
            "/api/tasks", json={"title": "Call Bob", "state": "next"}, headers=keys()
        ),
        201,
    )
    with sqlite3.connect(container.task_repo.db_path) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload FROM tasks WHERE id = ?", (task["id"],)
            ).fetchone()[0]
        )
        payload["title"] = PAYLOAD_TEXT * 40  # over the 500-character limit
        payload["priority"] = PAYLOAD_TEXT
        conn.execute(
            "UPDATE tasks SET payload = ? WHERE id = ?",
            (json.dumps(payload), task["id"]),
        )
    frozen_clock.advance(timedelta(days=60))

    caplog.set_level(logging.DEBUG)
    _run_review_maintenance_sweep(container)

    failures = [
        r.getMessage()
        for r in caplog.records
        if "review_sweep_owner_failed" in r.getMessage()
    ]
    assert failures and "error=ValidationError" in failures[0]
    assert "reason=" in failures[0]
    _assert_clean(caplog)
