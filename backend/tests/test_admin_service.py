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


# ---------------------------------------------------------------------------
# 009-FR-003 / 009-SC-001 — exact match, derived from a real account
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_member(container):
    _create_invite(container, "invite_exact")
    user, _token = _signup(container, email=MEMBER_EMAIL, code="invite_exact")
    return user


def test_009_SC_001_case_variant_of_a_real_account_id_returns_no_match(
    admin_service, seeded_member
) -> None:
    """Guards against a case-insensitive filesystem resolving the id for us."""

    assert (
        admin_service.find_account(
            operator_id="op_1", account_id=seeded_member.id.upper(), email=None
        )
        is None
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: f" {value} ",
        lambda value: value[:-2],
        lambda value: f"{value}x",
        lambda value: f"../users/{value}",
        lambda value: f"users/{value}",
        lambda value: f"{value}.json",
    ],
    ids=["whitespace", "prefix", "suffix", "traversal", "separator", "extension"],
)
def test_009_SC_001_near_match_account_ids_return_no_match(
    admin_service, seeded_member, mutate
) -> None:
    """Every variant of a real id, including the ones a file path would absorb."""

    assert (
        admin_service.find_account(
            operator_id="op_1", account_id=mutate(seeded_member.id), email=None
        )
        is None
    )


def test_009_FR_003_a_traversal_account_id_never_reaches_path_construction(
    admin_service, seeded_member, monkeypatch
) -> None:
    """The charset guard runs before the repository, not after it.

    `UserRepository._user_path` interpolates the id into a filename, so a
    rejection that happened only after the fetch would still have built (and
    resolved) an attacker-chosen path.
    """

    from app.repositories.user import UserRepository

    def _explode(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("an unvalidated account id reached UserRepository")

    monkeypatch.setattr(UserRepository, "get_by_id", _explode)

    assert (
        admin_service.find_account(
            operator_id="op_1",
            account_id=f"../users/{seeded_member.id}",
            email=None,
        )
        is None
    )
    with pytest.raises(NotFoundError):
        admin_service.revoke_sessions(
            operator_id="op_1", account_id=f"../users/{seeded_member.id}"
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.upper(),
        lambda value: f" {value} ",
        lambda value: value[:-2],
        lambda value: f"x{value}",
    ],
    ids=["case", "whitespace", "prefix", "suffix"],
)
def test_009_SC_001_near_match_emails_return_no_match(
    admin_service, seeded_member, mutate
) -> None:
    """`get_by_email` normalizes before the index read; FR-003 does not."""

    assert (
        admin_service.find_account(
            operator_id="op_1", account_id=None, email=mutate(MEMBER_EMAIL)
        )
        is None
    )


def test_009_FR_003_a_server_accepted_email_without_a_dotted_domain_matches(
    container, admin_service
) -> None:
    """`admin@localhost` is canonical here, so exact match must find it.

    The seed path and `AdminSettings` both accept it, so a lookup that could
    not resolve it would make a real (and possibly operator) account
    unfindable — the failure design.md names explicitly.
    """

    local = "admin@localhost"
    user = container.auth_service.seed_admin(email=local, password=PASSWORD)

    found = admin_service.find_account(operator_id="op_1", account_id=None, email=local)

    assert found is not None
    assert found.id == user.id


def test_009_FR_008_lookup_record_names_the_resolved_account_not_the_query(
    admin_service, seeded_member, caplog: pytest.LogCaptureFixture
) -> None:
    """A lookup that logged only `found=<bool>` would be unattributable."""

    with caplog.at_level(logging.INFO, logger="app.services.admin_service"):
        admin_service.find_account(
            operator_id="op_1", account_id=None, email=MEMBER_EMAIL
        )

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert f"account={seeded_member.id}" in joined
    assert "outcome=found" in joined
    assert MEMBER_EMAIL not in joined


def test_009_FR_008_a_no_match_lookup_records_the_outcome_without_a_target(
    admin_service, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.services.admin_service"):
        assert (
            admin_service.find_account(
                operator_id="op_1", account_id=None, email="nobody@example.com"
            )
            is None
        )

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "outcome=no_match" in joined
    assert "nobody@example.com" not in joined
