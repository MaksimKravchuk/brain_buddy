"""Tests for the /api/account profile, email, and password endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.container import Container
from app.core.rate_limit import SENSITIVE_ACTION_MAX_ATTEMPTS
from app.exceptions import StorageUnavailableError

from .conftest import (
    SECOND_USER_EMAIL,
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    BrainBuddyTestClient,
)


def _container(client: TestClient) -> Container:
    return client.app.state.container  # type: ignore[attr-defined]


def _second_session(client: TestClient) -> TestClient:
    """Open a second session for the same user against the same app."""

    other = BrainBuddyTestClient(client.app)  # type: ignore[attr-defined]
    resp = other.post(
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return other


def _create_task(
    client: TestClient,
    title: str,
    *,
    key: str,
    state: str = "inbox",
) -> dict[str, object]:
    response = client.post(
        "/api/tasks",
        headers={"Idempotency-Key": key},
        json={"title": title, "state": state},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _transition_task(
    client: TestClient,
    task: dict[str, object],
    action: str,
    *,
    key: str,
    to_state: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": action,
        "expected_revision": task["revision"],
    }
    if to_state is not None:
        payload["to_state"] = to_state
    response = client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


# ----------------------------------------------------------------------
# GET /api/account
# ----------------------------------------------------------------------


def test_get_account_returns_profile(api_client: TestClient) -> None:
    """The account read exposes identity fields and no deletion state."""

    resp = api_client.get("/api/account")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == TEST_USER_EMAIL
    assert body["id"].startswith("user_")
    assert body["display_name"] is None
    assert body["completed_task_count"] == 0
    assert body["deletion_requested_at"] is None
    assert body["purge_at"] is None


def test_018_SC_001_account_count_tracks_complete_and_reopen(
    api_client: TestClient,
) -> None:
    """018-FR-001, 018-FR-007: profile reads reflect current lifecycle state."""

    task = _create_task(
        api_client,
        "Count lifecycle",
        key="018-count-lifecycle",
        state="next",
    )
    assert api_client.get("/api/account").json()["completed_task_count"] == 0

    completed = _transition_task(
        api_client,
        task,
        "complete",
        key="018-count-complete",
    )
    assert api_client.get("/api/account").json()["completed_task_count"] == 1

    _transition_task(
        api_client,
        completed,
        "reopen",
        key="018-count-reopen",
        to_state="next",
    )
    assert api_client.get("/api/account").json()["completed_task_count"] == 0


def test_018_SC_002_account_count_excludes_other_owner_cancelled_and_subtasks(
    second_api_client: tuple[TestClient, TestClient],
) -> None:
    """018-FR-003, 018-FR-004, 018-FR-005, 018-FR-006; 018-SC-002, 018-SC-003."""

    client_a, client_b = second_api_client
    for index in range(2):
        task = _create_task(
            client_a,
            f"Owned completed {index}",
            key=f"018-owned-{index}",
        )
        _transition_task(
            client_a,
            task,
            "complete",
            key=f"018-owned-complete-{index}",
        )

    cancelled = _create_task(client_a, "Cancelled", key="018-cancelled")
    _transition_task(
        client_a,
        cancelled,
        "cancel",
        key="018-cancel-transition",
    )

    parent = _create_task(client_a, "Parent", key="018-parent")
    subtask_response = client_a.post(
        f"/api/tasks/{parent['id']}/subtasks",
        headers={"Idempotency-Key": "018-subtask"},
        json={"title": "Completed child"},
    )
    assert subtask_response.status_code == 201, subtask_response.text
    subtask = subtask_response.json()
    completed_subtask = client_a.post(
        f"/api/tasks/{parent['id']}/subtasks/{subtask['id']}/transitions",
        headers={"Idempotency-Key": "018-subtask-complete"},
        json={"action": "complete", "expected_revision": subtask["revision"]},
    )
    assert completed_subtask.status_code == 200, completed_subtask.text

    other_task = _create_task(client_b, "Other owner", key="018-other")
    _transition_task(
        client_b,
        other_task,
        "complete",
        key="018-other-complete",
    )

    assert client_a.get("/api/account").json()["completed_task_count"] == 2
    assert client_b.get("/api/account").json()["completed_task_count"] == 1


def test_get_account_requires_auth(anonymous_api_client: TestClient) -> None:
    """Anonymous callers are refused."""

    assert anonymous_api_client.get("/api/account").status_code == 401


# ----------------------------------------------------------------------
# PATCH /api/account/profile
# ----------------------------------------------------------------------


def test_update_profile_sets_display_name(api_client: TestClient) -> None:
    """A display name is stored, trimmed, and echoed via /auth/me."""

    resp = api_client.patch("/api/account/profile", json={"display_name": "  Maks  "})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Maks"

    me = api_client.get("/api/auth/me")
    assert me.json()["display_name"] == "Maks"


def test_update_profile_empty_clears_display_name(api_client: TestClient) -> None:
    """Whitespace-only input clears the display name back to null."""

    api_client.patch("/api/account/profile", json={"display_name": "Maks"})
    resp = api_client.patch("/api/account/profile", json={"display_name": "   "})
    assert resp.status_code == 200
    assert resp.json()["display_name"] is None


def test_018_FR_012_count_failure_prevents_profile_and_email_writes(
    api_client: TestClient,
    monkeypatch,
) -> None:
    """018-FR-009, 018-FR-012: task failure happens before account mutation."""

    container = _container(api_client)
    current = api_client.get("/api/auth/me").json()

    def unavailable(*, owner_id: str) -> int:
        raise StorageUnavailableError(f"task store unavailable for {owner_id}")

    monkeypatch.setattr(
        container.task_service,
        "completed_task_count",
        unavailable,
    )

    profile_response = api_client.patch(
        "/api/account/profile",
        json={"display_name": "Must not persist"},
    )
    assert profile_response.status_code == 503
    stored = container.user_repo.get_by_id(current["id"])
    assert stored is not None
    assert stored.display_name is None

    email_response = api_client.post(
        "/api/account/email",
        json={
            "new_email": "must-not-persist@example.com",
            "current_password": TEST_USER_PASSWORD,
        },
    )
    assert email_response.status_code == 503
    assert container.user_repo.get_by_email(TEST_USER_EMAIL) is not None
    assert container.user_repo.get_by_email("must-not-persist@example.com") is None


def test_update_profile_rejects_overlong_name(api_client: TestClient) -> None:
    """Display names above the length cap fail schema validation."""

    resp = api_client.patch("/api/account/profile", json={"display_name": "x" * 65})
    assert resp.status_code == 422


def test_update_profile_rejects_unknown_fields(api_client: TestClient) -> None:
    """The strict request schema refuses stray fields."""

    resp = api_client.patch(
        "/api/account/profile",
        json={"display_name": "ok", "email": "sneaky@example.com"},
    )
    assert resp.status_code == 422


# ----------------------------------------------------------------------
# POST /api/account/email
# ----------------------------------------------------------------------


def test_change_email_moves_account(api_client: TestClient) -> None:
    """After a change, only the new address can sign in."""

    resp = api_client.post(
        "/api/account/email",
        json={
            "new_email": "renamed@example.com",
            "current_password": TEST_USER_PASSWORD,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "renamed@example.com"

    old_login = BrainBuddyTestClient(api_client.app).post(  # type: ignore[attr-defined]
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert old_login.status_code == 401

    new_login = BrainBuddyTestClient(api_client.app).post(  # type: ignore[attr-defined]
        "/api/auth/login",
        json={"email": "renamed@example.com", "password": TEST_USER_PASSWORD},
    )
    assert new_login.status_code == 200


def test_change_email_wrong_password_is_403(api_client: TestClient) -> None:
    """A failed re-auth is 403 (not 401, which would clear the session)."""

    resp = api_client.post(
        "/api/account/email",
        json={"new_email": "other@example.com", "current_password": "wrong-pass"},
    )
    assert resp.status_code == 403
    assert api_client.get("/api/account").json()["email"] == TEST_USER_EMAIL


def test_change_email_conflict_is_generic_400(second_api_client) -> None:
    """A taken address yields the same generic 400 as any rejection.

    The response must not reveal that the address belongs to an account, and
    the other account must keep it.
    """

    client_a, client_b = second_api_client
    resp = client_a.post(
        "/api/account/email",
        json={
            "new_email": SECOND_USER_EMAIL,
            "current_password": TEST_USER_PASSWORD,
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["message"] == "That email address can't be used."
    assert SECOND_USER_EMAIL not in str(body)

    assert client_a.get("/api/account").json()["email"] == TEST_USER_EMAIL
    assert client_b.get("/api/account").json()["email"] == SECOND_USER_EMAIL


def test_change_email_requires_auth(anonymous_api_client: TestClient) -> None:
    """Anonymous callers are refused before any re-auth logic runs."""

    resp = anonymous_api_client.post(
        "/api/account/email",
        json={"new_email": "a@example.com", "current_password": "whatever"},
    )
    assert resp.status_code == 401


# ----------------------------------------------------------------------
# POST /api/account/password
# ----------------------------------------------------------------------


def test_change_password_rotates_and_keeps_current_session(
    api_client: TestClient,
) -> None:
    """Other sessions are revoked; the caller's session survives."""

    other = _second_session(api_client)
    assert other.get("/api/account").status_code == 200

    resp = api_client.post(
        "/api/account/password",
        json={
            "current_password": TEST_USER_PASSWORD,
            "new_password": "brand-new-password-123",
        },
    )
    assert resp.status_code == 204

    assert api_client.get("/api/account").status_code == 200
    assert other.get("/api/account").status_code == 401

    relogin = BrainBuddyTestClient(api_client.app).post(  # type: ignore[attr-defined]
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": "brand-new-password-123"},
    )
    assert relogin.status_code == 200


def test_change_password_wrong_current_is_403(api_client: TestClient) -> None:
    """A failed re-auth leaves the password untouched."""

    resp = api_client.post(
        "/api/account/password",
        json={"current_password": "wrong-pass", "new_password": "whatever-is-long"},
    )
    assert resp.status_code == 403

    relogin = BrainBuddyTestClient(api_client.app).post(  # type: ignore[attr-defined]
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert relogin.status_code == 200


def test_change_password_enforces_policy(api_client: TestClient) -> None:
    """The new password must satisfy the same policy as signup."""

    resp = api_client.post(
        "/api/account/password",
        json={"current_password": TEST_USER_PASSWORD, "new_password": "short"},
    )
    assert resp.status_code == 400


# ----------------------------------------------------------------------
# Sensitive-action rate limiting
# ----------------------------------------------------------------------


def test_sensitive_actions_are_rate_limited_per_user(api_client: TestClient) -> None:
    """Re-auth attempts across the sensitive endpoints share one budget."""

    for _ in range(SENSITIVE_ACTION_MAX_ATTEMPTS):
        resp = api_client.post(
            "/api/account/password",
            json={"current_password": "wrong-pass", "new_password": "whatever-is-long"},
        )
        assert resp.status_code == 403

    resp = api_client.post(
        "/api/account/email",
        json={
            "new_email": "next@example.com",
            "current_password": TEST_USER_PASSWORD,
        },
    )
    assert resp.status_code == 429
