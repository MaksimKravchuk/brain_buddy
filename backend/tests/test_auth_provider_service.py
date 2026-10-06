"""Real JWT signatures and synthetic transports for provider trust profiles."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from joserfc import jwt
from joserfc.jwk import ECKey, OctKey, RSAKey
from pydantic import SecretStr

from app.core.config import ModernAuthSettings
from app.services.auth_provider_service import AuthProviderService, ProviderError

NOW = 1_800_000_000
VERIFIER = "v" * 43
NONCE = "synthetic-raw-nonce"


@pytest.fixture(scope="module")
def rsa_key() -> RSAKey:
    return RSAKey.generate_key(
        parameters={"kid": "provider-key", "use": "sig", "alg": "RS256"}
    )


@pytest.fixture(scope="module")
def apple_key() -> ECKey:
    return ECKey.generate_key(
        parameters={"kid": "KEY1234567", "use": "sig", "alg": "ES256"}
    )


def settings(apple_key: ECKey) -> ModernAuthSettings:
    return ModernAuthSettings(
        public_origin="https://app.example.com",
        api_origin="https://api.example.com",
        current_key_id="key",
        keyring={"key": SecretStr(base64.b64encode(b"x" * 32).decode())},
        google_client_id="synthetic.apps.googleusercontent.com",
        google_client_secret=SecretStr("synthetic-google-secret"),
        apple_team_id="TEAM123456",
        apple_key_id="KEY1234567",
        apple_private_key=SecretStr(apple_key.as_pem(private=True).decode()),
        apple_services_id="com.example.web",
        apple_native_app_id="com.example.app",
    )


def claims(provider: str = "google", **changes: Any) -> dict[str, Any]:
    return {
        "iss": (
            "https://accounts.google.com"
            if provider == "google"
            else "https://appleid.apple.com"
        ),
        "aud": (
            "synthetic.apps.googleusercontent.com"
            if provider == "google"
            else "com.example.web"
        ),
        "sub": "stable-synthetic-subject",
        "iat": NOW - 5,
        "exp": NOW + 300,
        "nonce": NONCE,
        "email": (
            "person@gmail.com"
            if provider == "google"
            else "person@privaterelay.appleid.com"
        ),
        "email_verified": True,
        **changes,
    }


def assertion(key: RSAKey, values: dict[str, Any], **headers: Any) -> str:
    return jwt.encode({"alg": "RS256", "kid": "provider-key", **headers}, values, key)


def gateway(
    rsa_key: RSAKey,
    apple_key: ECKey,
    token: str,
    *,
    extra: dict[str, Any] | None = None,
    transport_status: int = 200,
) -> tuple[AuthProviderService, list[httpx.Request], list[float]]:
    requests: list[httpx.Request] = []
    clock = [float(NOW)]

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/certs") or request.url.path.endswith("/keys"):
            return httpx.Response(200, json={"keys": [rsa_key.as_dict()]})
        if request.url.path.endswith("/revoke"):
            return httpx.Response(transport_status)
        return httpx.Response(
            transport_status, json={"id_token": token, **(extra or {})}
        )

    service = AuthProviderService(
        settings(apple_key),
        client=httpx.Client(transport=httpx.MockTransport(upstream)),
        clock=lambda: clock[0],
    )
    return service, requests, clock


def exchange_google(service: AuthProviderService) -> Any:
    return service.exchange_google(
        "synthetic-one-use-code",
        redirect_uri=service.callback_uri("google"),
        pkce_verifier=VERIFIER,
        nonce=NONCE,
    )


def test_023_FR_004_google_exchange_proves_signature_claims_and_fixed_transport(
    rsa_key: RSAKey, apple_key: ECKey
) -> None:
    """A valid signed Google identity uses the pinned exchange and JWKS endpoints."""
    service, requests, _ = gateway(
        rsa_key,
        apple_key,
        assertion(rsa_key, claims()),
        extra={"access_token": "discard-access", "refresh_token": "discard-refresh"},
    )
    result = exchange_google(service)
    assert result.identity.subject == "stable-synthetic-subject"
    assert result.identity.issuer == "https://accounts.google.com"
    assert result.identity.email_authoritative
    assert result.revocation_token is None
    assert [str(request.url) for request in requests] == [
        "https://oauth2.googleapis.com/token",
        "https://www.googleapis.com/oauth2/v3/certs",
    ]
    form = parse_qs(requests[0].content.decode())
    assert form["code_verifier"] == [VERIFIER]
    assert form["client_secret"] == ["synthetic-google-secret"]
    assert all(
        request.extensions["timeout"]
        == {"connect": 10.0, "read": 10.0, "write": 10.0, "pool": 10.0}
        for request in requests
    )
    assert "person@gmail.com" not in repr(result)
    assert "stable-synthetic-subject" not in repr(result)


def test_023_FR_004_authorization_urls_use_google_s256_and_apple_form_post(
    rsa_key: RSAKey, apple_key: ECKey
) -> None:
    """Provider URLs request minimal identity scopes with exact configured callbacks."""
    service, _, _ = gateway(rsa_key, apple_key, "unused")
    url = service.authorization_url(
        "google",
        state="state",
        nonce=NONCE,
        redirect_uri=service.callback_uri("google"),
        pkce_verifier=VERIFIER,
    )
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        == "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert query["scope"] == ["openid email"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [
        base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
        .rstrip(b"=")
        .decode()
    ]
    assert "access_type" not in query and "client_secret" not in query
    apple_url = service.authorization_url(
        "apple", state="state", nonce=NONCE, redirect_uri=service.callback_uri("apple")
    )
    apple_query = parse_qs(urlsplit(apple_url).query)
    assert apple_url.startswith("https://appleid.apple.com/auth/authorize?")
    assert apple_query["response_mode"] == ["form_post"]
    assert apple_query["scope"] == ["email"]
    assert apple_query["nonce"] == [NONCE]
    assert "code_challenge" not in apple_query


@pytest.mark.parametrize(
    "redirect",
    [
        "https://attacker.example/callback",
        "https://api.example.com/other",
        "https://api.example.com/api/auth/providers/google/callback?next=bad",
    ],
)
def test_023_FR_004_unconfigured_callback_destinations_are_rejected(
    rsa_key: RSAKey, apple_key: ECKey, redirect: str
) -> None:
    """Neither authorization nor exchange accepts a request-selected callback."""
    service, requests, _ = gateway(rsa_key, apple_key, "unused")
    with pytest.raises(ProviderError):
        service.authorization_url(
            "google",
            state="state",
            nonce=NONCE,
            redirect_uri=redirect,
            pkce_verifier=VERIFIER,
        )
    with pytest.raises(ProviderError):
        service.exchange_google(
            "code", redirect_uri=redirect, pkce_verifier=VERIFIER, nonce=NONCE
        )
    assert requests == []


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://attacker.example"},
        {"aud": "other-client"},
        {"azp": "other-client"},
        {"aud": ["synthetic.apps.googleusercontent.com", "other-client"]},
        {"nonce": "other-nonce"},
        {"exp": NOW - 61},
        {"exp": True},
        {"iat": NOW + 61},
        {"iat": "1800000000"},
        {"sub": ""},
        {"sub": "x" * 256},
        {"sub": True},
        {"email_verified": "true"},
        {"email_verified": "false"},
        {"nbf": NOW + 61},
    ],
)
def test_023_FR_004_invalid_signed_claims_never_authorize(
    rsa_key: RSAKey, apple_key: ECKey, change: dict[str, Any]
) -> None:
    """Signed but wrong issuer, audience, nonce, time, subject or boolean claims fail."""
    service, _, _ = gateway(rsa_key, apple_key, assertion(rsa_key, claims(**change)))
    with pytest.raises(ProviderError):
        exchange_google(service)


@pytest.mark.parametrize("missing", ["iss", "aud", "sub", "iat", "exp", "nonce"])
def test_023_FR_004_required_login_claims_cannot_be_omitted(
    rsa_key: RSAKey, apple_key: ECKey, missing: str
) -> None:
    """Every login identity must include its exact authority and time bindings."""
    values = claims()
    del values[missing]
    service, _, _ = gateway(rsa_key, apple_key, assertion(rsa_key, values))
    with pytest.raises(ProviderError):
        exchange_google(service)


@pytest.mark.parametrize(
    "header",
    [
        {"jku": "https://attacker.example/keys"},
        {"x5u": "https://attacker.example/cert"},
        {"jwk": {"kty": "RSA"}},
    ],
)
def test_023_FR_004_header_selected_keys_are_rejected_without_fetch(
    rsa_key: RSAKey, apple_key: ECKey, header: dict[str, Any]
) -> None:
    """Token headers cannot choose a key source or cause attacker-directed HTTP."""
    service, requests, _ = gateway(
        rsa_key, apple_key, assertion(rsa_key, claims(), **header)
    )
    with pytest.raises(ProviderError):
        exchange_google(service)
    assert len(requests) == 1


@pytest.mark.parametrize("algorithm", ["HS256", "none"])
def test_023_FR_004_unsupported_signature_algorithms_fail_before_jwks(
    rsa_key: RSAKey, apple_key: ECKey, algorithm: str
) -> None:
    """Unsigned and symmetric assertions are never accepted as provider identity."""
    key = (
        OctKey.import_key("synthetic-key-with-at-least-32-bytes")
        if algorithm == "HS256"
        else None
    )
    token = jwt.encode({"alg": algorithm, "kid": "provider-key"}, claims(), key, algorithms=[algorithm])  # type: ignore[arg-type]
    service, requests, _ = gateway(rsa_key, apple_key, token)
    with pytest.raises(ProviderError):
        exchange_google(service)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "email,hd,verified,authoritative",
    [
        ("person@gmail.com", None, True, True),
        ("person@googlemail.com", None, True, True),
        ("person@gmail.com", None, False, False),
        ("person@external.example", None, True, False),
        ("person@workspace.example", "workspace.example", True, True),
        ("person@workspace.example", "https://workspace.example", True, False),
        ("person@workspace.example", "*.workspace.example", True, False),
        ("person@workspace.example", "bad..example", True, False),
    ],
)
def test_023_FR_004_google_mailbox_authority_requires_google_or_signed_valid_workspace(
    rsa_key: RSAKey,
    apple_key: ECKey,
    email: str,
    hd: str | None,
    verified: bool,
    authoritative: bool,
) -> None:
    """Third-party verified email is not mailbox authority without valid signed hd."""
    values = claims(email=email, email_verified=verified)
    if hd is not None:
        values["hd"] = hd
    service, _, _ = gateway(rsa_key, apple_key, assertion(rsa_key, values))
    assert exchange_google(service).identity.email_authoritative is authoritative


def test_023_FR_004_google_issuer_alias_and_explicit_multi_audience_party(
    rsa_key: RSAKey, apple_key: ECKey
) -> None:
    """Recognized Google issuer aliases normalize and multiple audiences require azp."""
    values = claims(
        iss="accounts.google.com",
        aud=["synthetic.apps.googleusercontent.com", "other"],
        azp="synthetic.apps.googleusercontent.com",
    )
    service, _, _ = gateway(rsa_key, apple_key, assertion(rsa_key, values))
    assert exchange_google(service).identity.issuer == "https://accounts.google.com"


def test_023_FR_004_jwks_cache_expiry_and_unknown_key_refresh_are_bounded(
    rsa_key: RSAKey, apple_key: ECKey
) -> None:
    """Known keys cache for one hour and unknown IDs cannot amplify key fetching."""
    current_token = [assertion(rsa_key, claims())]
    requests: list[httpx.Request] = []
    clock = [float(NOW)]

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [rsa_key.as_dict()]})
        return httpx.Response(200, json={"id_token": current_token[0]})

    service = AuthProviderService(
        settings(apple_key),
        client=httpx.Client(transport=httpx.MockTransport(transport)),
        clock=lambda: clock[0],
    )
    exchange_google(service)
    exchange_google(service)
    assert sum(request.url.path.endswith("/certs") for request in requests) == 1
    current_token[0] = assertion(rsa_key, claims(), kid="unknown")
    for _ in range(3):
        with pytest.raises(ProviderError):
            exchange_google(service)
    assert sum(request.url.path.endswith("/certs") for request in requests) == 1
    clock[0] += 60
    for _ in range(3):
        with pytest.raises(ProviderError):
            exchange_google(service)
    assert sum(request.url.path.endswith("/certs") for request in requests) == 2
    clock[0] = NOW + 3661
    current_token[0] = assertion(rsa_key, claims(iat=NOW + 3600, exp=NOW + 4000))
    exchange_google(service)
    assert sum(request.url.path.endswith("/certs") for request in requests) == 3


def test_023_FR_025_apple_exchange_signs_short_lived_secret_and_returns_only_revocation_grant(
    rsa_key: RSAKey, apple_key: ECKey
) -> None:
    """Apple confidential exchange uses ES256 and protects its transient cleanup grant."""
    token = assertion(
        rsa_key, claims("apple", email_verified="true", is_private_email="true")
    )
    service, requests, _ = gateway(
        rsa_key,
        apple_key,
        token,
        extra={
            "refresh_token": "synthetic-refresh",
            "access_token": "synthetic-access",
        },
    )
    result = service.exchange_apple(
        "synthetic-apple-code", redirect_uri=service.callback_uri("apple"), nonce=NONCE
    )
    assert result.identity.provider == "apple"
    assert result.identity.email_authoritative and result.identity.is_private_email
    assert result.revocation_token is not None
    assert result.revocation_token.get_secret_value() == "synthetic-refresh"
    assert result.revocation_token_type == "refresh_token"
    assert result.issuing_client == "com.example.web"
    assert "synthetic-refresh" not in repr(result)
    assert str(requests[0].url) == "https://appleid.apple.com/auth/token"
    assert str(requests[1].url) == "https://appleid.apple.com/auth/keys"
    form = parse_qs(requests[0].content.decode())
    secret = jwt.decode(form["client_secret"][0], apple_key, algorithms=["ES256"])
    assert secret.header["kid"] == "KEY1234567"
    assert secret.claims["iss"] == "TEAM123456"
    assert secret.claims["sub"] == "com.example.web"
    assert secret.claims["aud"] == "https://appleid.apple.com"
    assert secret.claims["exp"] - secret.claims["iat"] <= 300
    assert "code_verifier" not in form


def test_023_FR_025_apple_identity_without_revocation_grant_fails_closed(
    rsa_key: RSAKey, apple_key: ECKey
) -> None:
    """Apple exchange cannot establish authority without its required cleanup credential."""
    service, _, _ = gateway(rsa_key, apple_key, assertion(rsa_key, claims("apple")))
    with pytest.raises(ProviderError):
        service.exchange_apple(
            "code", nonce=NONCE, redirect_uri=service.callback_uri("apple")
        )


def test_023_FR_004_wrong_rsa_signature_cannot_authorize_valid_claims(
    rsa_key: RSAKey, apple_key: ECKey
) -> None:
    """A valid-looking assertion signed by another RSA key fails cryptographic proof."""
    foreign_key = RSAKey.generate_key()
    service, _, _ = gateway(rsa_key, apple_key, assertion(foreign_key, claims()))
    with pytest.raises(ProviderError):
        exchange_google(service)


@pytest.mark.parametrize(
    "failure", ["timeout", "oversized", "redirect", "duplicate-key", "wrong-algorithm"]
)
def test_023_FR_004_unusable_jwks_fails_closed_and_refresh_failure_is_throttled(
    rsa_key: RSAKey, apple_key: ECKey, failure: str
) -> None:
    """Failed or malformed key responses cannot authorize or amplify repeated key fetches."""
    requests: list[httpx.Request] = []
    token = assertion(rsa_key, claims())

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"id_token": token})
        if failure == "timeout":
            raise httpx.ReadTimeout(
                "synthetic-sensitive-upstream-error", request=request
            )
        if failure == "oversized":
            return httpx.Response(200, content=b" " * 262_145)
        if failure == "redirect":
            return httpx.Response(
                302, headers={"location": "https://attacker.example/keys"}
            )
        if failure == "duplicate-key":
            return httpx.Response(
                200, json={"keys": [rsa_key.as_dict(), rsa_key.as_dict()]}
            )
        return httpx.Response(
            200, json={"keys": [{**rsa_key.as_dict(), "alg": "HS256"}]}
        )

    service = AuthProviderService(
        settings(apple_key),
        client=httpx.Client(transport=httpx.MockTransport(transport)),
        clock=lambda: float(NOW),
    )
    for _ in range(2):
        with pytest.raises(ProviderError) as error:
            exchange_google(service)
        assert "synthetic-sensitive" not in str(error.value)
    assert sum(request.url.path.endswith("/certs") for request in requests) == 1


@pytest.mark.parametrize("mismatch", ["sub", "aud", "nonce"])
def test_023_FR_004_apple_native_original_and_exchange_assertions_must_agree(
    rsa_key: RSAKey, apple_key: ECKey, mismatch: str
) -> None:
    """Native Apple exchanges every code and rejects inconsistent signed assertions."""
    original = assertion(rsa_key, claims("apple", aud="com.example.app"))
    exchanged = claims("apple", aud="com.example.app")
    exchanged[mismatch] = "foreign-value"
    service, _, _ = gateway(rsa_key, apple_key, assertion(rsa_key, exchanged))
    with pytest.raises(ProviderError):
        service.exchange_apple(
            "synthetic-native-code", nonce=NONCE, native_identity_token=original
        )


def test_023_FR_004_native_apple_accepts_raw_nonce_and_optional_returning_email(
    rsa_key: RSAKey, apple_key: ECKey
) -> None:
    """Native returning identities do not require a repeated profile or hashed nonce."""
    values = claims("apple", aud="com.example.app")
    del values["email"]
    del values["email_verified"]
    token = assertion(rsa_key, values)
    service, requests, _ = gateway(
        rsa_key, apple_key, token, extra={"access_token": "synthetic-access"}
    )
    result = service.exchange_apple(
        "synthetic-native-code", nonce=NONCE, native_identity_token=token
    )
    assert result.identity.email is None
    assert result.identity.audience == "com.example.app"
    assert result.revocation_token_type == "access_token"
    form = parse_qs(
        next(
            request.content.decode()
            for request in requests
            if request.url.path.endswith("/token")
        )
    )
    assert form["client_id"] == ["com.example.app"]
    assert "redirect_uri" not in form


@pytest.mark.parametrize("status", [302, 400, 503])
def test_023_FR_021_provider_errors_are_generic_and_code_exchange_is_never_retried(
    rsa_key: RSAKey, apple_key: ECKey, status: int
) -> None:
    """Upstream errors and redirects expose no code or provider body and are not retried."""
    service, requests, _ = gateway(
        rsa_key, apple_key, "synthetic-sensitive-assertion", transport_status=status
    )
    with pytest.raises(ProviderError) as error:
        exchange_google(service)
    assert str(error.value) == "Provider authentication could not be completed."
    assert len(requests) == 1
    assert error.value.__cause__ is None


def notification_claims(**changes: Any) -> dict[str, Any]:
    return {
        "iss": "https://appleid.apple.com",
        "aud": "com.example.web",
        "iat": NOW - 5,
        "jti": "synthetic-event-id",
        "events": json.dumps(
            {
                "type": "consent-revoked",
                "sub": "stable-synthetic-subject",
                "event_time": NOW - 10,
            }
        ),
        **changes,
    }


def test_023_FR_025_signed_apple_notification_has_separate_optional_exp_profile(
    rsa_key: RSAKey, apple_key: ECKey
) -> None:
    """Authentic bounded Apple notices do not require login nonce or undocumented exp."""
    service, _, _ = gateway(rsa_key, apple_key, "unused")
    notice = service.verify_notification(assertion(rsa_key, notification_claims()))
    assert notice.event_type == "consent-revoked"
    assert notice.subject == "stable-synthetic-subject"
    assert notice.jti == "synthetic-event-id"
    assert notice.event_time == NOW - 10
    assert "stable-synthetic-subject" not in repr(notice)


@pytest.mark.parametrize(
    "change",
    [
        {"exp": NOW - 61},
        {"exp": True},
        {"aud": "foreign-app"},
        {"iss": "https://attacker.example"},
        {"iat": NOW - 7 * 86400 - 61},
        {"iat": NOW - 7 * 86400 - 1},
        {"iat": NOW + 61},
        {"jti": ""},
        {
            "events": json.dumps(
                {"type": "account-delete", "sub": "subject", "event_time": NOW - 10}
            )
        },
        {
            "events": json.dumps(
                {
                    "type": "account-deleted",
                    "sub": "subject",
                    "event_time": NOW - 7 * 86400 - 61,
                }
            )
        },
        {
            "events": json.dumps(
                {
                    "type": "account-deleted",
                    "sub": "subject",
                    "event_time": NOW - 7 * 86400 - 1,
                }
            )
        },
    ],
)
def test_023_FR_025_invalid_stale_or_malformed_notification_is_rejected(
    rsa_key: RSAKey, apple_key: ECKey, change: dict[str, Any]
) -> None:
    """The signed notification profile enforces audience, age, event spelling and optional expiry."""
    service, _, _ = gateway(rsa_key, apple_key, "unused")
    with pytest.raises(ProviderError):
        service.verify_notification(assertion(rsa_key, notification_claims(**change)))


def test_023_FR_025_stateless_apple_revoke_uses_original_issuing_client(
    rsa_key: RSAKey, apple_key: ECKey
) -> None:
    """Revocation transport signs for the configured issuing client without storing the grant."""
    service, requests, _ = gateway(rsa_key, apple_key, "unused")
    service.revoke_apple(SecretStr("synthetic-refresh"), "com.example.app")
    assert len(requests) == 1
    assert str(requests[0].url) == "https://appleid.apple.com/auth/revoke"
    form = parse_qs(requests[0].content.decode())
    assert form["token"] == ["synthetic-refresh"]
    assert form["token_type_hint"] == ["refresh_token"]
    assert form["client_id"] == ["com.example.app"]
    with pytest.raises(ProviderError):
        service.revoke_apple("synthetic-refresh", "attacker-client")
    assert len(requests) == 1


def test_023_FR_003_unconfigured_providers_fail_without_external_requests() -> None:
    """Unavailable settings cannot authorize provider HTTP even when called directly."""
    requests: list[httpx.Request] = []

    def fail_transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("Unconfigured method made an external request")

    service = AuthProviderService(
        ModernAuthSettings(),
        client=httpx.Client(transport=httpx.MockTransport(fail_transport)),
        clock=lambda: float(NOW),
    )
    with pytest.raises(ProviderError):
        service.exchange_google(
            "code",
            redirect_uri="https://api.example.com/callback",
            pkce_verifier=VERIFIER,
            nonce=NONCE,
        )
    with pytest.raises(ProviderError):
        service.exchange_apple("code", nonce=NONCE)
    assert requests == []
