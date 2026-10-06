"""Email and provider proofs issue authority only to their initiating client."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr

from app.core.config import ModernAuthSettings
from app.schemas.modern_auth import (
    EmailRequest,
    EmailVerifyRequest,
    ProviderCompleteRequest,
    ProviderStartRequest,
)
from app.services.auth_mail_service import AuthMailService
from app.services.auth_provider_service import ProviderIdentity, ProviderTokens
from app.services.auth_secret_box import AuthSecretBox
from app.services.modern_auth_service import ModernAuthError, ModernAuthService

VERIFIER = "v" * 43


def challenge(verifier: str = VERIFIER) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )


@dataclass
class Clock:
    now: datetime = datetime(2026, 10, 6, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class Provider:
    def __init__(self, clock: Clock) -> None:
        self.identity = ProviderIdentity(
            "google",
            "https://accounts.google.com",
            "subject-a",
            "new@gmail.com",
            True,
            False,
            "web.apps.googleusercontent.com",
            int(clock().timestamp()),
        )

    def callback_uri(self, _provider: str) -> str:
        return "https://api.example.com/api/auth/providers/google/callback"

    def authorization_url(self, _provider: str, **_kwargs) -> str:
        return "https://accounts.google.com/o/oauth2/v2/auth?synthetic"

    def exchange_google(self, _code: str, **_kwargs) -> ProviderTokens:
        return ProviderTokens(self.identity, self.identity.audience)


@pytest.fixture
def modern(container):
    return make_modern(container)


def make_modern(container):
    clock = Clock()
    settings = ModernAuthSettings(
        public_origin="https://app.example.com",
        api_origin="https://api.example.com",
        current_key_id="k1",
        keyring={"k1": SecretStr(base64.b64encode(b"1" * 32).decode())},
        google_client_id="web.apps.googleusercontent.com",
        google_client_secret=SecretStr("synthetic"),
        smtp_host="smtp.example.com",
        smtp_sender="signin@example.com",
        smtp_username="synthetic",
        smtp_password=SecretStr("synthetic"),
    )
    box = AuthSecretBox.from_settings(settings)
    sent: list[tuple[str, str, str]] = []
    mail = AuthMailService(
        container.user_repo.store,
        box,
        settings,
        send=lambda *values: sent.append(values),
        clock=clock,
    )
    provider = Provider(clock)
    service = ModernAuthService(
        auth_service=container.auth_service,
        account_service=container.account_service,
        settings=settings,
        secret_box=box,
        provider_service=provider,
        mail_service=mail,
        clock=clock,
    )
    return service, mail, sent, provider, clock


def request(service, email: str):
    return service.request_email(
        EmailRequest(
            email=email, purpose="login", client="web", client_challenge=challenge()
        ),
        network="network",
    )


def verify(service, identifier: str, code: str, verifier: str = VERIFIER):
    return service.verify_email(
        EmailVerifyRequest(
            challenge_id=identifier, code=code, client_verifier=verifier
        ),
        network="network",
    )


def test_023_FR_001_code_signup_is_neutral_until_ack_and_consumes_once(
    modern, container
) -> None:
    service, mail, sent, _, _ = modern
    pending = request(service, "new@example.com")
    assert container.user_repo.get_by_email("new@example.com") is None
    assert "code" not in pending.model_dump()
    assert mail.dispatch_one()
    result = verify(service, pending.challenge_id, sent[0][1])
    assert result.payload.status == "signed_in"
    assert (
        container.auth_service.get_user_for_token(result.raw_token).id
        == result.payload.user.id
    )
    with pytest.raises(ModernAuthError):
        verify(service, pending.challenge_id, sent[0][1])
    assert len(container.user_repo.list_users()) == 1


def test_023_FR_010_unverified_legacy_email_never_grants_code_login(
    modern, container
) -> None:
    service, mail, _, _, _ = modern
    original = container.auth_service.seed_admin(
        email="legacy@example.com", password="legacy-long-password"
    )
    inert = request(service, original.email)
    assert not mail.dispatch_one()
    with pytest.raises(ModernAuthError):
        verify(service, inert.challenge_id, "123456")
    fresh = container.user_repo.get_by_id(original.id)
    assert fresh.password_hash == original.password_hash
    assert fresh.email_verified_at is None


def test_023_FR_008_foreign_verifier_and_missing_challenge_are_same_404(modern) -> None:
    service, _, _, _, _ = modern
    pending = request(service, "new@example.com")
    errors = []
    for identifier in [pending.challenge_id, "n" * 43]:
        with pytest.raises(ModernAuthError) as failure:
            verify(service, identifier, "123456", verifier="f" * 43)
        errors.append(
            (failure.value.status_code, failure.value.code, str(failure.value))
        )
    assert errors[0] == errors[1]
    assert errors[0][0] == 404


def test_023_FR_009_five_failed_guesses_remain_committed(modern) -> None:
    service, mail, sent, _, _ = modern
    pending = request(service, "new@example.com")
    mail.dispatch_one()
    wrong = "000000" if sent[0][1] != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(ModernAuthError):
            verify(service, pending.challenge_id, wrong)
    with service.store.connection() as connection:
        assert (
            connection.execute(
                "SELECT failures FROM auth_challenges WHERE id=?",
                (pending.challenge_id,),
            ).fetchone()[0]
            == 5
        )
    with pytest.raises(ModernAuthError):
        verify(service, pending.challenge_id, sent[0][1])


def provider_handoff(service):
    started = service.start_provider(
        "google",
        ProviderStartRequest(
            purpose="login", client="web", client_challenge=challenge()
        ),
    )
    returned = service.provider_callback(
        "google",
        code="synthetic-code",
        state=started.payload.state,
        binder=started.binder,
    )
    parameters = parse_qs(urlsplit(returned.url).fragment)
    return ProviderCompleteRequest(
        attempt_id=parameters["attempt"][0],
        state=parameters["state"][0],
        handoff_code=parameters["grant"][0],
        client_verifier=VERIFIER,
    )


def test_023_FR_004_provider_binding_keeps_identity_despite_email_change(
    modern, container
) -> None:
    service, _, _, provider, clock = modern
    first = service.complete_provider(provider_handoff(service))
    original = first.payload.user
    provider.identity = ProviderIdentity(
        "google",
        "https://accounts.google.com",
        "subject-a",
        "changed@gmail.com",
        True,
        False,
        provider.identity.audience,
        int(clock().timestamp()),
    )
    second = service.complete_provider(provider_handoff(service))
    assert second.payload.user.id == original.id
    assert second.payload.user.email == original.email
    assert len(container.user_repo.list_users()) == 1


def test_023_FR_004_provider_email_collision_never_merges_legacy_account(
    modern, container
) -> None:
    service, _, _, provider, _ = modern
    original = container.auth_service.seed_admin(
        email=provider.identity.email, password="legacy-long-password"
    )
    result = service.complete_provider(provider_handoff(service))
    assert result.payload.status == "existing_account_required"
    assert result.raw_token is None
    assert (
        container.user_repo.get_by_id(original.id).password_hash
        == original.password_hash
    )
    with service.store.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM auth_identity_bindings"
            ).fetchone()[0]
            == 0
        )


def test_023_FR_014_external_provider_mailbox_finalizes_after_handoff_expires(
    modern, container
) -> None:
    service, mail, sent, provider, clock = modern
    provider.identity = ProviderIdentity(
        "google",
        "https://accounts.google.com",
        "subject-external",
        "external@example.com",
        False,
        False,
        provider.identity.audience,
        int(clock().timestamp()),
    )
    handoff = provider_handoff(service)
    staged = service.complete_provider(handoff)
    assert staged.payload.status == "verify_mailbox"
    assert container.user_repo.get_by_email("external@example.com") is None
    with pytest.raises(ModernAuthError):
        service.complete_provider(handoff)
    mail.dispatch_one()
    clock.now += timedelta(seconds=90)
    finished = verify(service, staged.payload.challenge_id, sent[0][1])
    assert finished.payload.status == "signed_in"
    assert finished.payload.user.email == "external@example.com"


def password_owner(container, *, verified=True):
    owner = container.auth_service.seed_admin(
        email="owner@example.com", password="original-long-password"
    )
    if verified:
        owner = container.user_repo.mutate(
            owner.id,
            lambda fresh: fresh.model_copy(
                update={"email_verified_at": datetime(2026, 10, 6, tzinfo=UTC)}
            ),
        )
    token, _ = container.auth_service._create_session(owner.id)
    return owner, token


def recent(service, owner, token, action):
    from app.schemas.modern_auth import PasswordConfirmRequest

    return service.confirm_password(
        PasswordConfirmRequest(
            current_password="original-long-password",
            action=action,
            expected_account_id=owner.id,
        ),
        raw_token=token,
    ).recent_proof


def test_023_FR_012_recent_proof_is_session_owner_action_bound_and_one_use(
    modern, container
):
    from app.schemas.modern_auth import AccountActionRequest, PasswordConfirmRequest

    service, _, _, _, _ = modern
    owner, token = password_owner(container)
    with pytest.raises(ModernAuthError) as failure:
        service.confirm_password(
            PasswordConfirmRequest(
                current_password="original-long-password",
                action="export",
                expected_account_id="foreign",
            ),
            raw_token=token,
        )
    assert failure.value.status_code == 404
    proof = recent(service, owner, token, "export")
    action = AccountActionRequest(recent_proof=proof, expected_account_id=owner.id)
    other_token, _ = container.auth_service._create_session(owner.id)
    with pytest.raises(ModernAuthError):
        service.export_account(action, raw_token=other_token)
    filename, archive = service.export_account(action, raw_token=token)
    assert filename.endswith(".zip")
    archive.close()
    with pytest.raises(ModernAuthError):
        service.export_account(action, raw_token=token)


def test_023_FR_011_verified_recovery_revokes_sessions_without_auto_login(
    modern, container
):
    from app.schemas.modern_auth import ResetRequest

    service, mail, sent, _, _ = modern
    owner, token = password_owner(container)
    pending = service.request_email(
        EmailRequest(
            email=owner.email,
            purpose="recover",
            client="web",
            client_challenge=challenge(),
        ),
        network="recovery",
    )
    mail.dispatch_one()
    completion = verify(service, pending.challenge_id, sent[-1][1])
    assert completion.payload.status == "reset_ready"
    assert completion.raw_token is None
    payload = ResetRequest(
        reset_grant=completion.payload.reset_grant,
        client_verifier=VERIFIER,
        new_password="replacement-long-password",
    )
    service.reset_password(payload)
    assert container.auth_service.get_user_for_token(token) is None
    assert container.auth_service.verify_password(
        container.user_repo.get_by_id(owner.id), payload.new_password
    )
    with pytest.raises(ModernAuthError):
        service.reset_password(payload)


def test_023_FR_010_destination_is_unclaimed_until_both_confirmation_and_code(
    modern, container
):
    service, mail, sent, _, _ = modern
    owner, token = password_owner(container)
    proof = recent(service, owner, token, "change_email")
    pending = service.request_email(
        EmailRequest(
            email="destination@example.com",
            purpose="change_email",
            client="web",
            client_challenge=challenge(),
            expected_account_id=owner.id,
            action="change_email",
            recent_proof=proof,
        ),
        network="change",
        raw_token=token,
    )
    assert container.user_repo.get_by_email("destination@example.com") is None
    mail.dispatch_one()
    result = service.verify_email(
        EmailVerifyRequest(
            challenge_id=pending.challenge_id,
            code=sent[-1][1],
            client_verifier=VERIFIER,
        ),
        network="change",
        raw_token=token,
    )
    assert result.payload.status == "changed_email"
    assert result.raw_token is None
    assert result.payload.user.id == owner.id
    assert (
        container.auth_service.get_user_for_token(token).email
        == "destination@example.com"
    )
    assert container.user_repo.get_by_id(owner.id).email_verified_at is not None


def test_023_FR_005_existing_account_can_link_only_after_same_account_confirmation(
    modern, container
):
    service, _, _, provider, _ = modern
    owner, token = password_owner(container)
    proof = recent(service, owner, token, "link:google")
    started = service.start_provider(
        "google",
        ProviderStartRequest(
            purpose="link",
            client="web",
            client_challenge=challenge(),
            expected_account_id=owner.id,
            action="link:google",
            recent_proof=proof,
        ),
        raw_token=token,
    )
    callback = service.provider_callback(
        "google", code="synthetic", state=started.payload.state, binder=started.binder
    )
    fields = parse_qs(urlsplit(callback.url).fragment)
    completed = service.complete_provider(
        ProviderCompleteRequest(
            attempt_id=fields["attempt"][0],
            state=fields["state"][0],
            handoff_code=fields["grant"][0],
            client_verifier=VERIFIER,
        ),
        raw_token=token,
    )
    assert completed.payload.status == "linked"
    assert completed.payload.user.id == owner.id
    assert completed.raw_token is None
    returned = service.complete_provider(provider_handoff(service))
    assert returned.payload.user.id == owner.id


def test_023_FR_014_legacy_deletion_invalidates_all_modern_owner_proofs(
    modern, container
):
    service, _, _, _, _ = modern
    owner, token = password_owner(container)
    recent(service, owner, token, "delete")
    request(service, owner.email)
    service.start_provider(
        "google",
        ProviderStartRequest(
            purpose="reauth",
            action="export",
            expected_account_id=owner.id,
            client="web",
            client_challenge=challenge(),
        ),
        raw_token=token,
    )
    container.account_service.request_deletion(
        owner, current_password="original-long-password"
    )
    with service.store.connection() as connection:
        for table in ["auth_proofs", "auth_challenges", "auth_attempts"]:
            assert (
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (owner.id,)
                ).fetchone()[0]
                == 0
            )
    assert container.user_repo.get_by_id(owner.id).auth_version > owner.auth_version


def test_023_FR_014_admin_cannot_strand_verified_email_only_account(modern, container):
    service, mail, sent, _, _ = modern
    pending = request(service, "emailonly@example.com")
    mail.dispatch_one()
    result = verify(service, pending.challenge_id, sent[-1][1])
    owner = container.user_repo.get_by_id(result.payload.user.id)
    from app.exceptions import ConflictError

    with pytest.raises(ConflictError):
        container.admin_service.update_account(
            operator_id="operator",
            account_id=owner.id,
            email="unverified@example.com",
            display_name="New name",
        )
    assert container.user_repo.get_by_id(owner.id).email == owner.email
    same = container.admin_service.update_account(
        operator_id="operator",
        account_id=owner.id,
        email=owner.email,
        display_name="New name",
    )
    assert same.email_verified_at == owner.email_verified_at
