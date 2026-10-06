"""Spec 020: the ``weekly_review`` exposure gate (contracts/http.md "Gate").

Exposure control is not authorization: with the flag off a gated read answers
404 ``weekly_review_disabled``; with it on the route answers. Every response,
success or failure, carries ``X-Correlation-ID`` and the error envelope carries
the same id as ``reference_id`` (FR-045).
"""

from __future__ import annotations

import uuid

import allure
from fastapi.testclient import TestClient

STATE = "/api/review/state"


def enable_weekly_review(client: TestClient) -> None:
    client.app.state.container.feature_flag_service.set_mode(  # type: ignore[attr-defined]
        "weekly_review", "on", operator_id="test-operator"
    )


def test_020_FR_042_gated_read_is_404_weekly_review_disabled_while_off(
    api_client: TestClient,
) -> None:
    """With the flag off, ``GET /review/state`` is the fail-closed 404 body."""

    correlation = str(uuid.uuid4())
    with allure.step("GET /review/state with the flag off"):
        response = api_client.get(STATE, headers={"X-Correlation-ID": correlation})
    assert response.status_code == 404
    assert response.json() == {
        "message": "Not found",
        "detail": {"reason": "weekly_review_disabled"},
        "reference_id": correlation,
    }
    assert response.headers["X-Correlation-ID"] == correlation


def test_020_FR_045_gated_read_answers_with_a_correlation_id_when_on(
    api_client: TestClient,
) -> None:
    """With the flag effective the route answers 200 and carries the id."""

    enable_weekly_review(api_client)
    with allure.step("GET /review/state with the flag on"):
        response = api_client.get(STATE)
    assert response.status_code == 200, response.text
    assert response.headers["X-Correlation-ID"]
    assert response.json()["explainer_seen"] is False


def test_020_FR_042_selected_users_gate_only_the_selected_account(
    second_api_client: tuple[TestClient, TestClient],
) -> None:
    """SELECTED_USERS exposes the review to that account only."""

    member, outsider = second_api_client
    service = member.app.state.container.feature_flag_service  # type: ignore[attr-defined]
    member_id = member.get("/api/auth/me").json()["id"]
    service.set_mode("weekly_review", "selected_users", operator_id="test-operator")
    service.add_selected_user(
        "weekly_review", operator_id="test-operator", account_id=member_id
    )

    assert member.get(STATE).status_code == 200
    blocked = outsider.get(STATE)
    assert blocked.status_code == 404
    assert blocked.json()["detail"] == {"reason": "weekly_review_disabled"}


def test_020_FR_045_unauthenticated_review_routes_are_401(
    anonymous_api_client: TestClient,
) -> None:
    """Authentication comes before the gate: no session is 401, never 404."""

    response = anonymous_api_client.get(STATE)
    assert response.status_code == 401
    assert response.headers["X-Correlation-ID"]
