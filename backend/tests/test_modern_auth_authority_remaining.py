"""Failure, retry and cleanup authority paths backed by the real Identity store."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Event
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr

from app.container import Container
from app.schemas.auth import User
from app.schemas.modern_auth import (
    AccountActionRequest,
    Action,
    AppleNativeCompleteRequest,
    EmailRequest,
    EmailResendRequest,
    PasswordConfirmRequest,
    ProviderCompleteRequest,
    ProviderStartRequest,
    ReauthenticatedResult,
    SignedInResult,
    VerifyMailboxResult,
)
from app.services.auth_mail_service import (
    AuthMailError,
    AuthMailRateLimitError,
    AuthMailService,
)
from app.services.auth_provider_service import (
    AuthProviderService,
    ProviderError,
    ProviderTokens,
)
from app.services.auth_secret_box import AuthSecretBox, AuthSecretError
from app.services.modern_auth_service import (
    ModernAuthError,
    ModernAuthService,
    ProviderStartResult,
)
from tests.test_modern_auth_apple_integration import AppleProvider, apple_runtime
from tests.test_modern_auth_authority_edges import (
    PASSWORD,
    REPLACEMENT,
    Modern,
    authority_counts,
    current_user,
    delivered,
    email_proof,
    finish_email,
    handoff,
    password_owner,
    password_proof,
    provider_owner,
    provider_proof,
    rows,
    session_user,
    start_provider,
)
from tests.test_modern_auth_service import VERIFIER, Clock, challenge, modern

__all__ = ["apple_runtime", "modern"]

pytestmark = [
    pytest.mark.allure_label("Authentication & Access", label_type="epic"),
    pytest.mark.allure_label("Modern authentication", label_type="feature"),
    pytest.mark.allure_label(
        "023-FR-004 023-FR-006 023-FR-008–019 023-FR-025 023-SC-003 Failure authority",
        label_type="story",
    ),
]

AppleRuntime = tuple[
    ModernAuthService,
    AuthMailService,
    list[tuple[str, str, str]],
    AppleProvider,
    Clock,
]


def test_023_FR_004_native_apple_attempt_cannot_use_web_callback(apple_runtime):
    """A native attempt cannot be exchanged through the browser return endpoint."""
    service, _, _, provider, _ = apple_runtime
    started, _ = native_start(service)
    with pytest.raises(ModernAuthError):
        service.provider_callback(
            "apple", code="synthetic-code", state=started.payload.state
        )
    assert provider.received == []
    assert authority_counts(service) == (0, 0, 0)


@pytest.mark.parametrize("claims", [None, []])
def test_023_FR_004_invalid_sealed_claims_cannot_consume_valid_handoff(modern, claims):
    """Authenticated storage with invalid claim shape grants no session or account."""
    service = modern[0]
    payload = handoff(service, start_provider(service))
    with service.store.transaction() as connection:
        row = connection.execute("SELECT * FROM auth_attempts").fetchone()
        original = row["sealed_payload"]
        sealed = service.box.seal(
            json.dumps(claims).encode(),
            service._attempt_context(row, "provider_identity"),
        )
        connection.execute(
            "UPDATE auth_attempts SET sealed_payload=? WHERE id=?",
            (sealed, payload.attempt_id),
        )
    with pytest.raises(ModernAuthError):
        service.complete_provider(payload)
    assert authority_counts(service) == (0, 0, 0)
    with service.store.transaction() as connection:
        connection.execute(
            "UPDATE auth_attempts SET sealed_payload=? WHERE id=?",
            (original, payload.attempt_id),
        )
    assert service.complete_provider(payload).payload.status == "signed_in"


def test_023_FR_007_unlink_rechecks_binding_after_independent_confirmation(modern):
    """A confirmed mailbox cannot unlink a provider that has since been retired."""
    service = modern[0]
    user, _ = provider_owner(modern)
    pending, code = delivered(modern, user.email)
    token = finish_email(service, pending, code).raw_token
    assert token
    proof = email_proof(modern, user, token, "unlink:google")
    with service.store.transaction() as connection:
        connection.execute("UPDATE auth_identity_bindings SET state='disabled'")
    before = authority_counts(service)
    with pytest.raises(ModernAuthError) as failure:
        service.unlink(
            "google",
            AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
            raw_token=token,
        )
    assert failure.value.status_code == 404
    assert authority_counts(service) == before
    assert session_user(service, token).id == user.id


@pytest.mark.parametrize("deletion_age", [None, timedelta(days=15)])
def test_023_FR_012_provider_login_cannot_cancel_stale_or_expired_deletion(
    modern, deletion_age
):
    """A staged login cannot undo a later deletion request or its expired grace."""
    service, _, _, _, clock = modern
    user, _ = provider_owner(modern)
    payload = handoff(service, start_provider(service))
    if deletion_age is None:
        clock.now += timedelta(seconds=1)
    requested_at = clock() - (deletion_age or timedelta())
    service.auth.user_repo.mutate(
        user.id,
        lambda fresh: fresh.model_copy(update={"deletion_requested_at": requested_at}),
    )
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.complete_provider(payload)
    assert authority_counts(service) == before
    assert current_user(service, user.id).deletion_requested_at == requested_at


@pytest.mark.parametrize("changed", ["deleted", "generation"])
def test_023_FR_004_provider_handoff_rechecks_binding_after_exchange(modern, changed):
    """A proved provider handoff cannot cross removal or replacement of its source."""
    service = modern[0]
    provider_owner(modern)
    payload = handoff(service, start_provider(service))
    with service.store.transaction() as connection:
        connection.execute(
            "DELETE FROM auth_identity_bindings"
            if changed == "deleted"
            else "UPDATE auth_identity_bindings SET generation=generation+1"
        )
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.complete_provider(payload)
    assert authority_counts(service) == before


def native_start(
    service: ModernAuthService,
    *,
    purpose: Literal["login", "link", "reauth"] = "login",
    user: User | None = None,
    token: str | None = None,
    action: Action | None = None,
    proof: str | None = None,
) -> tuple[ProviderStartResult, AppleNativeCompleteRequest]:
    started = service.start_provider(
        "apple",
        ProviderStartRequest(
            purpose=purpose,
            client="ios",
            client_challenge=challenge(),
            expected_account_id=user.id if user else None,
            action=action,
            recent_proof=proof,
        ),
        raw_token=token,
    )
    return started, AppleNativeCompleteRequest(
        attempt_id=started.payload.attempt_id,
        state=started.payload.state,
        authorization_code="synthetic-native-code",
        identity_token="synthetic-native-assertion",
        client_verifier=VERIFIER,
    )


def native_owner(runtime: AppleRuntime) -> tuple[User, str]:
    service = runtime[0]
    _, payload = native_start(service)
    result = service.complete_native_apple(payload)
    assert isinstance(result.payload, SignedInResult) and result.raw_token
    return current_user(service, result.payload.user.id), result.raw_token


def native_proof(
    service: ModernAuthService, user: User, token: str, action: Action
) -> str:
    _, payload = native_start(
        service, purpose="reauth", user=user, token=token, action=action
    )
    result = service.complete_native_apple(payload, raw_token=token)
    assert isinstance(result.payload, ReauthenticatedResult)
    assert result.raw_token is None
    return result.payload.recent_proof


@pytest.mark.parametrize("absent", ["mail_service", "smtp_configuration"])
def test_023_FR_003_email_unavailability_is_global_and_creates_no_pending_authority(
    modern: Modern, absent: str
) -> None:
    """Absent email setup gives the same safe outcome for every address without queueing proof material."""
    service = modern[0]
    if absent == "mail_service":
        service.mail = None
    else:
        service.settings = service.settings.model_copy(update={"smtp_host": ""})
    outcomes = []
    for email in ("new@example.com", "missing@example.com"):
        with pytest.raises(ModernAuthError) as failure:
            service.request_email(
                EmailRequest(
                    email=email,
                    purpose="login",
                    client="web",
                    client_challenge=challenge(),
                ),
                network="failure-tests",
            )
        outcomes.append(
            (failure.value.code, failure.value.status_code, str(failure.value))
        )
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][:2] == ("method_unavailable", 503)
    assert authority_counts(service) == (0, 0, 0)
    assert not rows(service, "SELECT * FROM auth_challenges")
    assert not rows(service, "SELECT * FROM auth_mail_jobs")


@pytest.mark.parametrize("operation", ["request", "resend", "verify"])
@pytest.mark.parametrize("limited", [False, True])
def test_023_FR_008_FR_010_mail_dependency_failure_neither_consumes_nor_grants_authority(
    modern: Modern, monkeypatch: pytest.MonkeyPatch, operation: str, limited: bool
) -> None:
    """Mail adapter failures expose a coarse retry outcome and preserve an already delivered valid code."""
    service, mail, _, _, clock = modern
    pending = None
    code = ""
    if operation != "request":
        pending, code = delivered(modern, "new@example.com")
        clock.now += timedelta(seconds=61)
    error: AuthMailError = AuthMailRateLimitError(60) if limited else AuthMailError()

    def unavailable(*_args: object, **_kwargs: object) -> Any:
        raise error

    before = authority_counts(service)
    with monkeypatch.context() as patch:
        patch.setattr(
            mail,
            {"request": "enqueue", "resend": "resend", "verify": "verify_code"}[
                operation
            ],
            unavailable,
        )
        with pytest.raises(ModernAuthError) as failure:
            if operation == "request":
                service.request_email(
                    EmailRequest(
                        email="new@example.com",
                        purpose="login",
                        client="web",
                        client_challenge=challenge(),
                    ),
                    network="failure-tests",
                )
            elif operation == "resend":
                assert pending
                service.resend_email(
                    EmailResendRequest(
                        challenge_id=pending.challenge_id, client_verifier=VERIFIER
                    ),
                    network="failure-tests",
                )
            else:
                assert pending
                finish_email(service, pending, code)
        assert failure.value.status_code == (429 if limited else 503)
    assert authority_counts(service) == before
    if pending:
        assert finish_email(service, pending, code).payload.status == "signed_in"
    else:
        assert not rows(service, "SELECT * FROM auth_challenges")
        assert not rows(service, "SELECT * FROM auth_mail_jobs")


@pytest.mark.parametrize("eligible", [False, True])
def test_023_FR_008_FR_009_resend_preserves_outer_expiry_and_neutral_ineligible_shape(
    modern: Modern, container: Container, eligible: bool
) -> None:
    """Resend enforces the minimum interval, replaces the delivered generation and preserves the outer deadline."""
    service, mail, sent, _, clock = modern
    email = "new@example.com"
    if not eligible:
        user, _ = password_owner(container, clock, verified=False)
        email = user.email
    pending = service.request_email(
        EmailRequest(
            email=email, purpose="login", client="web", client_challenge=challenge()
        ),
        network="resend-tests",
    )
    if eligible:
        assert mail.dispatch_one()
        original_code = sent[-1][1]
    payload = EmailResendRequest(
        challenge_id=pending.challenge_id, client_verifier=VERIFIER
    )
    with pytest.raises(ModernAuthError) as too_early:
        service.resend_email(payload, network="resend-tests")
    assert too_early.value.status_code == 429
    clock.now += timedelta(seconds=60)
    renewed = service.resend_email(payload, network="resend-tests")
    assert renewed.challenge_id == pending.challenge_id
    assert renewed.expires_at == pending.expires_at
    assert renewed.message == pending.message
    assert renewed.resend_at == clock() + timedelta(seconds=60)
    if eligible:
        assert mail.dispatch_one()
        new_code = sent[-1][1]
        if new_code != original_code:
            with pytest.raises(ModernAuthError):
                finish_email(service, pending, original_code)
        assert finish_email(service, pending, new_code).payload.status == "signed_in"
    else:
        assert not mail.dispatch_one() and not sent
        with pytest.raises(ModernAuthError):
            finish_email(service, pending, "123456")
        assert authority_counts(service) == (1, 0, 1)


def test_023_FR_008_FR_009_exhausted_challenge_cannot_reset_guesses_by_resending(
    modern: Modern,
) -> None:
    """Five rejected guesses remain committed and resend cannot revive the challenge."""
    service, _, _, _, clock = modern
    pending, code = delivered(modern, "new@example.com")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(ModernAuthError):
            finish_email(service, pending, wrong)
    clock.now += timedelta(seconds=60)
    with pytest.raises(ModernAuthError) as failure:
        service.resend_email(
            EmailResendRequest(
                challenge_id=pending.challenge_id, client_verifier=VERIFIER
            ),
            network="guess-tests",
        )
    assert failure.value.status_code == 429
    assert (
        rows(
            service,
            "SELECT failures FROM auth_challenges WHERE id=?",
            (pending.challenge_id,),
        )[0][0]
        == 5
    )
    assert authority_counts(service) == (0, 0, 0)


@pytest.mark.parametrize(
    "invalid",
    [
        "public_mailbox",
        "reserved",
        "foreign_destination",
        "unverified_reauth",
        "missing_action",
        "wrong_action",
        "missing_proof",
    ],
)
def test_023_FR_006_FR_014_protected_email_cannot_borrow_missing_or_foreign_authority(
    modern: Modern, container: Container, invalid: str
) -> None:
    """Protected email operations reject wrong destination, intent or source before enqueueing any proof."""
    service, mail, _, _, clock = modern
    user, token = password_owner(
        container, clock, verified=invalid != "unverified_reauth"
    )
    proof = password_proof(service, user, token, "change_email")
    payload = EmailRequest(
        email=user.email,
        purpose="reauth",
        client="web",
        client_challenge=challenge(),
        expected_account_id=user.id,
        action="export",
    )
    if invalid == "public_mailbox":
        payload = payload.model_copy(update={"purpose": "provider_mailbox"})
    elif invalid == "reserved":
        service.auth.reserved_emails = frozenset({user.email})
    elif invalid == "foreign_destination":
        payload = payload.model_copy(update={"email": "foreign@example.com"})
    elif invalid == "missing_action":
        payload = payload.model_copy(update={"action": None})
    elif invalid in {"wrong_action", "missing_proof"}:
        payload = payload.model_copy(
            update={
                "purpose": "change_email",
                "recent_proof": proof if invalid == "wrong_action" else None,
                "action": "export" if invalid == "wrong_action" else "change_email",
            }
        )
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.request_email(payload, network="protected-tests", raw_token=token)
    assert authority_counts(service) == before
    assert not mail.dispatch_one()
    assert not rows(service, "SELECT * FROM auth_challenges")


def test_023_FR_008_code_rechecked_after_concurrent_resend_cannot_issue_a_session(
    modern: Modern, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A code replaced after its first check cannot issue authority from an earlier generation."""
    service, mail, sent, _, clock = modern
    pending, code = delivered(modern, "new@example.com")
    original = mail.verify_code

    def check_then_resend(identifier: str, candidate: str, *, network: str) -> bool:
        verified = original(identifier, candidate, network=network)
        clock.now += timedelta(seconds=61)
        service.resend_email(
            EmailResendRequest(challenge_id=identifier, client_verifier=VERIFIER),
            network=network,
        )
        return verified

    with monkeypatch.context() as patch:
        patch.setattr(mail, "verify_code", check_then_resend)
        with pytest.raises(ModernAuthError):
            finish_email(service, pending, code)
    assert authority_counts(service) == (0, 0, 0)
    assert mail.dispatch_one()
    assert finish_email(service, pending, sent[-1][1]).payload.status == "signed_in"


def test_023_FR_014_login_rechecks_mailbox_authority_after_the_code_check(
    modern: Modern, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrently unverified mailbox cannot retain login authority through an already checked code."""
    service, mail, _, _, clock = modern
    user, _ = password_owner(container, clock)
    pending, code = delivered(modern, user.email)
    original = mail.verify_code

    def check_then_unverify(identifier: str, candidate: str, *, network: str) -> bool:
        verified = original(identifier, candidate, network=network)
        container.user_repo.mutate(
            user.id, lambda fresh: fresh.model_copy(update={"email_verified_at": None})
        )
        return verified

    monkeypatch.setattr(mail, "verify_code", check_then_unverify)
    before = authority_counts(service)
    with pytest.raises(ModernAuthError) as failure:
        finish_email(service, pending, code)
    assert failure.value.status_code == 404
    assert authority_counts(service) == before
    assert current_user(service, user.id).email_verified_at is None


def test_023_FR_005_new_address_claimed_after_delivery_requires_existing_account_login(
    modern: Modern, container: Container
) -> None:
    """A signup code cannot seize an account created at that address while the code was in flight."""
    service = modern[0]
    pending, code = delivered(modern, "claimed@example.com")
    existing = container.auth_service.seed_admin(
        email="claimed@example.com", password=PASSWORD
    )
    result = finish_email(service, pending, code)
    assert (
        result.payload.status == "existing_account_required"
        and result.raw_token is None
    )
    assert authority_counts(service) == (1, 0, 0)
    assert current_user(service, existing.id).password_hash == existing.password_hash
    with pytest.raises(ModernAuthError):
        finish_email(service, pending, code)


@pytest.mark.parametrize("purpose", ["login", "recover", "reauth"])
def test_023_FR_017_operator_configuration_changed_after_delivery_blocks_old_email_proof(
    modern: Modern, container: Container, purpose: Literal["login", "recover", "reauth"]
) -> None:
    """A delivered public or protected email code cannot become an operator shortcut after configuration changes."""
    service, _, _, _, clock = modern
    if purpose == "login":
        pending, code = delivered(modern, "operator@example.com")
        email = "operator@example.com"
        token = None
    else:
        user, token = password_owner(container, clock)
        email = user.email
        pending, code = delivered(
            modern,
            email,
            purpose,
            user=user if purpose == "reauth" else None,
            token=token if purpose == "reauth" else None,
            action="export" if purpose == "reauth" else None,
        )
    service.auth.reserved_emails = frozenset({email})
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        finish_email(service, pending, code, token=token)
    assert authority_counts(service) == before
    assert not rows(service, "SELECT * FROM auth_proofs")


@pytest.mark.parametrize("purpose", ["recover", "reauth"])
def test_023_FR_011_FR_013_mailbox_disabled_after_delivery_cannot_issue_account_proofs(
    modern: Modern, container: Container, purpose: Literal["recover", "reauth"]
) -> None:
    """Delivered recovery or confirmation code cannot survive revocation of its verified mailbox authority."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    pending, code = delivered(
        modern,
        user.email,
        purpose,
        user=user if purpose == "reauth" else None,
        token=token if purpose == "reauth" else None,
        action="export" if purpose == "reauth" else None,
    )
    container.user_repo.mutate(
        user.id, lambda fresh: fresh.model_copy(update={"email_verified_at": None})
    )
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        finish_email(service, pending, code, token=token)
    assert authority_counts(service) == before
    assert not rows(service, "SELECT * FROM auth_proofs")


def test_023_FR_014_pending_legacy_verification_rejects_a_renewed_provider_source(
    modern: Modern, container: Container
) -> None:
    """Pending legacy verification cannot substitute a social recent grant for the original password authority."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock, verified=False)
    linked = start_provider(
        service,
        purpose="link",
        user=user,
        token=token,
        action="link:google",
        proof=password_proof(service, user, token, "link:google"),
    )
    assert (
        service.complete_provider(
            handoff(service, linked), raw_token=token
        ).payload.status
        == "linked"
    )
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
    wrong_source = provider_proof(service, user, token, "verify_email")
    with pytest.raises(ModernAuthError) as failure:
        finish_email(service, pending, code, token=token, proof=wrong_source)
    assert failure.value.status_code == 403
    assert current_user(service, user.id).email_verified_at is None
    assert (
        finish_email(service, pending, code, token=token).payload.status
        == "verified_email"
    )


@pytest.mark.parametrize("incorrect", ["password", "changed_during_check"])
def test_023_FR_006_password_confirmation_rechecks_the_exact_verified_credential(
    modern: Modern,
    container: Container,
    monkeypatch: pytest.MonkeyPatch,
    incorrect: str,
) -> None:
    """A wrong password or authority changed during password verification cannot mint a recent grant."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    if incorrect == "changed_during_check":
        original = service.auth.verify_password

        def checked_old_password(snapshot: User, raw: str) -> bool:
            matched = original(snapshot, raw)
            monkeypatch.setattr(service.auth, "verify_password", original)
            container.account_service.change_password(
                user,
                current_password=PASSWORD,
                new_password=REPLACEMENT,
                keep_token_hash=service.auth.hash_session_token(token),
            )
            return matched

        monkeypatch.setattr(service.auth, "verify_password", checked_old_password)
    with pytest.raises(ModernAuthError) as failure:
        service.confirm_password(
            PasswordConfirmRequest(
                current_password=(
                    "wrong-password" if incorrect == "password" else PASSWORD
                ),
                expected_account_id=user.id,
                action="export",
            ),
            raw_token=token,
        )
    assert failure.value.status_code == 403
    assert not rows(service, "SELECT * FROM auth_proofs")
    assert session_user(service, token).id == user.id


@pytest.mark.parametrize("operation", ["email", "provider", "recent"])
def test_023_FR_008_SC_003_lost_atomic_consumption_write_cannot_grant_authority(
    modern: Modern, container: Container, operation: str
) -> None:
    """A real SQLite trigger that refuses consumption prevents the protected effect and preserves retry state."""
    service, _, _, _, clock = modern
    if operation == "email":
        pending, code = delivered(modern, "new@example.com")
        trigger = "CREATE TRIGGER refuse_consume BEFORE UPDATE OF status ON auth_challenges WHEN NEW.status='consumed' BEGIN SELECT RAISE(IGNORE); END"
    elif operation == "provider":
        payload = handoff(service, start_provider(service))
        trigger = "CREATE TRIGGER refuse_consume BEFORE UPDATE OF status ON auth_attempts WHEN NEW.status='consumed' BEGIN SELECT RAISE(IGNORE); END"
    else:
        user, token = password_owner(container, clock)
        proof = password_proof(service, user, token, "export")
        trigger = "CREATE TRIGGER refuse_consume BEFORE UPDATE OF consumed_at ON auth_proofs WHEN NEW.consumed_at IS NOT NULL BEGIN SELECT RAISE(IGNORE); END"
    with service.store.transaction() as connection:
        connection.execute(trigger)
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        if operation == "email":
            finish_email(service, pending, code)
        elif operation == "provider":
            service.complete_provider(payload)
        else:
            service.export_account(
                AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
                raw_token=token,
            )
    assert authority_counts(service) == before
    with service.store.transaction() as connection:
        connection.execute("DROP TRIGGER refuse_consume")
    if operation == "email":
        assert finish_email(service, pending, code).payload.status == "signed_in"
    elif operation == "provider":
        assert service.complete_provider(payload).payload.status == "signed_in"
    else:
        _, stream = service.export_account(
            AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
            raw_token=token,
        )
        stream.close()


@pytest.mark.parametrize("failure_kind", ["unavailable", "assertion", "secret"])
def test_023_FR_004_failed_provider_exchange_erases_the_lease_and_never_retries_the_code(
    modern: Modern, monkeypatch: pytest.MonkeyPatch, failure_kind: str
) -> None:
    """A failed bounded provider exchange retires the attempt without exposing upstream inputs or retrying its code."""
    service, _, _, provider, _ = modern
    started = start_provider(service)
    error = (
        AuthSecretError()
        if failure_kind == "secret"
        else ProviderError(
            "provider_unavailable" if failure_kind == "unavailable" else "invalid_proof"
        )
    )

    def failed_exchange(*_args: object, **_kwargs: object) -> ProviderTokens:
        raise error

    monkeypatch.setattr(provider, "exchange_google", failed_exchange)
    with pytest.raises(ModernAuthError) as failure:
        handoff(service, started)
    assert failure.value.status_code == (503 if failure_kind == "unavailable" else 400)
    attempt = rows(service, "SELECT * FROM auth_attempts")[0]
    assert attempt["status"] == "failed" and attempt["sealed_payload"] is None
    assert attempt["lease_id"] is None
    with pytest.raises(ModernAuthError):
        handoff(service, started)
    assert authority_counts(service) == (0, 0, 0)
    assert not rows(service, "SELECT * FROM auth_handoffs")


@pytest.mark.parametrize("fault", ["box_missing", "retired_key", "tampered_payload"])
def test_023_FR_004_provider_attempt_key_protection_fails_closed_at_the_service_boundary(
    modern: Modern, fault: str
) -> None:
    """Absent protection, retired keys and corrupted sealed attempts cannot issue a returning grant."""
    service = modern[0]
    if fault == "box_missing":
        service.box = None
        with pytest.raises(ModernAuthError) as failure:
            start_provider(service)
        assert failure.value.status_code == 503
        assert not rows(service, "SELECT * FROM auth_attempts")
    else:
        started = start_provider(service)
        if fault == "retired_key":
            service.box = AuthSecretBox({"k2": b"2" * 32}, "k2")
        else:
            with service.store.transaction() as connection:
                connection.execute(
                    "UPDATE auth_attempts SET sealed_payload='corrupted' WHERE id=?",
                    (started.payload.attempt_id,),
                )
        with pytest.raises(ModernAuthError):
            handoff(service, started)
    assert authority_counts(service) == (0, 0, 0)
    assert not rows(service, "SELECT * FROM auth_handoffs")


@pytest.mark.parametrize("mismatch", ["provider", "audience"])
def test_023_FR_004_provider_adapter_cannot_stage_identity_for_another_attempt_profile(
    modern: Modern, mismatch: str
) -> None:
    """Even a faulty provider adapter cannot stage a different provider or audience under an existing attempt."""
    service, _, _, provider, _ = modern
    started = start_provider(service)
    provider.identity = replace(
        provider.identity,
        provider="apple" if mismatch == "provider" else "google",
        audience=(
            "foreign-client" if mismatch == "audience" else provider.identity.audience
        ),
    )
    with pytest.raises(ModernAuthError):
        handoff(service, started)
    assert authority_counts(service) == (0, 0, 0)
    assert not rows(service, "SELECT * FROM auth_handoffs")
    assert rows(service, "SELECT status FROM auth_attempts")[0][0] == "failed"


@pytest.mark.parametrize("authoritative", [False, True])
@pytest.mark.parametrize("address", [None, "reserved@example.com"])
def test_023_FR_014_FR_017_new_provider_identity_requires_an_eligible_destination(
    modern: Modern, authoritative: bool, address: str | None
) -> None:
    """Missing or newly reserved provider destinations cannot grant signup or mailbox-verification authority."""
    service, _, _, provider, _ = modern
    provider.identity = replace(
        provider.identity, email=address, email_authoritative=authoritative
    )
    payload = handoff(service, start_provider(service))
    service.auth.reserved_emails = frozenset({"reserved@example.com"})
    with pytest.raises(ModernAuthError):
        service.complete_provider(payload)
    assert authority_counts(service) == (0, 0, 0)
    assert not rows(service, "SELECT * FROM auth_challenges")


def test_023_FR_004_corrupt_staged_provider_ciphertext_cannot_consume_the_handoff(
    modern: Modern,
) -> None:
    """Corrupt stored assertion ciphertext fails before handoff consumption or account mutation."""
    service = modern[0]
    payload = handoff(service, start_provider(service))
    with service.store.transaction() as connection:
        connection.execute(
            "UPDATE auth_attempts SET sealed_payload='corrupted' WHERE id=?",
            (payload.attempt_id,),
        )
    with pytest.raises(ModernAuthError):
        service.complete_provider(payload)
    assert authority_counts(service) == (0, 0, 0)
    assert rows(service, "SELECT consumed_at FROM auth_handoffs")[0][0] is None


@pytest.mark.parametrize("corruption", ["destination", "attempt_state"])
def test_023_FR_014_mailbox_completion_rejects_inconsistent_staged_identity_state(
    modern: Modern, corruption: str
) -> None:
    """A mailbox challenge cannot finalize a different destination or a superseded provider state."""
    service, mail, sent, provider, _ = modern
    provider.identity = replace(
        provider.identity, email="external@example.com", email_authoritative=False
    )
    staged = service.complete_provider(handoff(service, start_provider(service)))
    assert isinstance(staged.payload, VerifyMailboxResult)
    assert mail.dispatch_one()
    with service.store.transaction() as connection:
        if corruption == "destination":
            connection.execute(
                "UPDATE auth_challenges SET destination='different@example.com' WHERE id=?",
                (staged.payload.challenge_id,),
            )
        else:
            connection.execute(
                "UPDATE auth_attempts SET status='started' WHERE id=(SELECT attempt_id FROM auth_challenges WHERE id=?)",
                (staged.payload.challenge_id,),
            )
    with pytest.raises(ModernAuthError):
        finish_email(service, staged.payload, sent[-1][1])
    assert authority_counts(service) == (0, 0, 0)


def test_023_FR_004_FR_009_provider_attempt_budget_survives_instances_and_key_rotation(
    modern: Modern,
) -> None:
    """Provider starts cannot reset durable client abuse counters by recreating service or rotating a key."""
    service, mail, _, provider, clock = modern
    for _ in range(25):
        start_provider(service)
    restarted = ModernAuthService(
        auth_service=service.auth,
        account_service=service.account,
        settings=service.settings,
        secret_box=service.box,
        provider_service=cast(AuthProviderService, provider),
        mail_service=mail,
        clock=clock,
    )
    restarted.box = AuthSecretBox({"k2": b"2" * 32, "k1": b"1" * 32}, "k2")
    with pytest.raises(ModernAuthError) as exhausted:
        start_provider(restarted)
    assert exhausted.value.status_code == 429
    restarted.box = AuthSecretBox({"k2": b"2" * 32}, "k2")
    with pytest.raises(ModernAuthError) as missing_old_key:
        start_provider(restarted)
    assert missing_old_key.value.status_code == 503
    assert authority_counts(service) == (0, 0, 0)
    assert len(rows(service, "SELECT * FROM auth_attempts")) == 25
    clock.now += timedelta(hours=24, seconds=1)
    assert not restarted.dispatch_one()
    assert not rows(service, "SELECT * FROM auth_attempts")
    assert start_provider(restarted).payload.attempt_id


def test_023_FR_009_network_start_budget_cannot_be_evaded_with_new_client_challenges(
    modern: Modern,
) -> None:
    """Changing client proof challenges cannot evade the independent provider network start budget."""
    service = modern[0]
    for index in range(100):
        service.start_provider(
            "google",
            ProviderStartRequest(
                purpose="login",
                client="web",
                client_challenge=challenge(f"{index:04d}" + "v" * 43),
            ),
            network="same-network",
        )
    with pytest.raises(ModernAuthError) as failure:
        service.start_provider(
            "google",
            ProviderStartRequest(
                purpose="login",
                client="web",
                client_challenge=challenge("last" + "v" * 43),
            ),
            network="same-network",
        )
    assert failure.value.status_code == 429
    assert len(rows(service, "SELECT * FROM auth_attempts")) == 100
    assert authority_counts(service) == (0, 0, 0)


@pytest.mark.parametrize(
    "invalid",
    [
        "unknown_provider",
        "operator",
        "missing_action",
        "wrong_link_action",
        "missing_proof",
    ],
)
def test_023_FR_006_FR_017_provider_start_rejects_unusable_protected_intent(
    modern: Modern, container: Container, invalid: str
) -> None:
    """Unsupported provider or protected intent cannot capture the cookie or create an attempt."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    proof = password_proof(service, user, token, "link:google")
    if invalid == "operator":
        service.auth.reserved_emails = frozenset({user.email})
    request = ProviderStartRequest(
        purpose="link",
        client="web",
        client_challenge=challenge(),
        expected_account_id=user.id,
        action="link:google",
        recent_proof=proof,
    )
    if invalid == "missing_action":
        request = request.model_copy(update={"action": None})
    elif invalid == "wrong_link_action":
        request = request.model_copy(update={"action": "link:apple"})
    elif invalid == "missing_proof":
        request = request.model_copy(update={"recent_proof": None})
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.start_provider(
            cast(Any, "unknown") if invalid == "unknown_provider" else "google",
            request,
            raw_token=token,
        )
    assert authority_counts(service) == before
    assert not rows(service, "SELECT * FROM auth_attempts")


def test_023_FR_006_explicit_relink_creates_new_removed_identity_authority(
    modern: Modern,
) -> None:
    """A fresh confirmed link creates new identity authority without changing account email or issuing a session."""
    service = modern[0]
    user, provider_token = provider_owner(modern)
    pending, code = delivered(modern, user.email)
    token = finish_email(service, pending, code).raw_token
    assert token
    prior = rows(service, "SELECT * FROM auth_identity_bindings")[0]
    unlink = provider_proof(service, user, provider_token, "unlink:google")
    service.unlink(
        "google",
        AccountActionRequest(recent_proof=unlink, expected_account_id=user.id),
        raw_token=provider_token,
    )
    assert not rows(service, "SELECT * FROM auth_identity_bindings")
    linked = start_provider(
        service,
        purpose="link",
        user=user,
        token=token,
        action="link:google",
        proof=email_proof(modern, user, token, "link:google"),
    )
    result = service.complete_provider(handoff(service, linked), raw_token=token)
    current = rows(service, "SELECT * FROM auth_identity_bindings")[0]
    assert result.payload.status == "linked" and result.raw_token is None
    assert current["id"] != prior["id"] and current["state"] == "active"
    assert current["generation"] == 1
    assert authority_counts(service) == (1, 1, 1)
    assert session_user(service, token).email == user.email


def test_023_FR_006_link_cannot_replace_an_existing_provider_subject(
    modern: Modern,
) -> None:
    """A newly proved second subject cannot overwrite an account's already connected provider identity."""
    service, _, _, provider, _ = modern
    user, token = provider_owner(modern)
    old_binding = rows(service, "SELECT * FROM auth_identity_bindings")
    proof = provider_proof(service, user, token, "link:google")
    provider.identity = replace(
        provider.identity, subject="second-subject", email="second@gmail.com"
    )
    started = start_provider(
        service,
        purpose="link",
        user=user,
        token=token,
        action="link:google",
        proof=proof,
    )
    with pytest.raises(ModernAuthError) as failure:
        service.complete_provider(handoff(service, started), raw_token=token)
    assert failure.value.status_code == 409
    assert rows(service, "SELECT * FROM auth_identity_bindings") == old_binding
    assert authority_counts(service) == (1, 1, 1)


def test_023_FR_006_stale_explicit_link_cannot_cross_removal_and_reconnection(
    modern: Modern,
) -> None:
    """An older staged explicit link cannot undo a later authorization and unlink generation."""
    service = modern[0]
    user, original_token = provider_owner(modern)
    pending, code = delivered(modern, user.email)
    independent = finish_email(service, pending, code).raw_token
    assert independent
    link = email_proof(modern, user, independent, "link:google")
    stale = handoff(
        service,
        start_provider(
            service,
            purpose="link",
            user=user,
            token=independent,
            action="link:google",
            proof=link,
        ),
    )
    proof = provider_proof(service, user, original_token, "unlink:google")
    service.unlink(
        "google",
        AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
        raw_token=original_token,
    )
    with pytest.raises(ModernAuthError):
        service.complete_provider(stale, raw_token=independent)
    linked = start_provider(
        service,
        purpose="link",
        user=user,
        token=independent,
        action="link:google",
        proof=email_proof(modern, user, independent, "link:google"),
    )
    assert (
        service.complete_provider(
            handoff(service, linked), raw_token=independent
        ).payload.status
        == "linked"
    )
    fresh = service.complete_provider(handoff(service, start_provider(service)))
    assert fresh.raw_token
    proof = provider_proof(service, user, fresh.raw_token, "unlink:google")
    service.unlink(
        "google",
        AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
        raw_token=fresh.raw_token,
    )
    before = authority_counts(service)
    with pytest.raises(ModernAuthError):
        service.complete_provider(stale, raw_token=independent)
    assert authority_counts(service) == before
    assert not rows(service, "SELECT * FROM auth_identity_bindings")


@pytest.mark.parametrize("changed", ["state", "generation"])
def test_023_FR_006_partially_retired_provider_source_cannot_authorize_existing_recent_grant(
    modern: Modern, changed: str
) -> None:
    """A partially applied provider-source retirement cannot leave an old recent grant usable."""
    service = modern[0]
    user, token = provider_owner(modern)
    proof = provider_proof(service, user, token, "export")
    with service.store.transaction() as connection:
        connection.execute(
            "UPDATE auth_identity_bindings SET state='disabled'"
            if changed == "state"
            else "UPDATE auth_identity_bindings SET generation=generation+1"
        )
    before = authority_counts(service)
    with pytest.raises(ModernAuthError) as failure:
        service.export_account(
            AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
            raw_token=token,
        )
    assert failure.value.status_code == (401 if changed == "state" else 403)
    assert authority_counts(service) == before


def test_023_FR_006_source_retired_during_consume_cannot_mint_provider_recent_authority(
    modern: Modern,
) -> None:
    """A source revoked at the durable attempt transition cannot mint a recent provider proof."""
    service = modern[0]
    user, token = provider_owner(modern)
    started = start_provider(
        service, purpose="reauth", user=user, token=token, action="export"
    )
    payload = handoff(service, started)
    with service.store.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER retire_source AFTER UPDATE OF status ON auth_attempts WHEN NEW.status='consumed' AND NEW.intent='reauth' BEGIN UPDATE auth_identity_bindings SET state='disabled' WHERE user_id=NEW.user_id AND provider=NEW.provider; END"
        )
    before = authority_counts(service)
    with pytest.raises(ModernAuthError) as failure:
        service.complete_provider(payload, raw_token=token)
    assert failure.value.status_code == 403
    assert authority_counts(service) == before
    assert not rows(service, "SELECT * FROM auth_proofs")
    assert rows(service, "SELECT state FROM auth_identity_bindings")[0][0] == "active"


def test_023_FR_025_apple_web_callback_seals_grant_and_uses_web_audience(
    apple_runtime: AppleRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apple's web callback selects the Services ID and seals its cleanup grant before issuing a session."""
    service, _, _, provider, _ = apple_runtime
    provider.identity = replace(
        provider.identity, audience=service.settings.apple_services_id
    )
    received: list[dict[str, Any]] = []

    def web_exchange(_code: str, **kwargs: Any) -> ProviderTokens:
        received.append(kwargs)
        return ProviderTokens(
            provider.identity,
            provider.identity.audience,
            SecretStr("synthetic-web-revocation-grant"),
            "refresh_token",
        )

    monkeypatch.setattr(provider, "exchange_apple", web_exchange)
    started = service.start_provider(
        "apple",
        ProviderStartRequest(
            purpose="login", client="web", client_challenge=challenge()
        ),
    )
    returned = service.provider_callback(
        "apple",
        code="synthetic-web-code",
        state=started.payload.state,
        binder=started.binder,
    )
    fields = parse_qs(urlsplit(returned.url).fragment)
    result = service.complete_provider(
        ProviderCompleteRequest(
            attempt_id=fields["attempt"][0],
            state=fields["state"][0],
            handoff_code=fields["grant"][0],
            client_verifier=VERIFIER,
        )
    )
    assert result.payload.status == "signed_in" and result.raw_token
    assert received[0]["nonce"] == started.payload.nonce
    assert "redirect_uri" in received[0] and "native_identity_token" not in received[0]
    grant = rows(service, "SELECT * FROM auth_apple_grants")[0]
    assert grant["issuing_client"] == service.settings.apple_services_id
    assert "synthetic-web-revocation-grant" not in grant["sealed_payload"]
    assert authority_counts(service) == (1, 1, 1)


@pytest.mark.parametrize("wrong", ["provider", "channel", "state"])
def test_023_FR_004_native_apple_completion_rejects_a_foreign_attempt_profile(
    apple_runtime: AppleRuntime, wrong: str
) -> None:
    """Native Apple completion refuses a broker or state belonging to another provider or channel."""
    service, _, _, provider, _ = apple_runtime
    if wrong == "provider":
        started = service.start_provider(
            "google",
            ProviderStartRequest(
                purpose="login", client="ios", client_challenge=challenge()
            ),
        )
        payload = AppleNativeCompleteRequest(
            attempt_id=started.payload.attempt_id,
            state=started.payload.state,
            authorization_code="synthetic",
            identity_token="synthetic",
            client_verifier=VERIFIER,
        )
    elif wrong == "channel":
        started = service.start_provider(
            "apple",
            ProviderStartRequest(
                purpose="login", client="web", client_challenge=challenge()
            ),
        )
        payload = AppleNativeCompleteRequest(
            attempt_id=started.payload.attempt_id,
            state=started.payload.state,
            authorization_code="synthetic",
            identity_token="synthetic",
            client_verifier=VERIFIER,
        )
    else:
        _, payload = native_start(service)
        payload = payload.model_copy(update={"state": "f" * 43})
    with pytest.raises(ModernAuthError):
        service.complete_native_apple(payload)
    assert not provider.received
    assert authority_counts(service) == (0, 0, 0)


@pytest.mark.parametrize("protection_failure", ["tampered_payload", "retired_key"])
def test_023_FR_004_native_apple_damaged_start_state_is_a_coarse_invalid_proof(
    apple_runtime: AppleRuntime, protection_failure: str
) -> None:
    """Damaged or no-longer-decryptable native start state fails before provider exchange or authority creation."""
    service, _, _, provider, _ = apple_runtime
    _, payload = native_start(service)
    if protection_failure == "tampered_payload":
        with service.store.transaction() as connection:
            connection.execute(
                "UPDATE auth_attempts SET sealed_payload='damaged-synthetic-envelope' WHERE id=?",
                (payload.attempt_id,),
            )
    else:
        service.box = AuthSecretBox({"k2": b"2" * 32}, "k2")
    with pytest.raises(ModernAuthError) as failure:
        service.complete_native_apple(payload)
    assert (failure.value.code, failure.value.status_code) == ("invalid_proof", 400)
    assert not provider.received
    assert authority_counts(service) == (0, 0, 0)
    assert not rows(service, "SELECT * FROM auth_apple_grants")


@pytest.mark.parametrize(
    "failure_kind",
    [
        "unavailable",
        "assertion",
        "secret",
        "missing_lifecycle",
        "missing_grant",
        "lease_expired",
    ],
)
def test_023_FR_004_FR_025_native_apple_failure_retires_attempt_and_rolls_back_authority(
    apple_runtime: AppleRuntime, monkeypatch: pytest.MonkeyPatch, failure_kind: str
) -> None:
    """Native provider, protection and lifecycle failures retire the lease and roll back account, binding and grant creation."""
    service, _, _, provider, clock = apple_runtime
    _, payload = native_start(service)

    def exchange(_code: str, **_kwargs: object) -> ProviderTokens:
        if failure_kind in {"unavailable", "assertion"}:
            raise ProviderError(
                "provider_unavailable"
                if failure_kind == "unavailable"
                else "invalid_proof"
            )
        if failure_kind == "secret":
            raise AuthSecretError()
        if failure_kind == "lease_expired":
            clock.now += timedelta(seconds=30)
        return ProviderTokens(
            provider.identity,
            provider.identity.audience,
            None if failure_kind == "missing_grant" else SecretStr("synthetic-grant"),
            "refresh_token",
        )

    monkeypatch.setattr(provider, "exchange_apple", exchange)
    if failure_kind == "missing_lifecycle":
        service.apple = None
    with pytest.raises(ModernAuthError) as failure:
        service.complete_native_apple(payload)
    assert failure.value.status_code == (
        503 if failure_kind in {"unavailable", "missing_lifecycle"} else 400
    )
    assert authority_counts(service) == (0, 0, 0)
    assert not rows(service, "SELECT * FROM auth_apple_grants")
    attempt = rows(service, "SELECT * FROM auth_attempts")[0]
    assert attempt["status"] == "failed" and attempt["sealed_payload"] is None
    assert attempt["lease_id"] is None


def test_023_FR_004_overlapping_native_callbacks_cannot_erase_the_first_exchange_lease(
    apple_runtime: AppleRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duplicate native request is refused while the original leased exchange alone completes."""
    service, _, _, provider, _ = apple_runtime
    _, payload = native_start(service)
    exchanging, release = Event(), Event()
    calls: list[str] = []

    def exchange(code: str, **_kwargs: object) -> ProviderTokens:
        calls.append(code)
        exchanging.set()
        assert release.wait(timeout=5)
        return ProviderTokens(
            provider.identity,
            provider.identity.audience,
            SecretStr("synthetic-grant"),
            "refresh_token",
        )

    monkeypatch.setattr(provider, "exchange_apple", exchange)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.complete_native_apple, payload)
        assert exchanging.wait(timeout=5)
        try:
            with pytest.raises(ModernAuthError):
                service.complete_native_apple(payload)
        finally:
            release.set()
        result = future.result(timeout=5)
    assert result.payload.status == "signed_in" and result.raw_token
    assert len(calls) == 1 and authority_counts(service) == (1, 1, 1)


def test_023_FR_014_native_apple_mailbox_proof_finalizes_the_original_grant_without_handoff(
    apple_runtime: AppleRuntime,
) -> None:
    """Non-authoritative native Apple email stages no account and finalizes once through the original mailbox verifier."""
    service, mail, sent, provider, _ = apple_runtime
    provider.identity = replace(provider.identity, email_authoritative=False)
    _, payload = native_start(service)
    staged = service.complete_native_apple(payload)
    assert isinstance(staged.payload, VerifyMailboxResult) and staged.raw_token is None
    assert authority_counts(service) == (0, 0, 0)
    with pytest.raises(ModernAuthError):
        service.complete_native_apple(payload)
    assert mail.dispatch_one()
    result = finish_email(service, staged.payload, sent[-1][1])
    assert result.payload.status == "signed_in" and result.raw_token
    assert authority_counts(service) == (1, 1, 1)
    assert len(rows(service, "SELECT * FROM auth_apple_grants")) == 1
    assert not rows(service, "SELECT * FROM auth_handoffs")


def test_023_FR_006_FR_025_native_apple_reauth_and_unlink_preserve_independent_email_session(
    apple_runtime: AppleRuntime,
) -> None:
    """Apple confirmation is purpose-bound, and unlink revokes provider authority while independent mailbox access survives."""
    service, _, _, _, _ = apple_runtime
    user, apple_token = native_owner(apple_runtime)
    pending, code = delivered(cast(Modern, apple_runtime), user.email)
    email_token = finish_email(service, pending, code).raw_token
    assert email_token
    proof = native_proof(service, user, apple_token, "unlink:apple")
    result = service.unlink(
        "apple",
        AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
        raw_token=apple_token,
    )
    assert result.signed_out and service.auth.get_user_for_token(apple_token) is None
    assert session_user(service, email_token).id == user.id
    assert rows(service, "SELECT reason FROM auth_apple_cleanup_jobs")[0][0] == "unlink"
    assert service.dispatch_one()
    assert not rows(service, "SELECT * FROM auth_apple_grants")


def test_023_FR_013_FR_025_passwordless_apple_deletion_schedules_cleanup_and_preserves_deadline(
    apple_runtime: AppleRuntime,
) -> None:
    """Passwordless Apple confirmation can request deletion and revocation without changing its fourteen-day purge deadline."""
    service, _, _, _, clock = apple_runtime
    user, token = native_owner(apple_runtime)
    proof = native_proof(service, user, token, "delete")
    deleted = service.delete_account(
        AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
        raw_token=token,
    )
    assert deleted.deletion_requested_at == clock()
    assert service.account.purge_at_for(deleted) == clock() + timedelta(days=14)
    assert service.auth.get_user_for_token(token) is None
    assert rows(service, "SELECT reason FROM auth_apple_cleanup_jobs")[0][0] == "delete"
    assert service.dispatch_one()
    assert not rows(service, "SELECT * FROM auth_apple_grants")
    assert (
        current_user(service, user.id).deletion_requested_at
        == deleted.deletion_requested_at
    )


def test_023_FR_025_active_cleanup_lease_blocks_native_grant_replacement_until_acknowledged(
    apple_runtime: AppleRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leased remote cleanup prevents a new native grant from racing the old generation's revocation."""
    service, _, _, provider, clock = apple_runtime
    user, token = native_owner(apple_runtime)
    pending, code = delivered(cast(Modern, apple_runtime), user.email)
    independent = finish_email(service, pending, code).raw_token
    assert independent
    proof = native_proof(service, user, token, "unlink:apple")
    service.unlink(
        "apple",
        AccountActionRequest(recent_proof=proof, expected_account_id=user.id),
        raw_token=token,
    )
    revoking, release = Event(), Event()

    def revoke(*_args: object, **_kwargs: object) -> None:
        revoking.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(provider, "revoke_apple", revoke)
    clock.now += timedelta(seconds=2)
    provider.identity = replace(provider.identity, issued_at=int(clock().timestamp()))
    _, payload = native_start(
        service,
        purpose="link",
        user=user,
        token=independent,
        action="link:apple",
        proof=email_proof(cast(Modern, apple_runtime), user, independent, "link:apple"),
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        cleanup = executor.submit(service.dispatch_one)
        assert revoking.wait(timeout=5)
        try:
            with pytest.raises(ModernAuthError) as failure:
                service.complete_native_apple(payload, raw_token=independent)
            assert (failure.value.code, failure.value.status_code) == ("conflict", 409)
            assert authority_counts(service) == (1, 1, 1)
            assert (
                rows(service, "SELECT state FROM auth_identity_bindings")[0][0]
                == "unlinked"
            )
        finally:
            release.set()
        assert cleanup.result(timeout=5)
    _, retried = native_start(
        service,
        purpose="link",
        user=user,
        token=independent,
        action="link:apple",
        proof=email_proof(cast(Modern, apple_runtime), user, independent, "link:apple"),
    )
    assert (
        service.complete_native_apple(retried, raw_token=independent).payload.status
        == "linked"
    )


def test_023_FR_025_apple_notification_requires_an_available_lifecycle_service(
    modern: Modern,
) -> None:
    """A signed-notice endpoint with no lifecycle processor fails safely without changing account authority."""
    service = modern[0]
    with pytest.raises(ModernAuthError) as failure:
        service.process_apple_notification("synthetic-signed-notice")
    assert (failure.value.code, failure.value.status_code) == (
        "method_unavailable",
        503,
    )
    assert authority_counts(service) == (0, 0, 0)


def test_023_FR_008_dispatcher_acknowledges_mail_and_erases_expired_proof_material(
    modern: Modern,
) -> None:
    """The lifecycle dispatcher activates acknowledged delivery and removes expired sealed attempts even with no transports."""
    service, _, sent, _, clock = modern
    pending = service.request_email(
        EmailRequest(
            email="new@example.com",
            purpose="login",
            client="web",
            client_challenge=challenge(),
        ),
        network="dispatch-tests",
    )
    assert service.dispatch_one()
    assert finish_email(service, pending, sent[-1][1]).payload.status == "signed_in"
    start_provider(service)
    service.mail = None
    service.apple = None
    clock.now += timedelta(minutes=10)
    assert not service.dispatch_one()
    assert not rows(service, "SELECT * FROM auth_attempts")
    assert not rows(service, "SELECT * FROM auth_challenges")
    assert not rows(service, "SELECT * FROM auth_mail_jobs")


def test_023_FR_004_dispatcher_retires_an_abandoned_exchange_before_late_provider_completion(
    modern: Modern, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup retires an expired in-flight exchange and its late response cannot restore the sealed attempt."""
    service, _, _, provider, clock = modern
    started = start_provider(service)

    def abandoned(_code: str, **_kwargs: object) -> ProviderTokens:
        clock.now += timedelta(seconds=30)
        assert not service.dispatch_one()
        return ProviderTokens(provider.identity, provider.identity.audience)

    monkeypatch.setattr(provider, "exchange_google", abandoned)
    with pytest.raises(ModernAuthError):
        handoff(service, started)
    attempt = rows(service, "SELECT * FROM auth_attempts")[0]
    assert attempt["status"] == "failed" and attempt["sealed_payload"] is None
    assert attempt["lease_id"] is None
    assert authority_counts(service) == (0, 0, 0)


def test_023_FR_019_completion_lookup_and_caller_do_not_expose_missing_or_foreign_owners(
    modern: Modern, container: Container
) -> None:
    """Completion and caller helpers require the live immutable owner, never a purged or foreign account."""
    service, _, _, _, clock = modern
    user, token = password_owner(container, clock)
    assert service.completion_user(user.id).id == user.id
    assert service.caller(token, user.id).id == user.id
    with pytest.raises(ModernAuthError) as foreign:
        service.caller(token, "foreign-owner")
    assert foreign.value.status_code == 404
    container.account_service.purge_account(user.id)
    with pytest.raises(ModernAuthError) as purged:
        service.completion_user(user.id)
    assert purged.value.status_code == 404
    assert authority_counts(service) == (0, 0, 0)
