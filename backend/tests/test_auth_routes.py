"""Tests for /api/auth/* endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Cookies

from app.container import Container
from app.core import get_config
from app.core.rate_limit import LOGIN_MAX_ATTEMPTS
from app.main import create_app
from app.schemas.auth import Invite
from app.utils.time import utcnow


def _bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, subdir: str
) -> tuple[TestClient, Container, str]:
    data_root = tmp_path / subdir
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    app = create_app()
    container: Container = app.state.container
    code = f"invite_{subdir}"
    container.invite_repo.create(Invite(code=code, created_at=utcnow()))
    return TestClient(app), container, code


def test_signup_sets_cookie_and_returns_me(tmp_path, monkeypatch) -> None:
    client, _, code = _bootstrap(tmp_path, monkeypatch, subdir="signup")
    resp = client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "very-long-password",
            "invite_code": code,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "user@example.com"
    assert "brainbuddy_session" in resp.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"


def test_signup_rejects_used_invite(tmp_path, monkeypatch) -> None:
    client, _, code = _bootstrap(tmp_path, monkeypatch, subdir="dup_invite")
    resp1 = client.post(
        "/api/auth/signup",
        json={
            "email": "first@example.com",
            "password": "very-long-password",
            "invite_code": code,
        },
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        "/api/auth/signup",
        json={
            "email": "second@example.com",
            "password": "very-long-password",
            "invite_code": code,
        },
    )
    assert resp2.status_code == 400


def test_login_and_logout_flow(tmp_path, monkeypatch) -> None:
    client, _, code = _bootstrap(tmp_path, monkeypatch, subdir="login")
    client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "very-long-password",
            "invite_code": code,
        },
    )
    # Drop the session cookie from signup so login is verifiable on its own.
    client.cookies.clear()

    login = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "very-long-password"},
    )
    assert login.status_code == 200
    assert "brainbuddy_session" in client.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 204

    me_after = client.get("/api/auth/me")
    assert me_after.status_code == 401


def test_held_logout_response_cannot_clear_a_successor_login_cookie(
    tmp_path, monkeypatch
) -> None:
    """A late logout response must not remove a successor session cookie."""
    client, _, code = _bootstrap(tmp_path, monkeypatch, subdir="logout_response_race")
    signup = client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "very-long-password",
            "invite_code": code,
        },
    )
    session_a = signup.cookies["brainbuddy_session"]

    # Model a browser explicitly applying real Set-Cookie response headers. The
    # logout response is held while its authenticated A request still revokes A.
    browser_cookies = Cookies()
    browser_cookies.extract_cookies(signup)
    held_logout = client.post(
        "/api/auth/logout",
        headers={"Cookie": f"brainbuddy_session={session_a}"},
    )
    assert held_logout.status_code == 204
    assert "set-cookie" not in held_logout.headers

    login_b = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "very-long-password"},
    )
    assert login_b.status_code == 200
    browser_cookies.extract_cookies(login_b)
    session_b = browser_cookies["brainbuddy_session"]
    assert session_b != session_a

    # Deliver the older response only after B has been installed. Without a
    # Set-Cookie deletion in that real response, B remains the browser token.
    browser_cookies.extract_cookies(held_logout)
    assert browser_cookies["brainbuddy_session"] == session_b

    me_as_b = client.get(
        "/api/auth/me", headers={"Cookie": f"brainbuddy_session={session_b}"}
    )
    assert me_as_b.status_code == 200
    assert me_as_b.json()["email"] == "user@example.com"


def test_failed_newer_login_then_held_logout_response_is_anonymous(
    tmp_path, monkeypatch
) -> None:
    """A revoked old token cannot authenticate after a failed successor login."""
    client, _, code = _bootstrap(
        tmp_path, monkeypatch, subdir="failed_login_logout_race"
    )
    signup = client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "very-long-password",
            "invite_code": code,
        },
    )
    session_a = signup.cookies["brainbuddy_session"]
    browser_cookies = Cookies()
    browser_cookies.extract_cookies(signup)

    # The server processes logout A, but the browser has not received that
    # response before the newer login attempt fails.
    held_logout = client.post(
        "/api/auth/logout",
        headers={"Cookie": f"brainbuddy_session={session_a}"},
    )
    failed_login = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )
    assert failed_login.status_code == 401

    browser_cookies.extract_cookies(failed_login)
    browser_cookies.extract_cookies(held_logout)
    assert browser_cookies["brainbuddy_session"] == session_a

    # The old cookie may remain in the browser, but its server-side session was
    # revoked by logout, so the resulting authorization truth is anonymous.
    me_as_old_session = client.get(
        "/api/auth/me", headers={"Cookie": f"brainbuddy_session={session_a}"}
    )
    assert me_as_old_session.status_code == 401


def test_login_wrong_password_returns_401(tmp_path, monkeypatch) -> None:
    client, _, code = _bootstrap(tmp_path, monkeypatch, subdir="wrongpw")
    client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "very-long-password",
            "invite_code": code,
        },
    )
    client.cookies.clear()
    resp = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "not-the-password"},
    )
    assert resp.status_code == 401


def test_login_rate_limiter_triggers_429(tmp_path, monkeypatch) -> None:
    client, _, code = _bootstrap(tmp_path, monkeypatch, subdir="ratelimit")
    client.post(
        "/api/auth/signup",
        json={
            "email": "user@example.com",
            "password": "very-long-password",
            "invite_code": code,
        },
    )
    client.cookies.clear()

    for _ in range(LOGIN_MAX_ATTEMPTS):
        resp = client.post(
            "/api/auth/login",
            json={"email": "user@example.com", "password": "wrong"},
        )
        assert resp.status_code == 401

    limited = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "very-long-password"},
    )
    assert limited.status_code == 429


def test_me_requires_authentication(anonymous_api_client) -> None:
    resp = anonymous_api_client.get("/api/auth/me")
    assert resp.status_code == 401
