"""Ephemeral real-app browser fixture; never import this from product code.

Run with explicit BRAIN_BUDDY_MODERN_E2E_{DATA_DIR,CAPTURE_FILE,ORIGIN} and
``uvicorn modern_auth_e2e_app:create_app --factory``. The runner supplies a
local TLS certificate and maps the validated fixture hostname to loopback.
All auth routes, origin checks, SQLite authority, mail activation and worker
lifecycle are the production implementations. Only provider HTTP and SMTP are
synthetic boundaries; codes never appear in an HTTP fixture endpoint.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import ECKey, RSAKey

_CLIENT_ID = "modern-e2e.apps.googleusercontent.com"
_PASSWORD = "E2E-modern-safe-password-123"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
_APPLE_TOKEN = "https://appleid.apple.com/auth/token"
_APPLE_JWKS = "https://appleid.apple.com/auth/keys"
_APPLE_CLIENT_ID = "com.example.modern-e2e.web"
_APPLE_TEAM_ID = "TEAM123456"
_APPLE_KEY_ID = "KEY1234567"


def _temporary_path(name: str) -> Path:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} must name an explicit ephemeral fixture path.")
    path = Path(value).resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if temporary_root != Path(os.path.sep) / "tmp":
        raise RuntimeError("The fixture requires the runner's /tmp temporary root.")
    if not path.is_relative_to(temporary_root) or not any(
        part.startswith("modern-auth-e2e") for part in path.parts[2:]
    ):
        raise RuntimeError("Modern auth E2E paths must be task-specific /tmp paths.")
    return path


class _SyntheticGoogle:
    """Sign upstream assertions after checking the real code exchange's PKCE."""

    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.key = RSAKey.generate_key(
            parameters={"kid": "modern-e2e-provider", "use": "sig", "alg": "RS256"}
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and str(request.url) == _GOOGLE_JWKS:
            return httpx.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if request.method != "POST" or str(request.url) != _GOOGLE_TOKEN:
            raise AssertionError(
                "An unexpected upstream request escaped the fixed fixture."
            )
        try:
            form = parse_qs(request.content.decode("ascii"), strict_parsing=True)
            if any(len(values) != 1 for values in form.values()):
                raise ValueError()
            code = form["code"][0]
            fixture = json.loads(
                base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
            )
            verifier = form["code_verifier"][0]
            digest = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(verifier.encode("ascii")).digest()
                )
                .rstrip(b"=")
                .decode("ascii")
            )
            if (
                form["grant_type"][0] != "authorization_code"
                or form["client_id"][0] != _CLIENT_ID
                or form["client_secret"][0] != "synthetic-google-client-secret"
                or form["redirect_uri"][0]
                != f"{self.origin}/api/auth/providers/google/callback"
                or not hmac.compare_digest(digest, fixture["pkce"])
                or any(
                    not isinstance(fixture[field], str) or not fixture[field]
                    for field in ("nonce", "subject", "email")
                )
            ):
                raise ValueError()
        except (ValueError, KeyError, TypeError, UnicodeError):
            return httpx.Response(400, json={"error": "invalid_grant"})
        now = int(time.time())
        token = jwt.encode(
            {"alg": "RS256", "kid": "modern-e2e-provider"},
            {
                "iss": "https://accounts.google.com",
                "aud": _CLIENT_ID,
                "sub": fixture["subject"],
                "nonce": fixture["nonce"],
                "email": fixture["email"],
                "email_verified": True,
                "iat": now - 1,
                "exp": now + 300,
            },
            self.key,
        )
        return httpx.Response(200, json={"id_token": token, "token_type": "Bearer"})


class _SyntheticApple:
    """Verify the real ES256 client secret and sign a pinned Apple assertion."""

    def __init__(self, origin: str, client_key: ECKey) -> None:
        self.origin = origin
        self.client_key = client_key
        self.key = RSAKey.generate_key(
            parameters={"kid": "modern-e2e-apple", "use": "sig", "alg": "RS256"}
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and str(request.url) == _APPLE_JWKS:
            return httpx.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if request.method != "POST" or str(request.url) != _APPLE_TOKEN:
            raise AssertionError("An unexpected Apple request escaped the fixture.")
        now = int(time.time())
        try:
            form = parse_qs(request.content.decode("ascii"), strict_parsing=True)
            if set(form) != {
                "grant_type",
                "client_id",
                "client_secret",
                "code",
                "redirect_uri",
            } or any(len(values) != 1 for values in form.values()):
                raise ValueError()
            secret = jwt.decode(
                form["client_secret"][0], self.client_key, algorithms=["ES256"]
            )
            issued, expires = secret.claims["iat"], secret.claims["exp"]
            if (
                secret.header.get("kid") != _APPLE_KEY_ID
                or secret.claims.get("iss") != _APPLE_TEAM_ID
                or secret.claims.get("sub") != _APPLE_CLIENT_ID
                or secret.claims.get("aud") != "https://appleid.apple.com"
                or not isinstance(issued, int)
                or not isinstance(expires, int)
                or not now - 60 <= issued <= now + 60
                or not now < expires <= issued + 300
                or form["grant_type"][0] != "authorization_code"
                or form["client_id"][0] != _APPLE_CLIENT_ID
                or form["redirect_uri"][0]
                != f"{self.origin}/api/auth/providers/apple/callback"
            ):
                raise ValueError()
            code = form["code"][0]
            fixture = json.loads(
                base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
            )
            if any(
                not isinstance(fixture[field], str) or not fixture[field]
                for field in ("nonce", "subject")
            ) or (
                fixture["email"] is not None
                and (not isinstance(fixture["email"], str) or not fixture["email"])
            ):
                raise ValueError()
        except (JoseError, ValueError, KeyError, TypeError, UnicodeError):
            return httpx.Response(400, json={"error": "invalid_grant"})
        claims = {
            "iss": "https://appleid.apple.com",
            "aud": _APPLE_CLIENT_ID,
            "sub": fixture["subject"],
            "nonce": fixture["nonce"],
            "iat": now - 1,
            "exp": now + 300,
        }
        if fixture["email"] is not None:
            claims.update(
                email=fixture["email"], email_verified="true", is_private_email="true"
            )
        token = jwt.encode(
            {"alg": "RS256", "kid": "modern-e2e-apple"}, claims, self.key
        )
        return httpx.Response(
            200,
            json={
                "id_token": token,
                "token_type": "Bearer",
                "refresh_token": "synthetic-apple-refresh-"
                + hashlib.sha256(code.encode("ascii")).hexdigest()[:24],
            },
        )


def create_app() -> FastAPI:
    """Configure one isolated process before importing the real ASGI app."""
    data_dir = _temporary_path("BRAIN_BUDDY_MODERN_E2E_DATA_DIR")
    capture = _temporary_path("BRAIN_BUDDY_MODERN_E2E_CAPTURE_FILE")
    origin = os.environ.get(
        "BRAIN_BUDDY_MODERN_E2E_ORIGIN", "https://brainbuddy-e2e.example.com:9443"
    )
    if urlsplit(origin).hostname != "brainbuddy-e2e.example.com":
        raise RuntimeError(
            "The E2E origin must use the runner's loopback-mapped fixture host."
        )
    if data_dir.exists() and any(data_dir.iterdir()):
        raise RuntimeError(
            "Start each E2E process with a fresh, empty fixture data directory."
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    capture.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(capture, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"):
        pass
    apple_client_key = ECKey.generate_key(
        parameters={"kid": _APPLE_KEY_ID, "use": "sig", "alg": "ES256"}
    )
    os.environ.update(
        {
            "BRAIN_BUDDY_ENV": "test",
            "BRAIN_BUDDY_DATA_DIR": str(data_dir),
            "BRAIN_BUDDY_AUTH_PUBLIC_ORIGIN": origin,
            "BRAIN_BUDDY_AUTH_API_ORIGIN": origin,
            "BRAIN_BUDDY_AUTH_CURRENT_KEY_ID": "e2e",
            "BRAIN_BUDDY_AUTH_KEYRING": json.dumps(
                {"e2e": base64.b64encode(os.urandom(32)).decode("ascii")}
            ),
            "BRAIN_BUDDY_AUTH_GOOGLE_CLIENT_ID": _CLIENT_ID,
            "BRAIN_BUDDY_AUTH_GOOGLE_CLIENT_SECRET": "synthetic-google-client-secret",
            "BRAIN_BUDDY_AUTH_APPLE_PRIVATE_KEY": apple_client_key.as_pem(
                private=True
            ).decode("ascii"),
            "BRAIN_BUDDY_AUTH_APPLE_KEY_ID": _APPLE_KEY_ID,
            "BRAIN_BUDDY_AUTH_APPLE_TEAM_ID": _APPLE_TEAM_ID,
            "BRAIN_BUDDY_AUTH_APPLE_SERVICES_ID": _APPLE_CLIENT_ID,
            "BRAIN_BUDDY_AUTH_APPLE_NATIVE_APP_ID": "",
            "BRAIN_BUDDY_AUTH_SMTP_HOST": "smtp.example.com",
            "BRAIN_BUDDY_AUTH_SMTP_SENDER": "signin@example.com",
            "BRAIN_BUDDY_AUTH_SMTP_USERNAME": "synthetic",
            "BRAIN_BUDDY_AUTH_SMTP_PASSWORD": "synthetic",
            "BRAIN_BUDDY_AUTH_SMTP_PORT": "587",
            "BRAIN_BUDDY_AUTH_SMTP_TLS": "starttls",
            "BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS": "",
            "BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST": "1",
        }
    )
    os.environ.pop("BRAIN_BUDDY_ADMIN_EMAIL", None)
    os.environ.pop("BRAIN_BUDDY_ADMIN_PASSWORD", None)
    # Configure before importing app.main; reuse its single app so no second
    # default SMTP worker can race this fixture's captured mail delivery.
    from app.core.config import AppEnvironment
    from app.main import app as application
    from app.schemas.auth import User
    from app.services.auth_mail_service import AuthMailService
    from app.services.auth_provider_service import AuthProviderService
    from app.utils.time import utcnow

    config = application.state.config
    if config.environment is not AppEnvironment.TEST or config.data_dir != data_dir:
        raise RuntimeError("The real app was imported before ephemeral configuration.")
    settings = config.modern_auth
    if (
        not settings.google_available
        or not settings.apple_web_available
        or not settings.email_available
    ):
        raise RuntimeError(
            "The fixture must pass the real modern-auth settings validator."
        )
    container = application.state.container
    modern = container.modern_auth_service
    modern.provider.close()
    google = _SyntheticGoogle(origin)
    apple = _SyntheticApple(origin, apple_client_key)

    def provider_boundary(request: httpx.Request) -> httpx.Response:
        if request.url.host == "appleid.apple.com":
            return apple(request)
        return google(request)

    upstream = httpx.Client(transport=httpx.MockTransport(provider_boundary))
    modern.provider = AuthProviderService(settings, client=upstream)
    apple_lifecycle = container.account_service.apple_lifecycle
    if apple_lifecycle is None:
        raise RuntimeError("The real app must wire the Apple credential lifecycle.")
    apple_lifecycle.gateway = modern.provider
    application.router.add_event_handler("shutdown", upstream.close)

    def capture_mail(recipient: str, code: str, purpose: str) -> None:
        message = (
            json.dumps(
                {"recipient": recipient, "code": code, "purpose": purpose},
                separators=(",", ":"),
            )
            + "\n"
        )
        with os.fdopen(
            os.open(capture, os.O_WRONLY | os.O_APPEND, 0o600), "w"
        ) as stream:
            stream.write(message)

    modern.mail = AuthMailService(modern.store, modern.box, settings, send=capture_mail)
    # These initial states are synthetic database fixtures, not auth endpoints:
    # one unverified legacy collision, one already-verified recovery account,
    # and two password owners for a real cookie-switch rejection.
    for email in (
        "legacy-modern-e2e@gmail.com",
        "recovery-modern-e2e@example.com",
        "stale-modern-e2e@example.com",
        "other-modern-e2e@example.com",
    ):
        if container.user_repo.get_by_email(email) is None:
            container.user_repo.create(
                User(
                    id="user_e2e_" + hashlib.sha256(email.encode()).hexdigest()[:12],
                    email=email,
                    password_hash=container.auth_service.hash_password(_PASSWORD),
                    created_at=utcnow(),
                    email_verified_at=(
                        utcnow() if email.startswith("recovery-") else None
                    ),
                )
            )

    distribution = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if not (distribution / "index.html").is_file():
        raise RuntimeError(
            "Build the real frontend bundle before starting this fixture."
        )
    application.mount(
        "/assets", StaticFiles(directory=distribution / "assets"), name="e2e-assets"
    )

    @application.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(distribution / "index.html")

    return application
