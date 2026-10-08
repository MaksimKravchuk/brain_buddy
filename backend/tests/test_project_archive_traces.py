"""Spec 021: the golden project archive traces run against the real API.

``tests/fixtures/project_archive_traces.json`` records request sequences and the
expected statuses and responses (format in its ``conventions``), in the format
of the 020 review traces whose matcher it reuses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from .test_review_traces import _capture, _matches, _substitute

TRACES_PATH = Path(__file__).parent / "fixtures" / "project_archive_traces.json"
TRACES: dict[str, Any] = json.loads(TRACES_PATH.read_text(encoding="utf-8"))
SEEDED_AT = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def _seed(client: TestClient, seed: dict[str, str]) -> None:
    repo = client.app.state.container.task_service.task_repo  # type: ignore[attr-defined]
    owner = client.get("/api/account").json()["id"]
    project = repo.get_project_for_owner(seed["project"], owner_id=owner)
    kept = seed["kind"] == "archive_keeping_members"
    repo.save_project(
        project.model_copy(
            update={
                "state": "archived",
                "revision": project.revision + 1,
                "archived_at": SEEDED_AT if kept else None,
                "archived_before_lossless": not kept,
            }
        )
    )


def _run_step(
    step: dict[str, Any],
    clients: dict[str, TestClient],
    captured: dict[str, Any],
) -> None:
    if "seed" in step:
        _seed(clients["first"], _substitute(step["seed"], captured))
        return
    request = _substitute(step["request"], captured)
    client = clients[request.get("as", "first")]
    headers = {"Idempotency-Key": request["key"]} if "key" in request else {}
    response = client.request(
        request["method"], request["path"], json=request.get("body"), headers=headers
    )
    expect = _substitute(step["expect"], captured)
    assert response.status_code == expect["status"], (step["name"], response.text)
    body = response.json() if response.content else None
    if "body" in expect:
        _matches(expect["body"], body)
    for name, path in step.get("capture", {}).items():
        captured[name] = _capture(path, body)


@pytest.mark.parametrize(
    "trace", TRACES["traces"], ids=[trace["id"] for trace in TRACES["traces"]]
)
def test_021_FR_025_021_FR_026_021_FR_027_021_FR_028_golden_trace_replays(
    second_api_client: tuple[TestClient, TestClient], trace: dict[str, Any]
) -> None:
    """Every recorded status and response holds against the backend."""

    clients = dict(zip(("first", "second"), second_api_client, strict=True))
    captured: dict[str, Any] = {}
    for step in trace["steps"]:
        with allure.step(f"{trace['id']}: {step['name']}"):
            _run_step(step, clients, captured)


def test_021_FR_025_trace_file_names_its_requirements() -> None:
    """Each trace names the feature-qualified ids it evidences."""

    assert TRACES["schema"] == "brainbuddy-project-archive-traces/v1"
    ids = [trace["id"] for trace in TRACES["traces"]]
    assert len(ids) == len(set(ids))
    covered = {req for trace in TRACES["traces"] for req in trace["requirements"]}
    assert covered == {"021-FR-025", "021-FR-026", "021-FR-027", "021-FR-028"}
