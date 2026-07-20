"""Mobile opaque-session transport contract tests."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.core import get_config
from app.main import create_app
from app.schemas.auth import Invite
from app.utils.time import utcnow


def _client_with_account(tmp_path, monkeypatch) -> tuple[TestClient, str]:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "mobile-session-data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    app = create_app()
    app.state.container.invite_repo.create(
        Invite(code="mobile-session-invite", created_at=utcnow())
    )
    client = TestClient(app)
    signup = client.post(
        "/api/auth/signup",
        json={
            "email": "mobile@example.com",
            "password": "correct-horse-battery-staple",
            "invite_code": "mobile-session-invite",
        },
    )
    assert signup.status_code == 201
    client.cookies.clear()
    return client, "mobile@example.com"


def test_mobile_session_is_opaque_non_cookie_and_resolves_bearer(tmp_path, monkeypatch) -> None:
    client, email = _client_with_account(tmp_path, monkeypatch)

    response = client.post(
        "/api/auth/mobile/sessions",
        json={"email": email, "password": "correct-horse-battery-staple"},
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert "set-cookie" not in response.headers
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["user"]["email"] == email
    assert body["session_token"]
    assert body["expires_at"]

    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {body['session_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_dual_or_malformed_credentials_are_rejected(tmp_path, monkeypatch) -> None:
    client, email = _client_with_account(tmp_path, monkeypatch)
    mobile = client.post(
        "/api/auth/mobile/sessions",
        json={"email": email, "password": "correct-horse-battery-staple"},
    ).json()
    client.cookies.set("brainbuddy_session", "browser-token")

    dual = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {mobile['session_token']}"},
    )
    assert dual.status_code == 400

    client.cookies.clear()
    malformed = client.get("/api/auth/me", headers={"Authorization": "Basic nope"})
    assert malformed.status_code == 401


def test_bearer_logout_revokes_and_session_lookup_honours_expiry(tmp_path, monkeypatch) -> None:
    client, email = _client_with_account(tmp_path, monkeypatch)
    mobile = client.post(
        "/api/auth/mobile/sessions",
        json={"email": email, "password": "correct-horse-battery-staple"},
    ).json()
    headers = {"Authorization": f"Bearer {mobile['session_token']}"}

    logout = client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 204
    assert client.get("/api/auth/me", headers=headers).status_code == 401

    expired = client.post(
        "/api/auth/mobile/sessions",
        json={"email": email, "password": "correct-horse-battery-staple"},
    ).json()
    token_hash = client.app.state.container.auth_service.hash_session_token(
        expired["session_token"]
    )
    session = client.app.state.container.session_repo.get(token_hash)
    assert session is not None
    session_repo = client.app.state.container.session_repo
    session_repo.delete(token_hash)
    session_repo.create(
        session.model_copy(update={"expires_at": utcnow() - timedelta(seconds=1)})
    )
    assert (
        client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {expired['session_token']}"},
        ).status_code
        == 401
    )
