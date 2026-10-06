"""Spec 020: the golden decision and park traces run against the real API.

``tests/fixtures/review_traces_tasks.json`` records request sequences and the
expected statuses and responses (format in its ``conventions``). The same file
is copied byte-identically into the Swift sync tests, where the trace replay
against ``BrainBuddyFakeServer`` keeps the fake server from drifting from the
backend on the offline and two-device paths (020-SC-007, 020-FR-013).
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.utils.time import from_isoformat

from .conftest import FrozenClock
from .test_review_auto_park import sweep

TRACES_PATH = Path(__file__).parent / "fixtures" / "review_traces_tasks.json"
TRACES: dict[str, Any] = json.loads(TRACES_PATH.read_text(encoding="utf-8"))
# Slice PR-11 (tasks.md T131): the run traces in the same format. Loaded only
# when present so a missing file fails the schema test below, not collection.
RUNS_PATH = Path(__file__).parent / "fixtures" / "review_traces_runs.json"
RUNS: dict[str, Any] = (
    json.loads(RUNS_PATH.read_text(encoding="utf-8"))
    if RUNS_PATH.is_file()
    else {"traces": []}
)
RUN_TRACE_IDS = ("TR-R01", "TR-R02", "TR-R03", "TR-R04", "TR-R05")
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _substitute(value: Any, captured: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda m: str(captured[m.group(1)]), value)
    if isinstance(value, list):
        return [_substitute(item, captured) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, captured) for key, item in value.items()}
    return value


def _normal(value: Any) -> Any:
    """Instants compare as UTC instants, whatever their spelling."""

    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}T", value):
        try:
            return from_isoformat(value)
        except ValueError:
            return value
    return value


def _matches(expected: Any, actual: Any, where: str = "body") -> None:
    if expected == "$present":
        assert actual is not None, where
    elif isinstance(expected, dict):
        assert isinstance(actual, dict), where
        for key, item in expected.items():
            assert key in actual, f"{where}.{key} missing"
            _matches(item, actual[key], f"{where}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), where
        for index, item in enumerate(expected):
            _matches(item, actual[index], f"{where}[{index}]")
    else:
        assert _normal(actual) == _normal(expected), (where, actual, expected)


def _capture(path: str, body: Any) -> Any:
    value = body
    for part in path.split("."):
        value = value[part]
    return value


def _run_step(
    step: dict[str, Any],
    client: TestClient,
    clock: FrozenClock,
    captured: dict[str, Any],
) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]
    if "advance" in step:
        clock.advance(timedelta(**step["advance"]))
        return
    if step.get("sweep"):
        sweep(container)
        return
    if "flag" in step:
        container.feature_flag_service.set_mode(
            "weekly_review", step["flag"], operator_id="trace"
        )
        return
    request = _substitute(step["request"], captured)
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
def test_020_SC_007_020_FR_013_golden_trace_replays_against_the_real_api(
    api_client: TestClient, frozen_clock: FrozenClock, trace: dict[str, Any]
) -> None:
    """Every recorded status and response holds against the backend."""

    frozen_clock.set(from_isoformat(trace["start"]))
    container = api_client.app.state.container  # type: ignore[attr-defined]
    container.feature_flag_service.set_mode(
        "weekly_review", trace["flag"], operator_id="trace"
    )
    captured: dict[str, Any] = {}
    for step in trace["steps"]:
        with allure.step(f"{trace['id']}: {step['name']}"):
            _run_step(step, api_client, frozen_clock, captured)
            allure.attach(
                json.dumps(
                    {key: value for key, value in step.items() if key != "name"},
                    sort_keys=True,
                ),
                name="Trace step",
                attachment_type=allure.attachment_type.JSON,
            )


def _replay(trace: dict[str, Any], client: TestClient, clock: FrozenClock) -> None:
    clock.set(from_isoformat(trace["start"]))
    container = client.app.state.container  # type: ignore[attr-defined]
    container.feature_flag_service.set_mode(
        "weekly_review", trace["flag"], operator_id="trace"
    )
    captured: dict[str, Any] = {}
    for step in trace["steps"]:
        with allure.step(f"{trace['id']}: {step['name']}"):
            _run_step(step, client, clock, captured)
            allure.attach(
                json.dumps(
                    {key: value for key, value in step.items() if key != "name"},
                    sort_keys=True,
                ),
                name="Trace step",
                attachment_type=allure.attachment_type.JSON,
            )


@pytest.mark.parametrize(
    "trace", RUNS["traces"], ids=[trace["id"] for trace in RUNS["traces"]]
)
def test_020_FR_029_020_SC_007_run_trace_replays_against_the_real_api(
    api_client: TestClient, frozen_clock: FrozenClock, trace: dict[str, Any]
) -> None:
    """Start, replace, merged progress, a late retry merged once, finish."""

    _replay(trace, api_client, frozen_clock)


def test_020_FR_011_020_SC_007_run_trace_file_declares_its_schema() -> None:
    """The run traces exist in the shared format and name their requirements."""

    assert RUNS_PATH.is_file(), f"{RUNS_PATH.name} is missing"
    assert RUNS["schema"] == TRACES["schema"]
    assert RUNS["conventions"] == TRACES["conventions"]
    assert tuple(trace["id"] for trace in RUNS["traces"]) == RUN_TRACE_IDS
    covered = {req for trace in RUNS["traces"] for req in trace["requirements"]}
    assert {"020-FR-011", "020-FR-029", "020-SC-007"} <= covered
    for trace in RUNS["traces"]:
        assert all(req.startswith("020-") for req in trace["requirements"])


def test_020_SC_007_trace_file_declares_its_schema_and_requirements() -> None:
    """Each trace names the feature-qualified ids it evidences."""

    assert TRACES["schema"] == "brainbuddy-review-traces/v1"
    ids = [trace["id"] for trace in TRACES["traces"]]
    assert len(ids) == len(set(ids)) == 7
    for trace in TRACES["traces"]:
        assert trace["requirements"]
        assert all(req.startswith("020-") for req in trace["requirements"])
