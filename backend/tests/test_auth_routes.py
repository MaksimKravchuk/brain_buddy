"""Tests for /api/auth/* endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
