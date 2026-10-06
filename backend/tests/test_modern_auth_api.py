"""New auth routes preserve origins, opaque sessions and typed outcomes."""

from __future__ import annotations

import pytest

from .test_modern_auth_service import VERIFIER, challenge, make_modern


@pytest.mark.parametrize("client", ["web", "ios"])
def test_022_FR_001_discovery_preserves_password_without_optional_keys(
    client, anonymous_api_client
):
    response = anonymous_api_client.get(f"/api/auth/methods?client={client}")
    assert response.status_code == 200
    assert response.json() == {
        "password": True,
        "google": False,
        "apple": False,
        "email": False,
        "web_account_origin": None,
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.parametrize(
    "path",
    [
        "/auth/email/request",
        "/auth/providers/google/start",
        "/auth/confirm/password",
        "/account/auth-delete",
    ],
)
def test_022_FR_019_cross_origin_mutation_is_rejected_before_authority(
    path, anonymous_api_client
):
    response = anonymous_api_client.post(
        "/api" + path, json={}, headers={"Origin": "https://foreign.example"}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "invalid_proof"
    assert response.headers["Cache-Control"] == "no-store"


def test_022_FR_017_schema_errors_never_reflect_secret_input(anonymous_api_client):
    secret = "do-not-reflect-secret"
    response = anonymous_api_client.post(
        "/api/auth/email/verify",
        json={"challenge_id": secret, "client_verifier": secret, "code": secret},
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert response.headers["Referrer-Policy"] == "no-referrer"


@pytest.fixture
def live_modern(anonymous_api_client, container):
    service, mail, sent, provider, clock = make_modern(container)
    anonymous_api_client.app.state.container = container
    anonymous_api_client.app.state.config = (
        anonymous_api_client.app.state.config.model_copy(
            update={"modern_auth": service.settings}
        )
    )
    container.modern_auth_service = service
    return anonymous_api_client, service, mail, sent, provider, clock


def test_022_FR_001_SC_001_email_http_signup_me_and_discovery_use_same_opaque_session(
    live_modern,
):
    client, _, mail, sent, _, _ = live_modern
    response = client.post(
        "/api/auth/email/request",
        json={
            "email": "http@example.com",
            "purpose": "login",
            "client": "web",
            "client_challenge": challenge(),
        },
        headers={"Origin": "https://app.example.com"},
    )
    assert response.status_code == 202
    assert mail.dispatch_one()
    completed = client.post(
        "/api/auth/email/verify",
        json={
            "challenge_id": response.json()["challenge_id"],
            "code": sent[-1][1],
            "client_verifier": VERIFIER,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "signed_in"
    assert "HttpOnly" in completed.headers["set-cookie"]
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == completed.json()["user"]
    assert me.json()["feature_flags"]
    methods = client.get("/api/account/auth-methods")
    assert methods.status_code == 200
    assert methods.json()["has_password"] is False
    assert methods.json()["email_verified"] is True


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_022_FR_019_foreign_fetch_metadata_and_non_json_fail_before_proof(
    live_modern, site
):
    client, *_ = live_modern
    response = client.post(
        "/api/auth/email/request",
        json={},
        headers={"Sec-Fetch-Site": site, "Origin": "https://app.example.com"},
    )
    assert response.status_code == 403
    response = client.post(
        "/api/auth/email/request", data="{}", headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 400
