"""Real Identity-store evidence for recovery and protected account authority."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier, Event
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr

from app.container import Container
from app.schemas.auth import User
from app.schemas.modern_auth import (
    AccountActionRequest,
    AccountPasswordRequest,
    Action,
    ChallengeResponse,
    EmailPurpose,
    EmailRequest,
    EmailVerifyRequest,
    PasswordConfirmRequest,
    ProviderCompleteRequest,
    ProviderStartRequest,
    ReauthenticatedResult,
    ResetReadyResult,
    ResetRequest,
    SignedInResult,
)
from app.services.auth_mail_service import AuthMailService
from app.services.auth_provider_service import ProviderTokens
from app.services.modern_auth_service import (
    AuthResult,
    ModernAuthError,
    ModernAuthService,
    ProviderStartResult,
)
from tests.test_modern_auth_service import (
    VERIFIER,
    Clock,
    Provider,
    challenge,
    modern,
)

__all__ = ["modern"]  # Re-export the shared fixture for pytest discovery.

pytestmark = [
    pytest.mark.allure_label("Authentication & Access", label_type="epic"),
    pytest.mark.allure_label("Modern authentication", label_type="feature"),
    pytest.mark.allure_label(
        "023-FR-004–019 023-SC-003 023-SC-004 Protected authority",
        label_type="story",
    ),
]

Modern = tuple[
    ModernAuthService,
    AuthMailService,
    list[tuple[str, str, str]],
    Provider,
    Clock,
]
PASSWORD = "original-long-password"
REPLACEMENT = "replacement-long-password"


def current_user(service: ModernAuthService, identifier: str) -> User:
    user = service.auth.user_repo.get_by_id(identifier)
    assert user is not None, "The existing owner must still be persisted"
    return user


def session_user(service: ModernAuthService, token: str) -> User:
    user = service.auth.get_user_for_token(token)
    assert user is not None, "The independent acting session must remain usable"
    return user


def rows(
    service: ModernAuthService, sql: str, arguments: tuple[object, ...] = ()
) -> list[sqlite3.Row]:
    with service.store.connection() as connection:
        return cast(list[sqlite3.Row], connection.execute(sql, arguments).fetchall())


def authority_counts(service: ModernAuthService) -> tuple[int, int, int]:
    """Observe durable users, identity bindings and application sessions."""
    return (
        int(rows(service, "SELECT COUNT(*) FROM users")[0][0]),
        int(rows(service, "SELECT COUNT(*) FROM auth_identity_bindings")[0][0]),
        int(rows(service, "SELECT COUNT(*) FROM sessions")[0][0]),
    )


def password_owner(
    container: Container,
    clock: Clock,
    *,
    email: str = "owner@example.com",
    verified: bool = True,
) -> tuple[User, str]:
    user = container.auth_service.seed_admin(email=email, password=PASSWORD)
    if verified:
        user = container.user_repo.mutate(
            user.id,
            lambda fresh: fresh.model_copy(update={"email_verified_at": clock()}),
        )
    _, token, _ = container.auth_service.login(email=user.email, password=PASSWORD)
    return user, token


def password_proof(
    service: ModernAuthService, user: User, token: str, action: Action
) -> str:
    return service.confirm_password(
        PasswordConfirmRequest(
            current_password=PASSWORD, expected_account_id=user.id, action=action
        ),
        raw_token=token,
    ).recent_proof


def delivered(
    modern: Modern,
    email: str,
    purpose: EmailPurpose = "login",
    *,
    user: User | None = None,
    token: str | None = None,
    action: Action | None = None,
    proof: str | None = None,
) -> tuple[ChallengeResponse, str]:
    service, mail, sent, _, clock = modern
    # Model the explicit wait between requests. The persistent minimum send
    # interval applies across intents, not just to the resend operation.
    clock.now += timedelta(seconds=61)
    pending = service.request_email(
        EmailRequest(
            email=email,
            purpose=purpose,
            client="web",
            client_challenge=challenge(),
            expected_account_id=user.id if user else None,
            action=action,
            recent_proof=proof,
        ),
        network="authority-tests",
        raw_token=token,
    )
    assert mail.dispatch_one(), "The synthetic delivery must acknowledge this proof"
    assert sent[-1][0] == email
    return pending, sent[-1][1]


def finish_email(
    service: ModernAuthService,
    pending: ChallengeResponse,
    code: str,
    *,
    token: str | None = None,
    proof: str | None = None,
) -> AuthResult:
    return service.verify_email(
        EmailVerifyRequest(
            challenge_id=pending.challenge_id,
            code=code,
            client_verifier=VERIFIER,
            recent_proof=proof,
        ),
        network="authority-tests",
        raw_token=token,
    )


def email_owner(modern: Modern) -> tuple[User, str]:
    service = modern[0]
    pending, code = delivered(modern, "email-owner@example.com")
    result = finish_email(service, pending, code)
    assert isinstance(result.payload, SignedInResult) and result.raw_token
    user = service.auth.user_repo.get_by_id(result.payload.user.id)
    assert user is not None and not user.password_hash
    return user, result.raw_token


def email_proof(modern: Modern, user: User, token: str, action: Action) -> str:
    pending, code = delivered(
        modern, user.email, "reauth", user=user, token=token, action=action
    )
    result = finish_email(modern[0], pending, code, token=token)
    assert isinstance(result.payload, ReauthenticatedResult)
    assert result.raw_token is None
    return result.payload.recent_proof


def start_provider(
    service: ModernAuthService,
    *,
    purpose: Literal["login", "link", "reauth"] = "login",
    user: User | None = None,
    token: str | None = None,
    action: Action | None = None,
    proof: str | None = None,
) -> ProviderStartResult:
    return service.start_provider(
        "google",
        ProviderStartRequest(
            purpose=purpose,
            client="web",
            client_challenge=challenge(),
            expected_account_id=user.id if user else None,
            action=action,
            recent_proof=proof,
        ),
        raw_token=token,
    )


def handoff(
    service: ModernAuthService, started: ProviderStartResult
) -> ProviderCompleteRequest:
    returned = service.provider_callback(
        "google",
        code="synthetic-provider-code",
        state=started.payload.state,
        binder=started.binder,
    )
    parameters = parse_qs(urlsplit(returned.url).fragment)
    assert urlsplit(returned.url).path == "/auth/complete"
    return ProviderCompleteRequest(
        attempt_id=parameters["attempt"][0],
        state=parameters["state"][0],
        handoff_code=parameters["grant"][0],
        client_verifier=VERIFIER,
    )


def provider_owner(modern: Modern) -> tuple[User, str]:
    service = modern[0]
    result = service.complete_provider(handoff(service, start_provider(service)))
    assert isinstance(result.payload, SignedInResult) and result.raw_token
    user = service.auth.user_repo.get_by_id(result.payload.user.id)
    assert user is not None and not user.password_hash
    return user, result.raw_token


def provider_proof(
    service: ModernAuthService, user: User, token: str, action: Action
) -> str:
    started = start_provider(
        service, purpose="reauth", user=user, token=token, action=action
    )
    result = service.complete_provider(handoff(service, started), raw_token=token)
    assert isinstance(result.payload, ReauthenticatedResult)
    assert result.raw_token is None
    return result.payload.recent_proof


def recovery(modern: Modern, user: User) -> ResetRequest:
    pending, code = delivered(modern, user.email, "recover")
    result = finish_email(modern[0], pending, code)
    assert isinstance(result.payload, ResetReadyResult)
    assert result.raw_token is None
    return ResetRequest(
        reset_grant=result.payload.reset_grant,
        client_verifier=VERIFIER,
        new_password=REPLACEMENT,
    )


@pytest.mark.parametrize(
    "kind", ["unknown", "legacy", "passwordless", "operator", "due"]
)
def test_023_FR_010_FR_011_FR_014_ineligible_recovery_is_neutral_and_inert(
    modern: Modern, container: Container, kind: str
) -> None:
    """Unknown, unverified, passwordless, reserved and past-due recovery creates no authority."""
    service, mail, sent, _, clock = modern
    email = "unknown@example.com"
    if kind == "passwordless":
        user, _ = email_owner(modern)
        email = user.email
        sent.clear()
        clock.now += timedelta(seconds=61)
    elif kind != "unknown":
        user, _ = password_owner(container, clock, verified=kind != "legacy")
        email = user.email
        if kind == "operator":
            service.auth.reserved_emails = frozenset({email})
        elif kind == "due":
            container.user_repo.mutate(
                user.id,
                lambda fresh: fresh.model_copy(
                    update={"deletion_requested_at": clock() - timedelta(days=15)}
                ),
            )
    before = authority_counts(service)
    pending = service.request_email(
        EmailRequest(
            email=email, purpose="recover", client="web", client_challenge=challenge()
        ),
        network="authority-tests",
    )
    assert pending.message == "If this address can be used, you will receive a code."
    assert pending.expires_at == clock() + timedelta(minutes=10)
    assert not mail.dispatch_one() and not sent
    with pytest.raises(ModernAuthError):
        finish_email(service, pending, "123456")
    assert authority_counts(service) == before


@pytest.mark.parametrize(
    "invalidated",
    [
        "expiry",
        "verifier",
        "policy",
        "password",
        "mailbox",
        "deletion",
        "purge",
        "operator",
    ],
)
def test_023_FR_011_FR_019_reset_fresh_checks_every_authority_boundary(
    modern: Modern, container: Container, invalidated: str
) -> None:
    """A stale or foreign reset cannot rotate a password, mint sessions or cancel deletion."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    payload = recovery(modern, user)
    if invalidated == "expiry":
        clock.now += timedelta(minutes=10)
    elif invalidated == "verifier":
        payload = payload.model_copy(update={"client_verifier": "f" * 43})
    elif invalidated == "policy":
        payload = payload.model_copy(update={"new_password": "short"})
    elif invalidated == "password":
        container.account_service.change_password(
            user,
            current_password=PASSWORD,
            new_password="independently-changed-password",
            keep_token_hash=service.auth.hash_session_token(token),
        )
    elif invalidated == "mailbox":
        container.user_repo.mutate(
            user.id, lambda fresh: fresh.model_copy(update={"email_verified_at": None})
        )
    elif invalidated == "deletion":
        container.account_service.request_deletion(user, current_password=PASSWORD)
    elif invalidated == "purge":
        container.account_service.purge_account(user.id)
    else:
        service.auth.reserved_emails = frozenset({user.email})
    fresh = container.user_repo.get_by_id(user.id)
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.reset_password(payload)
    assert container.user_repo.get_by_id(user.id) == fresh
    assert authority_counts(service) == before


def test_023_FR_011_SC_003_two_reset_consumers_allow_one_change_and_zero_sessions(
    modern: Modern, container: Container
) -> None:
    """Two real transactions race on one reset grant and create no automatic login."""
    service, _, _, _, clock = modern
    user, first = password_owner(container, clock)
    _, second, _ = service.auth.login(email=user.email, password=PASSWORD)
    payload = recovery(modern, user)
    started = Barrier(2)

    def reset() -> bool:
        started.wait(timeout=5)
        try:
            service.reset_password(payload)
        except ModernAuthError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: reset(), range(2)))
    assert sorted(results) == [False, True]
    assert authority_counts(service) == (1, 0, 0)
    assert service.auth.get_user_for_token(first) is None
    assert service.auth.get_user_for_token(second) is None
    fresh = container.user_repo.get_by_id(user.id)
    assert fresh is not None and service.auth.verify_password(fresh, REPLACEMENT)
    assert not rows(service, "SELECT * FROM auth_proofs WHERE user_id=?", (user.id,))


def test_023_FR_011_FR_013_reset_and_recent_grants_cannot_exchange_purposes(
    modern: Modern, container: Container
) -> None:
    """Mailbox recovery grants and session-bound recent grants have disjoint authority."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    reset = recovery(modern, user)
    recent = password_proof(service, user, token, "export")
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.reset_password(reset.model_copy(update={"reset_grant": recent}))
    with pytest.raises(ModernAuthError):
        service.export_account(
            AccountActionRequest(
                recent_proof=reset.reset_grant, expected_account_id=user.id
            ),
            raw_token=token,
        )
    assert authority_counts(service) == before
    assert service.auth.verify_password(current_user(service, user.id), PASSWORD)


def test_023_FR_012_expired_confirmation_can_be_renewed_without_losing_pending_code(
    modern: Modern, container: Container
) -> None:
    """An expired five-minute confirmation preserves the pending code for fresh same-action proof."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    _, other, _ = service.auth.login(email=user.email, password=PASSWORD)
    proof = password_proof(service, user, token, "change_email")
    pending, code = delivered(
        modern,
        "destination@example.com",
        "change_email",
        user=user,
        token=token,
        action="change_email",
        proof=proof,
    )
    clock.now += timedelta(minutes=5)
    with pytest.raises(ModernAuthError) as failure:
        finish_email(service, pending, code, token=token)
    assert failure.value.status_code == 403
    assert container.user_repo.get_by_email("destination@example.com") is None
    assert current_user(service, user.id).email == user.email
    renewal = password_proof(service, user, token, "change_email")
    result = finish_email(service, pending, code, token=token, proof=renewal)
    assert result.payload.status == "changed_email" and result.raw_token is None
    fresh = service.auth.get_user_for_token(token)
    assert fresh is not None and fresh.id == user.id
    assert fresh.email == "destination@example.com" and fresh.email_verified_at
    assert container.user_repo.get_by_email(user.email) is None
    assert service.auth.get_user_for_token(other) is None
    with pytest.raises(ModernAuthError):
        finish_email(service, pending, code, token=token, proof=renewal)


@pytest.mark.parametrize("mismatch", ["action", "session", "owner"])
def test_023_FR_006_FR_012_pending_email_confirmation_rejects_foreign_renewal(
    modern: Modern, container: Container, mismatch: str
) -> None:
    """A pending destination cannot use another action, session or owner's renewed confirmation."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    proof = password_proof(service, user, token, "change_email")
    pending, code = delivered(
        modern,
        "destination@example.com",
        "change_email",
        user=user,
        token=token,
        action="change_email",
        proof=proof,
    )
    if mismatch == "action":
        foreign = password_proof(service, user, token, "password")
    elif mismatch == "session":
        _, second, _ = service.auth.login(email=user.email, password=PASSWORD)
        foreign = password_proof(service, user, second, "change_email")
    else:
        other, second = password_owner(container, clock, email="other@example.com")
        foreign = password_proof(service, other, second, "change_email")
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        finish_email(service, pending, code, token=token, proof=foreign)
    assert authority_counts(service) == before
    assert current_user(service, user.id).email == user.email
    assert container.user_repo.get_by_email("destination@example.com") is None
    assert (
        finish_email(service, pending, code, token=token).payload.status
        == "changed_email"
    )


@pytest.mark.parametrize("kind", ["claimed", "reserved"])
def test_023_FR_012_destination_conflict_rolls_back_confirmation_and_address_change(
    modern: Modern, container: Container, kind: str
) -> None:
    """A newly claimed or reserved destination leaves the old verified account intact."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    proof = password_proof(service, user, token, "change_email")
    pending, code = delivered(
        modern,
        "destination@example.com",
        "change_email",
        user=user,
        token=token,
        action="change_email",
        proof=proof,
    )
    if kind == "claimed":
        password_owner(container, clock, email="destination@example.com")
    else:
        service.auth.reserved_emails = frozenset({"destination@example.com"})
    before = authority_counts(service)
    with pytest.raises(ModernAuthError) as failure:
        finish_email(service, pending, code, token=token)
    assert (failure.value.code, failure.value.status_code) == ("conflict", 409)
    assert authority_counts(service) == before
    assert container.user_repo.get_by_id(user.id) == user
    assert session_user(service, token).id == user.id


def test_023_FR_014_authenticated_legacy_verification_rejects_another_session(
    modern: Modern, container: Container
) -> None:
    """Historical unverified email gains authority only after password and same-session mailbox proof."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock, verified=False)
    proof = password_proof(service, user, token, "verify_email")
    pending, code = delivered(
        modern,
        user.email,
        "verify_email",
        user=user,
        token=token,
        action="verify_email",
        proof=proof,
    )
    _, second, _ = service.auth.login(email=user.email, password=PASSWORD)
    with pytest.raises(ModernAuthError) as failure:
        finish_email(service, pending, code, token=second)
    assert failure.value.status_code == 404
    assert current_user(service, user.id).email_verified_at is None
    result = finish_email(service, pending, code, token=token)
    assert result.payload.status == "verified_email" and result.raw_token is None
    assert current_user(service, user.id).email_verified_at is not None
    assert service.auth.get_user_for_token(second) is None


@pytest.mark.parametrize("purpose", ["verify_email", "change_email", "reauth"])
def test_023_FR_006_FR_012_protected_email_requires_explicit_expected_owner(
    modern: Modern, container: Container, purpose: EmailPurpose
) -> None:
    """Protected email operations cannot infer the intended account from another tab's cookie."""
    service, mail, _, _, clock = modern
    user, token = password_owner(container, clock)
    action = "export" if purpose == "reauth" else cast(Action, purpose)
    proof = password_proof(service, user, token, action)
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.request_email(
            EmailRequest(
                email=user.email,
                purpose=purpose,
                client="web",
                client_challenge=challenge(),
                action=action,
                recent_proof=proof,
            ),
            network="authority-tests",
            raw_token=token,
        )
    assert not mail.dispatch_one()
    assert authority_counts(service) == before


@pytest.mark.parametrize("mismatch", ["binder_missing", "binder", "state", "provider"])
def test_023_FR_004_callback_rejects_foreign_attempt_before_provider_exchange(
    modern: Modern, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    """Wrong provider, state or browser binder grants no upstream exchange or durable authority."""
    service, _, _, provider, _ = modern
    started = start_provider(service)
    calls: list[str] = []

    def exchange(code: str, **_kwargs: Any) -> ProviderTokens:
        calls.append(code)
        return ProviderTokens(provider.identity, provider.identity.audience)

    monkeypatch.setattr(provider, "exchange_google", exchange)
    binder = started.binder
    if mismatch == "binder_missing":
        binder = None
    elif mismatch == "binder":
        binder = "f" * 43
    state = "f" * 43 if mismatch == "state" else started.payload.state
    selected: Literal["google", "apple"] = (
        "apple" if mismatch == "provider" else "google"
    )
    with pytest.raises(ModernAuthError):
        service.provider_callback(
            selected, code="synthetic", state=state, binder=binder
        )
    assert not calls
    assert authority_counts(service) == (0, 0, 0)
    assert rows(service, "SELECT status FROM auth_attempts")[0][0] == "started"


@pytest.mark.parametrize(
    "mismatch", ["state", "client_verifier", "handoff_code", "attempt_id"]
)
def test_023_FR_004_FR_015_handoff_requires_all_original_client_fields_and_consumes_once(
    modern: Modern, mismatch: str
) -> None:
    """A stolen or substituted callback field cannot issue a session or consume the owner's grant."""
    service = modern[0]
    payload = handoff(service, start_provider(service))
    foreign = payload.model_copy(update={mismatch: "f" * 43})
    with pytest.raises(ModernAuthError):
        service.complete_provider(foreign)
    assert authority_counts(service) == (0, 0, 0)
    result = service.complete_provider(payload)
    assert result.payload.status == "signed_in" and result.raw_token
    assert authority_counts(service) == (1, 1, 1)
    with pytest.raises(ModernAuthError):
        service.complete_provider(payload)
    assert authority_counts(service) == (1, 1, 1)


def test_023_FR_015_handoff_expires_at_exact_sixty_second_boundary(
    modern: Modern,
) -> None:
    """The callback grant cannot authorize at or beyond its sixty-second deadline."""
    service, _, _, _, clock = modern
    payload = handoff(service, start_provider(service))
    clock.now += timedelta(seconds=60)
    with pytest.raises(ModernAuthError):
        service.complete_provider(payload)
    assert authority_counts(service) == (0, 0, 0)


@pytest.mark.parametrize("elapsed", [30, 31])
def test_023_FR_004_callback_exchange_cannot_commit_after_its_lease_expires(
    modern: Modern, monkeypatch: pytest.MonkeyPatch, elapsed: int
) -> None:
    """An expired exchange lease cannot stage a late provider result or issue a returning grant."""
    service, _, _, provider, clock = modern
    started = start_provider(service)

    def delayed_exchange(_code: str, **_kwargs: Any) -> ProviderTokens:
        clock.now += timedelta(seconds=elapsed)
        return ProviderTokens(provider.identity, provider.identity.audience)

    monkeypatch.setattr(provider, "exchange_google", delayed_exchange)
    with pytest.raises(ModernAuthError):
        handoff(service, started)
    assert authority_counts(service) == (0, 0, 0)
    assert not rows(service, "SELECT * FROM auth_handoffs")


def test_023_FR_004_concurrent_callbacks_exchange_once_and_return_one_grant(
    modern: Modern, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real callback transaction lease prevents concurrent redemption of the same upstream code."""
    service, _, _, provider, _ = modern
    started = start_provider(service)
    calls: list[str] = []
    exchanging, release = Event(), Event()

    def exchange(code: str, **_kwargs: Any) -> ProviderTokens:
        calls.append(code)
        exchanging.set()
        assert release.wait(
            timeout=5
        ), "The first exchange must be released by the test"
        return ProviderTokens(provider.identity, provider.identity.audience)

    monkeypatch.setattr(provider, "exchange_google", exchange)

    def callback() -> ProviderCompleteRequest | None:
        try:
            return handoff(service, started)
        except ModernAuthError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(callback)
        assert exchanging.wait(timeout=5)
        try:
            second = executor.submit(callback)
            assert second.result(timeout=5) is None
        finally:
            release.set()
        successful = first.result(timeout=5)
    assert successful is not None and len(calls) == 1
    assert len(rows(service, "SELECT * FROM auth_handoffs")) == 1
    assert authority_counts(service) == (0, 0, 0)
    assert service.complete_provider(successful).payload.status == "signed_in"


@pytest.mark.parametrize(
    "invalidated", ["session", "owner", "password", "purge", "operator", "expiry"]
)
def test_023_FR_006_FR_019_link_completion_rechecks_current_session_owner_and_authority(
    modern: Modern, container: Container, invalidated: str
) -> None:
    """A staged link cannot attach a binding after its session, account or confirmation changes."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    proof = password_proof(service, user, token, "link:google")
    if invalidated == "expiry":
        clock.now += timedelta(minutes=4, seconds=45)
    payload = handoff(
        service,
        start_provider(
            service,
            purpose="link",
            user=user,
            token=token,
            action="link:google",
            proof=proof,
        ),
    )
    acting = token
    if invalidated == "session":
        _, acting, _ = service.auth.login(email=user.email, password=PASSWORD)
    elif invalidated == "owner":
        _, acting = password_owner(container, clock, email="other@example.com")
    elif invalidated == "password":
        container.account_service.change_password(
            user,
            current_password=PASSWORD,
            new_password=REPLACEMENT,
            keep_token_hash=service.auth.hash_session_token(token),
        )
    elif invalidated == "purge":
        container.account_service.purge_account(user.id)
    elif invalidated == "operator":
        service.auth.reserved_emails = frozenset({user.email})
    else:
        # The callback grant remains live when the original confirmation expires.
        clock.now += timedelta(seconds=15)
    before = authority_counts(service)
    with pytest.raises(ModernAuthError) as failure:
        service.complete_provider(payload, raw_token=acting)
    if invalidated == "expiry":
        assert failure.value.status_code == 403
    assert authority_counts(service) == before
    assert not rows(service, "SELECT * FROM auth_identity_bindings")


def test_023_FR_005_bound_identity_cannot_be_linked_to_a_different_existing_owner(
    modern: Modern, container: Container
) -> None:
    """Proving an identity owned by another account cannot reassign either account or its sessions."""
    service, _, _, _, clock = modern
    original, original_token = provider_owner(modern)
    other, token = password_owner(container, clock)
    proof = password_proof(service, other, token, "link:google")
    payload = handoff(
        service,
        start_provider(
            service,
            purpose="link",
            user=other,
            token=token,
            action="link:google",
            proof=proof,
        ),
    )
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.complete_provider(payload, raw_token=token)
    assert authority_counts(service) == before
    assert (
        rows(service, "SELECT user_id FROM auth_identity_bindings")[0][0] == original.id
    )
    assert session_user(service, original_token).id == original.id
    assert session_user(service, token).id == other.id


@pytest.mark.parametrize("field", ["subject", "namespace", "issuer"])
def test_023_FR_004_FR_013_same_email_does_not_make_a_foreign_identity_recent_authority(
    modern: Modern, field: str
) -> None:
    """An unbound subject, issuer or namespace cannot reauthenticate a same-email account."""
    service, _, _, provider, _ = modern
    user, token = provider_owner(modern)
    original = provider.identity
    provider.identity = replace(
        original,
        subject="foreign-identity" if field == "subject" else original.subject,
        namespace="foreign-identity" if field == "namespace" else original.namespace,
        issuer="foreign-identity" if field == "issuer" else original.issuer,
    )
    payload = handoff(
        service,
        start_provider(
            service, purpose="reauth", user=user, token=token, action="export"
        ),
    )
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.complete_provider(payload, raw_token=token)
    assert authority_counts(service) == before
    assert not rows(service, "SELECT * FROM auth_proofs")


def test_023_FR_014_provider_recent_proof_cannot_verify_a_legacy_unverified_address(
    modern: Modern, container: Container
) -> None:
    """A linked provider's email match cannot establish historical mailbox authority without password proof."""
    service, mail, _, _, clock = modern
    user, token = password_owner(container, clock, verified=False)
    link = password_proof(service, user, token, "link:google")
    service.complete_provider(
        handoff(
            service,
            start_provider(
                service,
                purpose="link",
                user=user,
                token=token,
                action="link:google",
                proof=link,
            ),
        ),
        raw_token=token,
    )
    proof = provider_proof(service, user, token, "verify_email")
    with pytest.raises(ModernAuthError) as failure:
        service.request_email(
            EmailRequest(
                email=user.email,
                purpose="verify_email",
                client="web",
                client_challenge=challenge(),
                expected_account_id=user.id,
                action="verify_email",
                recent_proof=proof,
            ),
            network="authority-tests",
            raw_token=token,
        )
    assert failure.value.status_code == 403
    assert not mail.dispatch_one()
    assert current_user(service, user.id).email_verified_at is None


def test_023_FR_007_last_usable_method_failure_preserves_binding_and_one_use_proof(
    modern: Modern,
) -> None:
    """Disabling the alternative delivery method cannot permit removal of the only usable provider."""
    service, _, _, _, _ = modern
    user, token = provider_owner(modern)
    settings = service.settings
    service.settings = settings.model_copy(update={"smtp_host": ""})
    proof = provider_proof(service, user, token, "unlink:google")
    payload = AccountActionRequest(recent_proof=proof, expected_account_id=user.id)
    before = rows(service, "SELECT * FROM auth_identity_bindings")
    metadata = service.account_methods(raw_token=token)
    assert [method.method for method in metadata.methods if method.usable] == ["google"]
    with pytest.raises(ModernAuthError) as failure:
        service.unlink("google", payload, raw_token=token)
    assert (failure.value.code, failure.value.status_code) == ("last_method", 409)
    assert rows(service, "SELECT * FROM auth_identity_bindings") == before
    assert session_user(service, token).id == user.id
    service.settings = settings
    result = service.unlink("google", payload, raw_token=token)
    assert result.signed_out
    assert service.auth.get_user_for_token(token) is None
    assert any(
        method.method == "email" and method.usable for method in result.methods.methods
    )


@pytest.mark.parametrize("caller", ["provider", "email"])
def test_023_FR_007_unlink_revokes_only_originating_provider_sessions_and_reports_signout(
    modern: Modern, caller: str
) -> None:
    """Unlink removes every originating provider session while preserving independent email authority."""
    service = modern[0]
    user, first = provider_owner(modern)
    second_result = service.complete_provider(handoff(service, start_provider(service)))
    second = second_result.raw_token
    assert second
    pending, code = delivered(modern, user.email)
    independent = finish_email(service, pending, code).raw_token
    assert independent
    if caller == "provider":
        acting = first
        proof = provider_proof(service, user, acting, "unlink:google")
    else:
        acting = independent
        proof = email_proof(modern, user, acting, "unlink:google")
    payload = AccountActionRequest(recent_proof=proof, expected_account_id=user.id)
    result = service.unlink("google", payload, raw_token=acting)
    assert result.signed_out == (caller == "provider")
    assert service.auth.get_user_for_token(first) is None
    assert service.auth.get_user_for_token(second) is None
    assert session_user(service, independent).id == user.id
    assert authority_counts(service) == (1, 1, 1)
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.unlink("google", payload, raw_token=acting)
    assert authority_counts(service) == before


def test_023_FR_004_old_provider_handoff_cannot_cross_unlink_and_new_authorization_generation(
    modern: Modern,
) -> None:
    """A staged old provider assertion stays invalid after unlink and a fresh explicit provider login."""
    service = modern[0]
    user, token = provider_owner(modern)
    stale = handoff(service, start_provider(service))
    proof = provider_proof(service, user, token, "unlink:google")
    service.unlink(
        "google",
        AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
        raw_token=token,
    )
    fresh = service.complete_provider(handoff(service, start_provider(service)))
    assert fresh.payload.status == "signed_in" and fresh.raw_token
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.complete_provider(stale)
    assert authority_counts(service) == before
    assert session_user(service, fresh.raw_token).id == user.id


@pytest.mark.parametrize("action", ["password", "export", "delete"])
def test_023_FR_013_SC_004_passwordless_account_retains_sensitive_actions(
    modern: Modern, container: Container, action: Action
) -> None:
    """A passwordless owner can confirm its linked email and add a password, export or request deletion."""
    service, _, sent, _, clock = modern
    user, token = email_owner(modern)
    pending, code = delivered(modern, user.email)
    other = finish_email(service, pending, code).raw_token
    assert other
    proof = email_proof(modern, user, token, action)
    payload = AccountActionRequest(recent_proof=proof, expected_account_id=user.id)
    if action == "password":
        with pytest.raises(ModernAuthError):
            service.set_password(
                AccountPasswordRequest(**payload.model_dump(), new_password="short"),
                raw_token=token,
            )
        service.set_password(
            AccountPasswordRequest(**payload.model_dump(), new_password=REPLACEMENT),
            raw_token=token,
        )
        fresh = service.auth.get_user_for_token(token)
        assert fresh is not None and fresh.id == user.id and fresh.password_hash
        assert service.auth.get_user_for_token(other) is None
        logged_in, _, _ = service.auth.login(email=user.email, password=REPLACEMENT)
        assert logged_in.id == user.id
    elif action == "export":
        filename, stream = service.export_account(payload, raw_token=token)
        try:
            assert filename.endswith(".zip")
            with zipfile.ZipFile(stream) as archive:
                account = json.loads(archive.read("account.json"))
                assert account["id"] == user.id
                content = b"\n".join(archive.read(name) for name in archive.namelist())
                for secret in [token, other, proof, *(message[1] for message in sent)]:
                    assert secret.encode() not in content
                assert b'"password_hash"' not in content
        finally:
            stream.close()
        assert session_user(service, token).id == user.id
        assert session_user(service, other).id == user.id
    else:
        deleted = service.delete_account(payload, raw_token=token)
        assert deleted.id == user.id and not deleted.password_hash
        assert deleted.deletion_requested_at == clock()
        assert service.account.purge_at_for(deleted) == clock() + timedelta(days=14)
        assert service.auth.get_user_for_token(token) is None
        assert service.auth.get_user_for_token(other) is None
        assert not rows(
            service, "SELECT * FROM auth_proofs WHERE user_id=?", (user.id,)
        )
        assert container.user_repo.get_by_id(user.id) is not None


@pytest.mark.parametrize("stage", ["email_code", "reset", "provider_handoff"])
def test_023_FR_018_FR_019_purged_known_owner_never_falls_back_to_signup(
    modern: Modern, container: Container, stage: str
) -> None:
    """Previously known owner proofs cannot recreate an erased account or create a new account at its address."""
    service, _, _, _, clock = modern
    if stage == "provider_handoff":
        user, _ = provider_owner(modern)
        provider_payload = handoff(service, start_provider(service))
    else:
        user, _ = password_owner(container, clock)
        if stage == "reset":
            reset = recovery(modern, user)
        else:
            pending, code = delivered(modern, user.email)
    container.account_service.purge_account(user.id)
    assert authority_counts(service) == (0, 0, 0)
    with pytest.raises(ModernAuthError):
        if stage == "provider_handoff":
            service.complete_provider(provider_payload)
        elif stage == "reset":
            service.reset_password(reset)
        else:
            finish_email(service, pending, code)
    assert authority_counts(service) == (0, 0, 0)
    assert container.user_repo.get_by_email(user.email) is None


def test_023_FR_017_operator_configuration_rejects_preexisting_external_sessions_and_proofs(
    modern: Modern,
) -> None:
    """Configuring an operator address cannot elevate an existing public provider session or staged proof."""
    service = modern[0]
    user, token = provider_owner(modern)
    proof = provider_proof(service, user, token, "export")
    payload = handoff(service, start_provider(service))
    service.auth.reserved_emails = frozenset({user.email})
    assert service.auth.get_user_for_token(token) is None
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.complete_provider(payload)
    with pytest.raises(ModernAuthError):
        service.export_account(
            AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
            raw_token=token,
        )
    assert authority_counts(service) == before
    assert len(service.auth.user_repo.list_users()) == 1


@pytest.mark.parametrize("mutation", ["password", "legacy_email", "deletion", "purge"])
def test_023_FR_012_FR_019_pending_destination_cannot_outlive_current_account_authority(
    modern: Modern, container: Container, mutation: str
) -> None:
    """A queued new-address code cannot override a later credential change, deletion or purge."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    proof = password_proof(service, user, token, "change_email")
    pending, code = delivered(
        modern,
        "destination@example.com",
        "change_email",
        user=user,
        token=token,
        action="change_email",
        proof=proof,
    )
    if mutation == "password":
        container.account_service.change_password(
            user,
            current_password=PASSWORD,
            new_password=REPLACEMENT,
            keep_token_hash=service.auth.hash_session_token(token),
        )
    elif mutation == "legacy_email":
        container.account_service.change_email(
            user,
            current_password=PASSWORD,
            new_email="independent@example.com",
            keep_token_hash=service.auth.hash_session_token(token),
        )
    elif mutation == "deletion":
        container.account_service.request_deletion(user, current_password=PASSWORD)
    else:
        container.account_service.purge_account(user.id)
    expected = container.user_repo.get_by_id(user.id)
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        finish_email(service, pending, code, token=token)
    assert authority_counts(service) == before
    assert container.user_repo.get_by_id(user.id) == expected
    assert container.user_repo.get_by_email("destination@example.com") is None


@pytest.mark.parametrize("method", ["email", "google"])
def test_023_FR_004_FR_015_login_cannot_replace_another_acting_cookie_owner(
    modern: Modern, container: Container, method: str
) -> None:
    """Another tab's authenticated cookie cannot attach the completed login to a different account."""
    service, _, _, _, clock = modern
    if method == "email":
        user, owner_token = email_owner(modern)
        pending, code = delivered(modern, user.email)
    else:
        user, owner_token = provider_owner(modern)
        payload = handoff(service, start_provider(service))
    foreign, foreign_token = password_owner(
        container, clock, email="foreign@example.com"
    )
    before = authority_counts(service)
    with pytest.raises(ModernAuthError) as failure:
        if method == "email":
            finish_email(service, pending, code, token=foreign_token)
        else:
            service.complete_provider(payload, raw_token=foreign_token)
    assert failure.value.status_code == 404
    assert authority_counts(service) == before
    assert session_user(service, foreign_token).id == foreign.id
    if method == "email":
        result = finish_email(service, pending, code, token=owner_token)
    else:
        result = service.complete_provider(payload, raw_token=owner_token)
    assert isinstance(result.payload, SignedInResult) and result.raw_token
    assert result.payload.user.id == user.id
    assert session_user(service, result.raw_token).id == user.id


def test_023_FR_007_missing_provider_configuration_hides_method_without_rewriting_binding(
    modern: Modern,
) -> None:
    """A missing provider credential hides new login while preserving the stored connected identity."""
    service = modern[0]
    user, token = provider_owner(modern)
    binding = rows(service, "SELECT * FROM auth_identity_bindings")
    service.settings = service.settings.model_copy(
        update={"google_client_secret": SecretStr("")}
    )
    assert not service.methods("web").google
    metadata = service.account_methods(raw_token=token)
    connected = next(method for method in metadata.methods if method.method == "google")
    assert connected.state == "active" and not connected.usable
    before = authority_counts(service)
    with pytest.raises(ModernAuthError) as failure:
        start_provider(service)
    assert (failure.value.code, failure.value.status_code) == (
        "method_unavailable",
        503,
    )
    assert rows(service, "SELECT * FROM auth_identity_bindings") == binding
    assert authority_counts(service) == before
    assert session_user(service, token).id == user.id


@pytest.mark.parametrize("purpose", ["link", "reauth"])
def test_023_FR_006_protected_provider_start_requires_explicit_expected_owner(
    modern: Modern,
    container: Container,
    purpose: Literal["link", "reauth"],
) -> None:
    """A protected provider dialog cannot silently capture the current cookie as its intended owner."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    action: Action = "link:google" if purpose == "link" else "export"
    proof = password_proof(service, user, token, action)
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.start_provider(
            "google",
            ProviderStartRequest(
                purpose=purpose,
                client="web",
                client_challenge=challenge(),
                action=action,
                recent_proof=proof,
            ),
            raw_token=token,
        )
    assert authority_counts(service) == before
    assert not rows(service, "SELECT * FROM auth_attempts")


def test_023_FR_011_FR_019_recovery_cannot_cancel_deletion_but_fresh_explicit_login_can(
    modern: Modern, container: Container
) -> None:
    """Recovery preserves the deletion marker; only fresh explicit login cancels the fourteen-day grace."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    proof = password_proof(service, user, token, "delete")
    deleted = service.delete_account(
        AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
        raw_token=token,
    )
    assert deleted.deletion_requested_at == clock()
    pending, code = delivered(modern, user.email, "recover")
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        finish_email(service, pending, code)
    assert authority_counts(service) == before
    assert (
        current_user(service, user.id).deletion_requested_at
        == deleted.deletion_requested_at
    )
    pending, code = delivered(modern, user.email)
    logged_in = finish_email(service, pending, code)
    assert isinstance(logged_in.payload, SignedInResult) and logged_in.raw_token
    assert logged_in.payload.deletion_cancelled
    assert logged_in.payload.user.id == user.id
    assert current_user(service, user.id).deletion_requested_at is None
    assert session_user(service, logged_in.raw_token).id == user.id
