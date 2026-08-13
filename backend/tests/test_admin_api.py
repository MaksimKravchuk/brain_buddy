"""Tests for the /api/admin routes: fail-closed authz, exact lookup, revoke.

009-FR-002, 009-FR-003, 009-FR-004, 009-FR-007, 009-FR-009, 009-FR-010.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.core import get_config
from app.main import create_app
from app.schemas.auth import Invite
from app.utils.time import utcnow

from .conftest import (
    SECOND_USER_EMAIL,
    SECOND_USER_PASSWORD,
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    BrainBuddyTestClient,
)


def _signup(app, *, email: str, password: str) -> tuple[TestClient, dict]:
    container: Container = app.state.container
    invite_code = f"invite_{email}"
    container.invite_repo.create(Invite(code=invite_code, created_at=utcnow()))
    client = BrainBuddyTestClient(app)
    resp = client.post(
        "/api/auth/signup",
        json={"email": email, "password": password, "invite_code": invite_code},
    )
    assert resp.status_code == 201, resp.text
    return client, resp.json()


@pytest.fixture
def admin_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, dict, TestClient, dict], None, None]:
    """One app: an allow-listed operator and a non-operator member."""

    data_root = tmp_path / "admin-data"
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS", TEST_USER_EMAIL)
    get_config.cache_clear()
    app = create_app()

    operator_client, operator_me = _signup(
        app, email=TEST_USER_EMAIL, password=TEST_USER_PASSWORD
    )
    member_client, member_me = _signup(
        app, email=SECOND_USER_EMAIL, password=SECOND_USER_PASSWORD
    )

    yield operator_client, operator_me, member_client, member_me

    operator_client.close()
    member_client.close()
    get_config.cache_clear()
    for var in (
        "BRAIN_BUDDY_DATA_DIR",
        "BRAIN_BUDDY_ENV",
        "BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS",
    ):
        monkeypatch.delenv(var, raising=False)


def test_009_FR_002_unauthenticated_lookup_is_401(
    anonymous_api_client: TestClient,
) -> None:
    resp = anonymous_api_client.post(
        "/api/admin/accounts/lookup", json={"account_id": "user_anything"}
    )
    assert resp.status_code == 401


def test_009_FR_002_unauthenticated_revoke_is_401(
    anonymous_api_client: TestClient,
) -> None:
    resp = anonymous_api_client.post(
        "/api/admin/accounts/user_anything/revoke-sessions"
    )
    assert resp.status_code == 401


def test_009_FR_002_non_operator_lookup_is_403(admin_world) -> None:
    _operator_client, _operator_me, member_client, _member_me = admin_world
    resp = member_client.post(
        "/api/admin/accounts/lookup", json={"account_id": "user_anything"}
    )
    assert resp.status_code == 403
    assert "id" not in resp.json()


def test_009_FR_002_non_operator_revoke_is_403(admin_world) -> None:
    _operator_client, operator_me, member_client, _member_me = admin_world
    resp = member_client.post(
        f"/api/admin/accounts/{operator_me['id']}/revoke-sessions"
    )
    assert resp.status_code == 403


def test_009_FR_002_denial_does_not_vary_with_target_existence(admin_world) -> None:
    """A 403 must look identical whether the target account exists or not."""

    _operator_client, operator_me, member_client, _member_me = admin_world

    existing = member_client.post(
        "/api/admin/accounts/lookup", json={"account_id": operator_me["id"]}
    )
    missing = member_client.post(
        "/api/admin/accounts/lookup", json={"account_id": "user_does_not_exist"}
    )

    assert existing.status_code == missing.status_code == 403
    assert existing.json()["message"] == missing.json()["message"]


def test_009_FR_003_operator_looks_up_by_account_id(admin_world) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/lookup", json={"account_id": member_me["id"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == member_me["id"]
    assert body["email"] == SECOND_USER_EMAIL


def test_009_FR_003_operator_looks_up_by_email(admin_world) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/lookup", json={"email": SECOND_USER_EMAIL}
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == member_me["id"]


def test_009_FR_003_lookup_rejects_neither_field(admin_world) -> None:
    operator_client, *_ = admin_world
    resp = operator_client.post("/api/admin/accounts/lookup", json={})
    assert resp.status_code == 422


def test_009_FR_003_lookup_rejects_both_fields(admin_world) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/lookup",
        json={"account_id": member_me["id"], "email": SECOND_USER_EMAIL},
    )
    assert resp.status_code == 422


def test_009_FR_003_lookup_no_exact_match_is_404(admin_world) -> None:
    operator_client, *_ = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/lookup", json={"account_id": "user_does_not_exist"}
    )
    assert resp.status_code == 404


def test_009_FR_004_lookup_response_has_only_the_four_allowed_fields(
    admin_world,
) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/lookup", json={"account_id": member_me["id"]}
    )
    assert resp.status_code == 200
    assert set(resp.json()) == {"id", "email", "display_name", "deletion_requested"}


def test_009_FR_007_revoke_sessions_unknown_account_is_404(admin_world) -> None:
    operator_client, *_ = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/user_does_not_exist/revoke-sessions"
    )
    assert resp.status_code == 404


def test_009_FR_009_revoke_sessions_rejects_cross_origin_request(
    admin_world,
) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    resp = operator_client.post(
        f"/api/admin/accounts/{member_me['id']}/revoke-sessions",
        headers={"Origin": "https://attacker.example"},
    )
    assert resp.status_code == 403


def test_009_FR_009_revoke_sessions_allows_matching_origin(admin_world) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    resp = operator_client.post(
        f"/api/admin/accounts/{member_me['id']}/revoke-sessions",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200


def test_009_FR_007_revoke_sessions_is_idempotent_on_zero_active_sessions(
    admin_world,
) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    # The member's own signup session is still live; log it out server-side
    # by revoking it once, then prove a second revoke still reports success.
    first = operator_client.post(
        f"/api/admin/accounts/{member_me['id']}/revoke-sessions"
    )
    assert first.status_code == 200
    assert first.json()["revoked_count"] >= 1

    second = operator_client.post(
        f"/api/admin/accounts/{member_me['id']}/revoke-sessions"
    )
    assert second.status_code == 200
    assert second.json()["revoked_count"] == 0


def test_009_FR_007_revoke_sessions_signs_the_account_out_everywhere(
    admin_world,
) -> None:
    operator_client, _operator_me, member_client, member_me = admin_world
    assert member_client.get("/api/auth/me").status_code == 200

    resp = operator_client.post(
        f"/api/admin/accounts/{member_me['id']}/revoke-sessions"
    )
    assert resp.status_code == 200

    assert member_client.get("/api/auth/me").status_code == 401


def test_009_FR_010_existing_auth_me_is_unaffected_by_this_feature(
    admin_world,
) -> None:
    operator_client, operator_me, _member_client, _member_me = admin_world
    resp = operator_client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["id"] == operator_me["id"]
