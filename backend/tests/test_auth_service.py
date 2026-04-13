"""Tests for the AuthService."""

from __future__ import annotations

import pytest

from app.exceptions import ConflictError, ValidationFailure
from app.schemas.auth import Invite
from app.services import InvalidCredentialsError, InvalidInviteError
from app.utils.time import utcnow


def _create_invite(container) -> str:
    code = "invite_test_code"
    container.invite_repo.create(Invite(code=code, created_at=utcnow()))
    return code


def test_signup_happy_path(container) -> None:
    code = _create_invite(container)
    user, token = container.auth_service.signup(
        email="Alice@Example.com",
        password="very-long-password",
        invite_code=code,
    )

    assert user.email == "alice@example.com"
    assert token  # opaque, non-empty
    assert container.user_repo.get_by_email("alice@example.com") is not None
    assert container.invite_repo.get(code).is_used


def test_signup_rejects_short_password(container) -> None:
    code = _create_invite(container)
    with pytest.raises(ValidationFailure):
        container.auth_service.signup(
            email="alice@example.com",
            password="short",
            invite_code=code,
        )
    # Password rejected before the invite is touched.
    assert not container.invite_repo.get(code).is_used


def test_signup_rejects_invalid_invite(container) -> None:
    with pytest.raises(InvalidInviteError):
        container.auth_service.signup(
            email="alice@example.com",
            password="very-long-password",
            invite_code="not-a-real-code",
        )


def test_signup_rejects_reused_invite(container) -> None:
    code = _create_invite(container)
    container.auth_service.signup(
        email="first@example.com",
        password="very-long-password",
        invite_code=code,
    )
    with pytest.raises(InvalidInviteError):
        container.auth_service.signup(
            email="second@example.com",
            password="very-long-password",
            invite_code=code,
        )


def test_signup_rejects_duplicate_email(container) -> None:
    first = _create_invite(container)
    container.auth_service.signup(
        email="dup@example.com", password="very-long-password", invite_code=first
    )
    second = "invite_test_code_2"
    container.invite_repo.create(Invite(code=second, created_at=utcnow()))
    with pytest.raises(ConflictError):
        container.auth_service.signup(
            email="dup@example.com",
            password="very-long-password",
            invite_code=second,
        )


def test_login_happy_path(container) -> None:
    code = _create_invite(container)
    container.auth_service.signup(
        email="bob@example.com", password="very-long-password", invite_code=code
    )
    user, token = container.auth_service.login(
        email="bob@example.com", password="very-long-password"
    )
    assert user.email == "bob@example.com"
    assert token
    # Token resolves back to the same user.
    assert container.auth_service.get_user_for_token(token).id == user.id


def test_login_wrong_password_raises(container) -> None:
    code = _create_invite(container)
    container.auth_service.signup(
        email="bob@example.com", password="very-long-password", invite_code=code
    )
    with pytest.raises(InvalidCredentialsError):
        container.auth_service.login(email="bob@example.com", password="wrong-password")


def test_login_unknown_email_raises_same_error(container) -> None:
    with pytest.raises(InvalidCredentialsError):
        container.auth_service.login(email="ghost@example.com", password="any-password")


def test_logout_invalidates_token(container) -> None:
    code = _create_invite(container)
    _, token = container.auth_service.signup(
        email="c@example.com", password="very-long-password", invite_code=code
    )
    assert container.auth_service.get_user_for_token(token) is not None
    container.auth_service.logout(token)
    assert container.auth_service.get_user_for_token(token) is None


def test_seed_admin_creates_account_when_missing(container) -> None:
    user = container.auth_service.seed_admin(
        email="Admin@Example.com", password="very-long-admin-password"
    )
    assert user.email == "admin@example.com"
    # Can log in with the seeded credentials — no invite required.
    _, token = container.auth_service.login(
        email="admin@example.com", password="very-long-admin-password"
    )
    assert token


def test_seed_admin_rotates_password_when_env_changes(container) -> None:
    first = container.auth_service.seed_admin(
        email="admin@example.com", password="very-long-admin-password"
    )
    second = container.auth_service.seed_admin(
        email="admin@example.com", password="different-admin-password"
    )
    assert first.id == second.id
    assert first.password_hash != second.password_hash
    # Old password is rejected, new one works.
    with pytest.raises(InvalidCredentialsError):
        container.auth_service.login(
            email="admin@example.com", password="very-long-admin-password"
        )
    _, token = container.auth_service.login(
        email="admin@example.com", password="different-admin-password"
    )
    assert token


def test_seed_admin_is_idempotent_for_unchanged_password(container) -> None:
    first = container.auth_service.seed_admin(
        email="admin@example.com", password="very-long-admin-password"
    )
    second = container.auth_service.seed_admin(
        email="admin@example.com", password="very-long-admin-password"
    )
    # Same user, same hash — no rotation when the env var is unchanged.
    assert first.id == second.id
    assert first.password_hash == second.password_hash


def test_seed_admin_rejects_short_password(container) -> None:
    with pytest.raises(ValidationFailure):
        container.auth_service.seed_admin(email="admin@example.com", password="short")
