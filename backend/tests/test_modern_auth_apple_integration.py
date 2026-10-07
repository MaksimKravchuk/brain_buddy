"""Apple broker glue retains grants and applies notices to current authority."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr

from app.schemas.modern_auth import (
    AppleNativeCompleteRequest,
    EmailRequest,
    ProviderStartRequest,
)
from app.services.auth_apple_lifecycle import AuthAppleLifecycle
from app.services.auth_provider_service import (
    AppleNotification,
    ProviderIdentity,
    ProviderTokens,
)
from app.services.modern_auth_service import ModernAuthError

from .test_modern_auth_service import VERIFIER, Provider, challenge, make_modern


class AppleProvider(Provider):
    def __init__(self, clock):
        super().__init__(clock)
        self.identity = ProviderIdentity(
            "apple",
            "https://appleid.apple.com",
            "native-subject",
            "relay@example.com",
            True,
            True,
            "com.example.native",
            int(clock().timestamp()),
        )
        self.received = []
        self.notification = AppleNotification(
            "signed-fixture-notice",
            "consent-revoked",
            self.identity.subject,
            self.identity.audience,
            int(clock().timestamp()) + 1,
            int(clock().timestamp()) + 1,
        )
        self.revocations = []

    def exchange_apple(self, code, *, nonce, native_identity_token):
        self.received.append((code, nonce, native_identity_token))
        return ProviderTokens(
            self.identity,
            self.identity.audience,
            SecretStr("synthetic-apple-revocation-token"),
            "refresh_token",
        )

    def verify_notification(self, payload):
        return self.notification

    def revoke_apple(self, token, issuing_client, *, token_type):
        self.revocations.append((token, issuing_client, token_type))


@pytest.fixture
def apple_runtime(container):
    service, mail, sent, _, clock = make_modern(container)
    key = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    service.settings = service.settings.model_copy(
        update={
            "apple_team_id": "TEAMID1234",
            "apple_key_id": "KEYID12345",
            "apple_private_key": SecretStr(key),
            "apple_services_id": "com.example.web",
            "apple_native_app_id": "com.example.native",
        }
    )
    provider = AppleProvider(clock)
    service.provider = provider
    service.apple = AuthAppleLifecycle(
        service.store, service.box, provider, clock=clock
    )
    return service, mail, sent, provider, clock


def native_login(service):
    start = service.start_provider(
        "apple",
        ProviderStartRequest(
            purpose="login", client="ios", client_challenge=challenge()
        ),
    )
    assert start.payload.authorization_url is None
    payload = AppleNativeCompleteRequest(
        attempt_id=start.payload.attempt_id,
        state=start.payload.state,
        authorization_code="synthetic-original-code",
        identity_token="synthetic-original-assertion",
        client_verifier=VERIFIER,
    )
    return service.complete_native_apple(payload), start, payload


def test_023_FR_003_FR_019_native_exchange_persists_only_sealed_revocation_grant(
    apple_runtime,
):
    service, _, _, provider, _ = apple_runtime
    result, start, payload = native_login(service)
    assert result.payload.status == "signed_in"
    assert provider.received == [
        (payload.authorization_code, start.payload.nonce, payload.identity_token)
    ]
    with service.store.connection() as connection:
        grants = connection.execute("SELECT * FROM auth_apple_grants").fetchall()
        assert len(grants) == 1
        assert grants[0]["issuing_client"] == "com.example.native"
        assert "synthetic-apple-revocation-token" not in grants[0]["sealed_payload"]
    assert (
        service.auth.get_user_for_token(result.raw_token).id == result.payload.user.id
    )
    with pytest.raises(ModernAuthError):
        service.complete_native_apple(payload)


def test_023_FR_019_relay_disabled_notice_removes_mail_login_and_reauth(apple_runtime):
    service, mail, _, provider, _ = apple_runtime
    result, _, _ = native_login(service)
    provider.notification = replace(
        provider.notification,
        event_type="email-disabled",
        email="relay@example.com",
        is_private_email=True,
    )
    service.process_apple_notification("synthetic-signed-notice")
    methods = service.account_methods(raw_token=result.raw_token)
    assert methods.email_delivery == "disabled"
    assert not next(
        method for method in methods.methods if method.method == "email"
    ).usable
    service.request_email(
        EmailRequest(
            email="relay@example.com",
            purpose="login",
            client="web",
            client_challenge=challenge(),
        ),
        network="relay",
    )
    assert not mail.dispatch_one()
    with pytest.raises(ModernAuthError):
        service.request_email(
            EmailRequest(
                email="relay@example.com",
                purpose="reauth",
                action="export",
                expected_account_id=result.payload.user.id,
                client="web",
                client_challenge=challenge(),
            ),
            network="relay",
            raw_token=result.raw_token,
        )


def test_023_FR_019_revoked_binding_has_safe_wire_state_and_fresh_consent_reactivates(
    apple_runtime,
):
    service, _, _, provider, clock = apple_runtime
    result, _, _ = native_login(service)
    email_token, _ = service.auth._create_session(
        result.payload.user.id, auth_method="email"
    )
    service.process_apple_notification("synthetic-signed-notice")
    assert service.auth.get_user_for_token(result.raw_token) is None
    methods = service.account_methods(raw_token=email_token)
    assert (
        next(method for method in methods.methods if method.method == "apple").state
        == "disabled"
    )
    clock.now += timedelta(seconds=2)
    provider.identity = replace(
        provider.identity, issued_at=int(clock().timestamp()), email=None
    )
    fresh, _, _ = native_login(service)
    assert fresh.payload.user.id == result.payload.user.id
    with service.store.connection() as connection:
        binding = connection.execute(
            "SELECT state,generation FROM auth_identity_bindings"
        ).fetchone()
        assert binding["state"] == "active"
        assert binding["generation"] == 2


def test_023_SC_005_purge_erases_personal_notice_receipts_under_retry(apple_runtime):
    service, _, _, provider, _ = apple_runtime
    result, _, _ = native_login(service)
    provider.notification = replace(
        provider.notification,
        event_type="email-disabled",
        email="relay@example.com",
        is_private_email=True,
    )
    service.process_apple_notification("synthetic-notice")
    with service.store.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM auth_apple_notification_receipts"
            ).fetchone()[0]
            == 1
        )
    service.account.purge_account(result.payload.user.id)
    service.account.purge_account(result.payload.user.id)
    with service.store.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM auth_apple_notification_receipts"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM auth_identity_bindings"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM auth_proofs").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM auth_apple_grants").fetchone()[0]
            == 0
        )
