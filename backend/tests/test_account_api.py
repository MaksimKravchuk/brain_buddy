"""Tests for the /api/account profile, email, and password endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.container import Container
from app.core.rate_limit import SENSITIVE_ACTION_MAX_ATTEMPTS

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
    assert body["deletion_requested_at"] is None
    assert body["purge_at"] is None


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
