"""Tests for AdminService: operator check, exact lookup, idempotent revoke.

009-FR-001, 009-FR-003, 009-FR-007, 009-FR-008.
"""

from __future__ import annotations

import logging

import pytest

from app.exceptions import NotFoundError
from app.schemas.auth import Invite
from app.services.admin_service import AdminService
from app.utils.time import utcnow

OPERATOR_EMAIL = "operator@example.com"
MEMBER_EMAIL = "member@example.com"
PASSWORD = "very-long-password"


def _create_invite(container, code: str) -> str:
    container.invite_repo.create(Invite(code=code, created_at=utcnow()))
    return code


def _signup(container, *, email: str, code: str):
    return container.auth_service.signup(
        email=email, password=PASSWORD, invite_code=code
    )


@pytest.fixture
def admin_service(container) -> AdminService:
    return AdminService(
        user_repo=container.user_repo,
        session_repo=container.session_repo,
        operator_emails=frozenset({OPERATOR_EMAIL}),
    )


def test_009_FR_001_is_operator_true_for_allow_listed_email(
    admin_service: AdminService,
) -> None:
    assert admin_service.is_operator(" Operator@Example.com ") is True


def test_009_FR_001_is_operator_false_for_unlisted_email(
    admin_service: AdminService,
) -> None:
    assert admin_service.is_operator(MEMBER_EMAIL) is False


def test_009_FR_001_is_operator_false_when_allow_list_is_empty(container) -> None:
    """An empty allow-list fails closed for every caller."""

    service = AdminService(
        user_repo=container.user_repo,
        session_repo=container.session_repo,
        operator_emails=frozenset(),
    )
    assert service.is_operator(OPERATOR_EMAIL) is False


def test_009_FR_003_find_account_by_exact_id(container, admin_service) -> None:
    _create_invite(container, "invite_a")
    user, _token = _signup(container, email=MEMBER_EMAIL, code="invite_a")

    found = admin_service.find_account(
        operator_id="op_1", account_id=user.id, email=None
    )

    assert found is not None
    assert found.id == user.id
    assert found.email == MEMBER_EMAIL


def test_009_FR_003_find_account_by_exact_email(container, admin_service) -> None:
    _create_invite(container, "invite_b")
    user, _token = _signup(container, email=MEMBER_EMAIL, code="invite_b")

    found = admin_service.find_account(
        operator_id="op_1", account_id=None, email=MEMBER_EMAIL
    )

    assert found is not None
    assert found.id == user.id


def test_009_FR_003_find_account_no_match_returns_none(admin_service) -> None:
    assert (
        admin_service.find_account(
            operator_id="op_1", account_id="user_does_not_exist", email=None
        )
        is None
    )
    assert (
        admin_service.find_account(
            operator_id="op_1", account_id=None, email="nobody@example.com"
        )
        is None
    )


def test_009_FR_007_revoke_sessions_unknown_account_raises_not_found(
    admin_service,
) -> None:
    """An id that never belonged to any account is a 404, not a fake success."""

    with pytest.raises(NotFoundError):
        admin_service.revoke_sessions(
            operator_id="op_1", account_id="user_never_existed"
        )


def test_009_FR_007_revoke_sessions_deletes_every_active_session(
    container, admin_service
) -> None:
    _create_invite(container, "invite_c")
    user, token = _signup(container, email=MEMBER_EMAIL, code="invite_c")
    token_hash = container.auth_service.hash_session_token(token)
    assert container.session_repo.get(token_hash) is not None

    revoked = admin_service.revoke_sessions(operator_id="op_1", account_id=user.id)

    assert revoked == 1
    assert container.session_repo.get(token_hash) is None
    # Idempotent: revoking again is still success, with nothing left to revoke.
    assert admin_service.revoke_sessions(operator_id="op_1", account_id=user.id) == 0


def test_009_FR_008_lookup_and_revoke_logs_carry_no_pii(
    container, admin_service, caplog: pytest.LogCaptureFixture
) -> None:
    _create_invite(container, "invite_d")
    user, _token = _signup(container, email=MEMBER_EMAIL, code="invite_d")

    with caplog.at_level(logging.INFO, logger="app.services.admin_service"):
        admin_service.find_account(
            operator_id="op_1", account_id=None, email=MEMBER_EMAIL
        )
        admin_service.revoke_sessions(operator_id="op_1", account_id=user.id)

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert MEMBER_EMAIL not in joined
    assert user.id in joined
    assert "op_1" in joined
