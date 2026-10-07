"""Legacy password contracts under the shared Identity authority."""

from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest

from app.exceptions import ReauthFailedError
from app.schemas.auth import User
from app.services.auth_service import InvalidCredentialsError
from app.utils.time import utcnow


@pytest.mark.parametrize("stored_hash", ["", "malformed-hash"])
def test_023_FR_010_unset_or_invalid_hash_pays_dummy_cost_and_cannot_login(
    container, stored_hash: str
) -> None:
    service = container.auth_service
    container.user_repo.create(
        User(
            id="user_passwordless",
            email="passwordless@example.com",
            password_hash=stored_hash,
            created_at=utcnow(),
        )
    )
    service._hasher = Mock(wraps=service._hasher)
    with pytest.raises(InvalidCredentialsError):
        service.login(
            email="passwordless@example.com",
            password="dummy-password-for-timing-equalization",
        )
    assert any(
        call.args[0] == service._dummy_hash
        for call in service._hasher.verify.call_args_list
    )


def test_023_FR_002_passwordless_sensitive_action_never_accepts_dummy_password(
    container,
) -> None:
    service = container.auth_service
    user = User(
        id="user_passwordless",
        email="passwordless@example.com",
        password_hash="",
        created_at=utcnow(),
    )
    service._hasher = Mock(wraps=service._hasher)
    assert not service.verify_password(user, "dummy-password-for-timing-equalization")
    assert any(
        call.args[0] == service._dummy_hash
        for call in service._hasher.verify.call_args_list
    )


def test_023_FR_014_password_changed_during_verify_cannot_issue_session(
    container, monkeypatch
) -> None:
    service = container.auth_service
    user = service.seed_admin(
        email="ordinary@example.com", password="old-long-password"
    )
    new_hash = service.hash_password("new-long-password")
    original = service._verify_password

    def verify_then_rotate(raw: str, hashed: str) -> bool:
        verified = original(raw, hashed)
        container.user_repo.mutate(
            user.id, lambda fresh: fresh.model_copy(update={"password_hash": new_hash})
        )
        return verified

    monkeypatch.setattr(service, "_verify_password", verify_then_rotate)
    with pytest.raises(InvalidCredentialsError):
        service.login(email=user.email, password="old-long-password")


def test_023_FR_021_operator_seed_logs_never_include_address_or_password(
    container, caplog
) -> None:
    service = container.auth_service
    email = "operator-private@example.com"
    passwords = ("old-long-password", "new-long-password")
    with caplog.at_level(logging.DEBUG, logger="app.services.auth_service"):
        service.seed_admin(email=email, password=passwords[0])
        service.seed_admin(email=email, password=passwords[0])
        service.seed_admin(email=email, password=passwords[1])
    assert email not in caplog.text
    assert all(password not in caplog.text for password in passwords)


@pytest.mark.parametrize("action", ["email", "password", "delete"])
def test_023_FR_014_stale_password_confirmation_cannot_mutate_account(
    container, monkeypatch, action: str
) -> None:
    service = container.auth_service
    account = container.account_service
    user = service.seed_admin(
        email="ordinary@example.com", password="old-long-password"
    )
    new_hash = service.hash_password("concurrent-long-password")
    original = service.verify_password

    def verify_then_rotate(snapshot: User, raw: str) -> bool:
        verified = original(snapshot, raw)
        container.user_repo.mutate(
            user.id, lambda fresh: fresh.model_copy(update={"password_hash": new_hash})
        )
        return verified

    monkeypatch.setattr(service, "verify_password", verify_then_rotate)
    with pytest.raises(ReauthFailedError):
        if action == "email":
            account.change_email(
                user,
                new_email="changed@example.com",
                current_password="old-long-password",
            )
        elif action == "password":
            account.change_password(
                user,
                current_password="old-long-password",
                new_password="requested-long-password",
                keep_token_hash=None,
            )
        else:
            account.request_deletion(user, current_password="old-long-password")
