"""HTTP account journeys preserve cookies, response envelopes and proof ownership."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

import pytest

from .test_modern_auth_api import live_modern
from .test_modern_auth_apple_integration import apple_runtime
from .test_modern_auth_service import VERIFIER, challenge

__all__ = ["live_modern", "apple_runtime"]
pytestmark = [
    pytest.mark.allure_label("Authentication & Access", label_type="epic"),
    pytest.mark.allure_label(
        "Modern authentication HTTP journeys", label_type="feature"
    ),
    pytest.mark.allure_label(
        "023-FR-001 023-FR-018 023-SC-004 HTTP authority", label_type="story"
    ),
]


def email_step(runtime, email, purpose="login", **extra):
    client, service, mail, sent, _, clock = runtime
    clock.now += timedelta(seconds=61)
    requested = client.post(
        "/api/auth/email/request",
        json={
            "email": email,
            "purpose": purpose,
            "client": "web",
            "client_challenge": challenge(),
            **extra,
        },
    )
    assert requested.status_code == 202, requested.text
    assert mail.dispatch_one()
    verified = client.post(
        "/api/auth/email/verify",
        json={
            "challenge_id": requested.json()["challenge_id"],
            "client_verifier": VERIFIER,
            "code": sent[-1][1],
        },
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


def email_proof(runtime, owner, action):
    return email_step(
        runtime,
        owner["email"],
        "reauth",
        expected_account_id=owner["id"],
        action=action,
    )["recent_proof"]


def google_step(runtime, purpose="login", **extra):
    client, *_ = runtime
    client.base_url = "https://api.example.com"
    started = client.post(
        "/api/auth/providers/google/start",
        json={
            "purpose": purpose,
            "client": "web",
            "client_challenge": challenge(),
            **extra,
        },
    )
    assert started.status_code == 200, started.text
    assert "Secure" in started.headers["set-cookie"]
    callback = client.get(
        "/api/auth/providers/google/callback",
        params={
            "code": "synthetic-code",
            "state": started.json()["state"],
        },
        follow_redirects=False,
    )
    assert callback.status_code == 303, callback.text
    assert "Max-Age=0" in callback.headers["set-cookie"]
    fragment = parse_qs(urlsplit(callback.headers["location"]).fragment)
    result = client.post(
        "/api/auth/providers/complete",
        json={
            "attempt_id": fragment["attempt"][0],
            "state": fragment["state"][0],
            "handoff_code": fragment["grant"][0],
            "client_verifier": VERIFIER,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_023_FR_018_023_SC_004_email_owner_adds_password_exports_and_deletes(
    live_modern,
):
    client, *_ = live_modern
    owner = email_step(live_modern, "http-rights@example.com")["user"]
    proof = email_proof(live_modern, owner, "password")
    added = client.post(
        "/api/account/auth-password",
        json={
            "expected_account_id": owner["id"],
            "recent_proof": proof,
            "new_password": "replacement-http-password",
        },
    )
    assert added.status_code == 204
    assert client.get("/api/auth/me").json()["id"] == owner["id"]
    assert client.get("/api/account/auth-methods").json()["has_password"]
    for action in ("export", "delete"):
        confirmed = client.post(
            "/api/auth/confirm/password",
            json={
                "current_password": "replacement-http-password",
                "action": action,
                "expected_account_id": owner["id"],
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        result = client.post(
            f"/api/account/auth-{action}",
            json={
                "expected_account_id": owner["id"],
                "recent_proof": confirmed.json()["recent_proof"],
            },
        )
        if action == "export":
            assert result.status_code == 200
            assert result.headers["content-type"] == "application/zip"
            with ZipFile(BytesIO(result.content)) as archive:
                assert "auth/connected-methods.json" in archive.namelist()
                assert b"password_hash" not in archive.read(
                    "auth/connected-methods.json"
                )
        else:
            assert result.status_code == 202
            assert "Max-Age=0" in result.headers["set-cookie"]
            assert client.get("/api/auth/me").status_code == 401


def test_023_FR_011_023_SC_004_recovery_http_reset_revokes_cookie_without_autologin(
    live_modern,
):
    client, service, _, _, _, clock = live_modern
    user = service.auth.seed_admin(
        email="http-recovery@example.com", password="original-http-password"
    )
    service.auth.user_repo.mutate(
        user.id, lambda fresh: fresh.model_copy(update={"email_verified_at": clock()})
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "original-http-password"},
        ).status_code
        == 200
    )
    ready = email_step(live_modern, user.email, "recover")
    assert ready["status"] == "reset_ready"
    response = client.post(
        "/api/auth/recovery/reset",
        json={
            "reset_grant": ready["reset_grant"],
            "client_verifier": VERIFIER,
            "new_password": "replacement-http-password",
        },
    )
    assert response.status_code == 204
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("provider_session", [False, True])
def test_023_FR_007_unlink_clears_only_the_origin_provider_session(
    live_modern, provider_session
):
    client, _, _, _, provider, _ = live_modern
    client.base_url = "https://api.example.com"
    owner = email_step(live_modern, "http-link@gmail.com")["user"]
    provider.identity = replace(provider.identity, email=owner["email"])
    linked = google_step(
        live_modern,
        "link",
        action="link:google",
        expected_account_id=owner["id"],
        recent_proof=email_proof(live_modern, owner, "link:google"),
    )
    assert linked["status"] == "linked"
    if provider_session:
        assert google_step(live_modern)["user"]["id"] == owner["id"]
    proof = email_proof(live_modern, owner, "unlink:google")
    removed = client.post(
        "/api/account/auth-methods/google/unlink",
        json={
            "expected_account_id": owner["id"],
            "recent_proof": proof,
        },
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["signed_out"] is provider_session
    assert ("set-cookie" in removed.headers) is provider_session
    assert client.get("/api/auth/me").status_code == (401 if provider_session else 200)


@pytest.mark.parametrize(
    "body,content_type",
    [
        ("{}", "application/json"),
        (
            "code=synthetic&state=" + "a" * 43 + "&state=" + "b" * 43,
            "application/x-www-form-urlencoded",
        ),
        ("code=synthetic&state=bad", "application/x-www-form-urlencoded"),
        (
            "code=synthetic&state=" + "a" * 43 + "&id_token=" + "x" * 16385,
            "application/x-www-form-urlencoded",
        ),
        ("code=" + "x" * 32769, "application/x-www-form-urlencoded"),
        ("%zz", "application/x-www-form-urlencoded"),
    ],
)
def test_023_FR_017_apple_form_exception_rejects_malformed_authority(
    live_modern, body, content_type
):
    client, service, *_ = live_modern
    response = client.post(
        "/api/auth/providers/apple/callback",
        content=body,
        headers={"Content-Type": content_type},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_proof"
    assert service.auth.user_repo.list_users() == []


def test_023_FR_001_native_apple_http_finish_sets_one_session(
    apple_runtime, anonymous_api_client, container
):
    service, _, _, provider, _ = apple_runtime
    client = anonymous_api_client
    container.modern_auth_service = service
    client.app.state.container = container
    client.app.state.config = client.app.state.config.model_copy(
        update={"modern_auth": service.settings}
    )
    started = client.post(
        "/api/auth/providers/apple/start",
        json={
            "purpose": "login",
            "client": "ios",
            "client_challenge": challenge(),
        },
    )
    assert started.status_code == 200
    result = client.post(
        "/api/auth/providers/apple/native/complete",
        json={
            "attempt_id": started.json()["attempt_id"],
            "state": started.json()["state"],
            "authorization_code": "synthetic-code",
            "identity_token": "synthetic-assertion",
            "client_verifier": VERIFIER,
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "signed_in"
    assert client.get("/api/auth/me").json()["id"] == result.json()["user"]["id"]
    assert (
        client.post(
            "/api/auth/providers/apple/notifications",
            json={"payload": "signed-synthetic-notice"},
        ).status_code
        == 204
    )
    assert client.get("/api/auth/me").status_code == 401


def test_023_FR_009_http_resend_replaces_only_the_initiating_challenge(live_modern):
    client, _, mail, sent, _, clock = live_modern
    requested = client.post(
        "/api/auth/email/request",
        json={
            "email": "http-resend@example.com",
            "purpose": "login",
            "client": "web",
            "client_challenge": challenge(),
        },
    )
    assert requested.status_code == 202
    assert mail.dispatch_one()
    old_code = sent[-1][1]
    clock.now += timedelta(seconds=61)
    renewed = client.post(
        "/api/auth/email/resend",
        json={
            "challenge_id": requested.json()["challenge_id"],
            "client_verifier": VERIFIER,
        },
    )
    assert renewed.status_code == 202, renewed.text
    assert mail.dispatch_one()
    old = client.post(
        "/api/auth/email/verify",
        json={
            "challenge_id": requested.json()["challenge_id"],
            "client_verifier": VERIFIER,
            "code": old_code,
        },
    )
    assert old.status_code == 400
    valid = client.post(
        "/api/auth/email/verify",
        json={
            "challenge_id": renewed.json()["challenge_id"],
            "client_verifier": VERIFIER,
            "code": sent[-1][1],
        },
    )
    assert valid.status_code == 200
