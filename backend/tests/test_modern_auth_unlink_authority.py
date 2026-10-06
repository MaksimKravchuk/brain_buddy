"""Explicit Remove ends identity authority while preserving fresh owner-bound links."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import allure
import pytest
from pydantic import SecretStr

from app.repositories.auth_metadata import AuthMetadataRepository
from app.schemas.modern_auth import (
    AccountActionRequest,
    AppleNativeCompleteRequest,
    PasswordConfirmRequest,
    ProviderCompleteRequest,
    ProviderStartRequest,
)
from app.services.auth_provider_service import ProviderTokens
from app.services.modern_auth_service import ModernAuthError
from tests import test_modern_auth_apple_integration as apple
from tests import test_modern_auth_service as broker

modern = broker.modern
apple_runtime = apple.apple_runtime
PASSWORD = "synthetic-independent-password"

pytestmark = [
    allure.epic("Authentication & access"),
    allure.feature("Explicit identity removal"),
    allure.story("023-FR-006/018/025; 023-SC-003/005"),
]


def owner_with_binding(service, provider, clock):
    owner = service.auth.seed_admin(email=provider.identity.email, password=PASSWORD)
    _, token, _ = service.auth.login(email=owner.email, password=PASSWORD)
    with service.store.transaction() as connection:
        identity = provider.identity
        connection.execute(
            "INSERT INTO auth_identity_bindings(id,user_id,provider,issuer,namespace,subject,created_at,updated_at,email,email_verified,is_private_email,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "original_binding",
                owner.id,
                identity.provider,
                identity.issuer,
                identity.namespace,
                identity.subject,
                clock().isoformat(),
                clock().isoformat(),
                identity.email,
                1,
                int(identity.is_private_email),
                json.dumps(
                    {
                        "provider_profile": "private metadata",
                        "email_delivery_disabled": True,
                    }
                ),
            ),
        )
        if identity.provider == "apple":
            service.apple.record_grant(
                connection,
                "original_binding",
                ProviderTokens(
                    identity,
                    identity.audience,
                    SecretStr("synthetic-revoke"),
                    "refresh_token",
                ),
            )
    return owner, token


def password_proof(service, owner, token, action):
    return service.confirm_password(
        PasswordConfirmRequest(
            current_password=PASSWORD, expected_account_id=owner.id, action=action
        ),
        raw_token=token,
    ).recent_proof


def remove(service, owner, token, provider):
    return service.unlink(
        provider,
        AccountActionRequest(
            expected_account_id=owner.id,
            recent_proof=password_proof(service, owner, token, f"unlink:{provider}"),
        ),
        raw_token=token,
    )


def google_link(service, owner, token):
    start = service.start_provider(
        "google",
        ProviderStartRequest(
            purpose="link",
            client="web",
            client_challenge=broker.challenge(),
            expected_account_id=owner.id,
            action="link:google",
            recent_proof=password_proof(service, owner, token, "link:google"),
        ),
        raw_token=token,
    )
    returned = service.provider_callback(
        "google", code="synthetic-code", state=start.payload.state, binder=start.binder
    )
    parameters = parse_qs(urlsplit(returned.url).fragment)
    return service.complete_provider(
        ProviderCompleteRequest(
            attempt_id=parameters["attempt"][0],
            state=parameters["state"][0],
            handoff_code=parameters["grant"][0],
            client_verifier=broker.VERIFIER,
        ),
        raw_token=token,
    )


def apple_link(service, owner, token):
    start = service.start_provider(
        "apple",
        ProviderStartRequest(
            purpose="link",
            client="ios",
            client_challenge=broker.challenge(),
            expected_account_id=owner.id,
            action="link:apple",
            recent_proof=password_proof(service, owner, token, "link:apple"),
        ),
        raw_token=token,
    )
    return service.complete_native_apple(
        AppleNativeCompleteRequest(
            attempt_id=start.payload.attempt_id,
            state=start.payload.state,
            authorization_code="synthetic-code",
            identity_token="synthetic-assertion",
            client_verifier=broker.VERIFIER,
        ),
        raw_token=token,
    )


def binding(service):
    with service.store.connection() as connection:
        return connection.execute("SELECT * FROM auth_identity_bindings").fetchone()


def test_023_fr006_removed_google_cannot_restore_old_owner_by_public_login(modern):
    """Fresh public provider proof after Remove requires existing-account authentication."""
    service, _, _, provider, clock = modern
    owner, token = owner_with_binding(service, provider, clock)
    remove(service, owner, token, "google")
    result = service.complete_provider(broker.provider_handoff(service))
    assert result.payload.status == "existing_account_required"
    assert result.raw_token is None
    assert binding(service) is None
    assert service.auth.get_user_for_token(token).id == owner.id


def test_023_fr006_unlink_erases_binding_account_proofs_and_staged_handoff(modern):
    """Remove erases old provider linkage and account confirmations together."""
    service, _, _, provider, clock = modern
    owner, token = owner_with_binding(service, provider, clock)
    staged = broker.provider_handoff(service)
    password_proof(service, owner, token, "export")
    remove(service, owner, token, "google")
    assert binding(service) is None
    with service.store.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM auth_proofs WHERE user_id=?", (owner.id,)
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM auth_attempts WHERE id=?", (staged.attempt_id,)
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT count(*) FROM auth_handoffs").fetchone()[0] == 0
        )
    with pytest.raises(ModernAuthError):
        service.complete_provider(staged)


def test_023_fr006_fresh_explicit_google_relink_cannot_revive_pre_unlink_handoff(
    modern,
):
    """Fresh owner-bound linking creates new authority; an old handoff cannot cross it."""
    service, _, _, provider, clock = modern
    owner, token = owner_with_binding(service, provider, clock)
    staged = broker.provider_handoff(service)
    remove(service, owner, token, "google")
    linked = google_link(service, owner, token)
    assert linked.payload.status == "linked" and linked.raw_token is None
    assert binding(service)["id"] != "original_binding"
    with pytest.raises(ModernAuthError):
        service.complete_provider(staged)
    fresh = service.complete_provider(broker.provider_handoff(service))
    assert fresh.payload.user.id == owner.id


def test_023_fr025_removed_apple_cannot_restore_old_owner_by_public_login(
    apple_runtime,
):
    """Pending Apple cleanup linkage carries no public login authority after Remove."""
    service, _, _, provider, clock = apple_runtime
    owner, token = owner_with_binding(service, provider, clock)
    remove(service, owner, token, "apple")
    clock.now += timedelta(seconds=2)
    provider.identity = replace(provider.identity, issued_at=int(clock().timestamp()))
    result, _, _ = apple.native_login(service)
    assert result.payload.status == "existing_account_required"
    assert result.raw_token is None
    assert binding(service)["state"] == "unlinked"
    assert service.auth.get_user_for_token(token).id == owner.id


def test_023_fr018_apple_unlink_keeps_only_bounded_cleanup_metadata(apple_runtime):
    """An unlinked Apple row retains only stable cleanup dimensions and its bounded deadline."""
    service, _, _, provider, clock = apple_runtime
    owner, token = owner_with_binding(service, provider, clock)
    password_proof(service, owner, token, "export")
    remove(service, owner, token, "apple")
    row = binding(service)
    assert row["state"] == "unlinked"
    assert (
        row["email"] is None and row["email_verified"] == row["is_private_email"] == 0
    )
    assert json.loads(row["payload_json"]) == {
        "unlinked_expires_at": (clock() + timedelta(hours=24)).isoformat()
    }
    with service.store.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM auth_proofs WHERE user_id=?", (owner.id,)
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("outcome", ["delivered", "expired", "missing_key"])
def test_023_fr018_terminal_apple_cleanup_erases_unlinked_mapping(
    apple_runtime, outcome
):
    """Terminal or expired revocation work erases the unlinked subject-to-owner mapping."""
    service, _, _, provider, clock = apple_runtime
    owner, token = owner_with_binding(service, provider, clock)
    provider.notification = replace(
        provider.notification,
        event_type="email-enabled",
        email=provider.identity.email,
        is_private_email=True,
    )
    service.process_apple_notification("synthetic signed email notice")
    with service.store.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM auth_apple_notification_receipts"
            ).fetchone()[0]
            == 1
        )
    if outcome == "missing_key":
        service.apple.secret_box = None
    remove(service, owner, token, "apple")
    if outcome == "delivered":
        assert service.apple.dispatch_one()
    elif outcome == "expired":
        clock.now += timedelta(hours=24, seconds=1)
        AuthMetadataRepository(service.store.root, service.store).cleanup_expired(
            now=clock()
        )
    assert binding(service) is None
    with service.store.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM auth_apple_cleanup_jobs"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT count(*) FROM auth_apple_grants").fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM auth_apple_notification_receipts"
            ).fetchone()[0]
            == 0
        )
    assert service.auth.get_user_for_token(token).id == owner.id


def test_023_fr025_fresh_explicit_apple_link_cancels_obsolete_cleanup_safely(
    apple_runtime,
):
    """Authenticated fresh consent reconnects the same owner and survives old cleanup expiry."""
    service, _, _, provider, clock = apple_runtime
    owner, token = owner_with_binding(service, provider, clock)
    remove(service, owner, token, "apple")
    clock.now += timedelta(seconds=2)
    provider.identity = replace(provider.identity, issued_at=int(clock().timestamp()))
    result = apple_link(service, owner, token)
    assert result.payload.status == "linked" and result.raw_token is None
    assert binding(service)["state"] == "active" and binding(service)["generation"] == 2
    assert not service.apple.dispatch_one()
    clock.now += timedelta(hours=24, seconds=1)
    AuthMetadataRepository(service.store.root, service.store).cleanup_expired(
        now=clock()
    )
    assert binding(service)["state"] == "active"
    with service.store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM auth_apple_grants").fetchone()[0]
            == 1
        )


def test_023_fr025_live_apple_cleanup_lease_blocks_explicit_relink(apple_runtime):
    """An in-flight old revoke must settle before the owner can commit newer consent."""
    service, _, _, provider, clock = apple_runtime
    owner, token = owner_with_binding(service, provider, clock)
    remove(service, owner, token, "apple")
    observed = []
    original = provider.revoke_apple

    def in_flight(*args, **kwargs):
        clock.now += timedelta(seconds=2)
        provider.identity = replace(
            provider.identity, issued_at=int(clock().timestamp())
        )
        with pytest.raises(ModernAuthError) as error:
            apple_link(service, owner, token)
        observed.append(error.value.status_code)
        AuthMetadataRepository(service.store.root, service.store).cleanup_expired(
            now=clock()
        )
        observed.append(binding(service)["state"])
        original(*args, **kwargs)

    provider.revoke_apple = in_flight
    assert service.apple.dispatch_one()
    assert observed == [409, "unlinked"]
    assert binding(service) is None
    result = apple_link(service, owner, token)
    assert result.payload.status == "linked"
    assert binding(service)["state"] == "active"


def test_023_fr025_unlink_notice_cannot_convert_removed_binding_to_reconsent(
    apple_runtime,
):
    """A signed revocation notice cannot turn explicit Remove into a revivable disabled identity."""
    service, _, _, provider, clock = apple_runtime
    owner, token = owner_with_binding(service, provider, clock)
    remove(service, owner, token, "apple")
    service.process_apple_notification("synthetic signed notice")
    assert binding(service) is None or binding(service)["state"] == "unlinked"
    clock.now += timedelta(seconds=2)
    provider.identity = replace(provider.identity, issued_at=int(clock().timestamp()))
    result, _, _ = apple.native_login(service)
    assert (
        result.payload.status == "existing_account_required"
        and result.raw_token is None
    )


def test_023_fr025_cleanup_never_starts_a_lease_past_its_retention_deadline(
    apple_runtime,
):
    """Work without a full bounded lease window is erased instead of extending retention."""
    service, _, _, provider, clock = apple_runtime
    owner, token = owner_with_binding(service, provider, clock)
    remove(service, owner, token, "apple")
    clock.now += timedelta(hours=24) - timedelta(seconds=10)
    assert not service.apple.dispatch_one()
    assert provider.revocations == []
    assert binding(service) is None


@pytest.mark.parametrize("outcome", ["delivered", "last_window", "expired_lease"])
def test_023_fr025_two_issuing_clients_cleanup_without_stale_binding_rows(
    apple_runtime, outcome
):
    """Two client grants settle or expire together without revisiting cascaded stale job rows."""
    service, _, _, provider, clock = apple_runtime
    owner, token = owner_with_binding(service, provider, clock)
    with service.store.transaction() as connection:
        web_identity = replace(
            provider.identity, audience=service.settings.apple_services_id
        )
        service.apple.record_grant(
            connection,
            "original_binding",
            ProviderTokens(
                web_identity,
                web_identity.audience,
                SecretStr("synthetic-web-revoke"),
                "refresh_token",
            ),
        )
    remove(service, owner, token, "apple")
    if outcome == "delivered":
        assert service.apple.dispatch_one()
        assert binding(service)["state"] == "unlinked"
        assert service.apple.dispatch_one()
        assert {client for _, client, _ in provider.revocations} == {
            "com.example.native",
            "com.example.web",
        }
    else:
        if outcome == "expired_lease":
            with service.store.transaction() as connection:
                connection.execute(
                    "UPDATE auth_apple_cleanup_jobs SET status='leased',attempts=1,lease_id='abandoned',lease_expires_at=?",
                    ((clock() + timedelta(seconds=30)).isoformat(),),
                )
            clock.now += timedelta(hours=24, seconds=1)
        else:
            clock.now += timedelta(hours=24) - timedelta(seconds=10)
        assert not service.apple.dispatch_one()
        assert provider.revocations == []
    assert binding(service) is None
    with service.store.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM auth_apple_cleanup_jobs"
            ).fetchone()[0]
            == 0
        )


def test_023_fr006_apple_explicit_link_cannot_steal_foreign_subject_while_unlinked(
    apple_runtime,
):
    """A fresh owner-bound link cannot erase another owner's subject binding or the original cleanup mapping."""
    service, _, _, provider, clock = apple_runtime
    owner, token = owner_with_binding(service, provider, clock)
    remove(service, owner, token, "apple")
    other = service.auth.seed_admin(email="foreign@example.com", password=PASSWORD)
    with service.store.transaction() as connection:
        connection.execute(
            "INSERT INTO auth_identity_bindings(id,user_id,provider,issuer,namespace,subject,created_at,updated_at) VALUES('foreign_binding',?,'apple','https://appleid.apple.com','brainbuddy','foreign-subject',?,?)",
            (other.id, clock().isoformat(), clock().isoformat()),
        )
    provider.identity = replace(
        provider.identity, subject="foreign-subject", email=other.email
    )
    with pytest.raises(ModernAuthError) as error:
        apple_link(service, owner, token)
    assert error.value.status_code == 404
    with service.store.connection() as connection:
        rows = connection.execute(
            "SELECT id,user_id,state FROM auth_identity_bindings ORDER BY id"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("foreign_binding", other.id, "active"),
            ("original_binding", owner.id, "unlinked"),
        ]
        assert (
            connection.execute(
                "SELECT count(*) FROM auth_apple_cleanup_jobs"
            ).fetchone()[0]
            == 1
        )
