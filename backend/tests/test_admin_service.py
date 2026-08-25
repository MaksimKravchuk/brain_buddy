"""Tests for AdminService: operator check, exact lookup, idempotent revoke.

009-FR-001, 009-FR-003, 009-FR-007, 009-FR-008.
"""

from __future__ import annotations

import logging

import pytest

from app.exceptions import AdminAuthorizationError, ConflictError, NotFoundError
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


def test_013_FR_005_FR_006_SC_003_admin_create_has_no_invite_or_session(
    container, admin_service
) -> None:
    before = len(list(container.session_repo.sessions_dir.glob("*.json")))
    admin_service.auth_service = container.auth_service
    created = admin_service.create_account(
        operator_id="op_1",
        email="created@example.com",
        password=PASSWORD,
        display_name="Created",
    )
    assert created.email == "created@example.com"
    assert container.user_repo.get_by_email(created.email) is not None
    assert len(list(container.session_repo.sessions_dir.glob("*.json"))) == before


def test_013_FR_007_FR_008_FR_011_SC_004_admin_update_keeps_email_index_coherent(
    container, admin_service
) -> None:
    _create_invite(container, "invite_admin_update")
    user, _token = _signup(container, email=MEMBER_EMAIL, code="invite_admin_update")
    updated = admin_service.update_account(
        operator_id="op_1",
        account_id=user.id,
        email="renamed@example.com",
        display_name="Renamed",
    )
    assert updated.email == "renamed@example.com"
    assert container.user_repo.get_by_email("renamed@example.com").id == user.id
    assert container.user_repo.get_by_email(MEMBER_EMAIL) is None


def test_013_FR_008_SC_004_operator_address_conflicts_even_when_unowned(
    container, admin_service
) -> None:
    _create_invite(container, "invite_reserved")
    user, _token = _signup(container, email=MEMBER_EMAIL, code="invite_reserved")

    with pytest.raises(ConflictError, match="account"):
        admin_service.update_account(
            operator_id="op_1",
            account_id=user.id,
            email=OPERATOR_EMAIL,
            display_name="Member",
        )


def test_013_operator_address_noop_is_allowed(container, admin_service) -> None:
    user = container.auth_service.seed_admin(email=OPERATOR_EMAIL, password=PASSWORD)

    updated = admin_service.update_account(
        operator_id="op_1",
        account_id=user.id,
        email=OPERATOR_EMAIL,
        display_name="Operator",
    )

    assert updated.email == OPERATOR_EMAIL


@pytest.mark.parametrize("operator_id", ["op_1", "different-operator"])
def test_013_configured_operator_cannot_move_away_from_allow_list(
    container, admin_service, operator_id
) -> None:
    configured = container.auth_service.seed_admin(
        email=OPERATOR_EMAIL, password=PASSWORD
    )

    with pytest.raises(AdminAuthorizationError, match="not allowed"):
        admin_service.update_account(
            operator_id=operator_id,
            account_id=configured.id,
            email="moved@example.com",
            display_name="Operator",
        )

    unchanged = container.user_repo.get_by_id(configured.id)
    assert unchanged is not None
    assert unchanged.email == OPERATOR_EMAIL


def test_013_admin_profile_update_rolls_back_index_when_user_write_fails(
    container, admin_service, monkeypatch
) -> None:
    _create_invite(container, "invite_atomic_update")
    user, _token = _signup(container, email=MEMBER_EMAIL, code="invite_atomic_update")
    original_dump = container.user_repo.dump_model

    def fail_updated_user(path, model):
        if path.name == f"{user.id}.json" and model.email == "renamed@example.com":
            raise OSError("injected user-file failure")
        return original_dump(path, model)

    monkeypatch.setattr(container.user_repo, "dump_model", fail_updated_user)

    with pytest.raises(OSError):
        admin_service.update_account(
            operator_id="op_1",
            account_id=user.id,
            email="renamed@example.com",
            display_name="Renamed",
        )

    assert container.user_repo.get_by_email(MEMBER_EMAIL).id == user.id
    assert container.user_repo.get_by_email("renamed@example.com") is None
    assert container.user_repo.get_by_id(user.id).email == MEMBER_EMAIL


def test_013_FR_009_FR_011_SC_005_admin_delete_delegates_to_purge(
    container, admin_service, monkeypatch
) -> None:
    _create_invite(container, "invite_admin_delete")
    user, _token = _signup(container, email=MEMBER_EMAIL, code="invite_admin_delete")
    calls: list[str] = []
    monkeypatch.setattr(
        container.account_service,
        "purge_account",
        lambda user_id: calls.append(user_id),
    )
    admin_service.account_service = container.account_service
    admin_service.delete_account(operator_id="op_1", account_id=user.id)
    assert calls == [user.id]


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


def test_009_FR_008_revoke_unknown_account_emits_one_content_free_audit(
    admin_service, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.INFO, logger="app.services.admin_service"),
        pytest.raises(NotFoundError),
    ):
        admin_service.revoke_sessions(
            operator_id="op_1", account_id="user_never_existed"
        )

    records = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.services.admin_service"
    ]
    assert len(records) == 1
    assert "operation=revoke" in records[0]
    assert "outcome=not_found" in records[0]


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


def test_013_FR_003_FR_004_FR_013_SC_001_list_accounts_is_canonical_and_audited(
    container, admin_service, caplog
) -> None:
    _create_invite(container, "invite_list")
    _signup(container, email="zulu@example.com", code="invite_list")
    _create_invite(container, "invite_list_two")
    _signup(container, email="alpha@example.com", code="invite_list_two")
    with caplog.at_level(logging.INFO, logger="app.services.admin_service"):
        accounts = admin_service.list_accounts(operator_id="op_1")
    assert [account.email for account in accounts] == [
        "alpha@example.com",
        "zulu@example.com",
    ]
    assert "operation=list" in caplog.text


def test_013_FR_006_FR_013_create_without_configured_auth_is_audited(
    container, admin_service, caplog
) -> None:
    with (
        caplog.at_level(logging.INFO, logger="app.services.admin_service"),
        pytest.raises(RuntimeError),
    ):
        admin_service.create_account(
            operator_id="op_1", email=MEMBER_EMAIL, password=PASSWORD, display_name=None
        )
    assert "operation=create" in caplog.text and "outcome=error" in caplog.text


def test_013_FR_005_FR_006_FR_013_create_conflict_is_generic_and_audited(
    container, admin_service, caplog
) -> None:
    class ConflictingAuth:
        def create_admin_user(self, **_kwargs):
            raise ConflictError("User", "email")

    admin_service.auth_service = ConflictingAuth()
    with (
        caplog.at_level(logging.INFO, logger="app.services.admin_service"),
        pytest.raises(ConflictError, match="account"),
    ):
        admin_service.create_account(
            operator_id="op_1", email=MEMBER_EMAIL, password=PASSWORD, display_name=None
        )
    assert "outcome=conflict" in caplog.text


def test_013_FR_013_FR_014_update_missing_account_is_audited(
    admin_service, caplog
) -> None:
    with (
        caplog.at_level(logging.INFO, logger="app.services.admin_service"),
        pytest.raises(NotFoundError),
    ):
        admin_service.update_account(
            operator_id="op_1",
            account_id="missing",
            email=MEMBER_EMAIL,
            display_name=None,
        )
    assert "operation=update" in caplog.text and "outcome=not_found" in caplog.text


def test_013_FR_007_FR_013_update_conflict_is_generic_and_audited(
    container, admin_service, seeded_member, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(
        container.user_repo,
        "update_profile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConflictError("User", "email")),
    )
    with (
        caplog.at_level(logging.INFO, logger="app.services.admin_service"),
        pytest.raises(ConflictError, match="account"),
    ):
        admin_service.update_account(
            operator_id="op_1",
            account_id=seeded_member.id,
            email="new@example.com",
            display_name=None,
        )
    assert "outcome=conflict" in caplog.text


def test_013_FR_009_FR_013_SC_005_delete_rejects_self_and_missing_configuration(
    container, admin_service, seeded_member, caplog
) -> None:
    with (
        caplog.at_level(logging.INFO, logger="app.services.admin_service"),
        pytest.raises(AdminAuthorizationError),
    ):
        admin_service.delete_account(
            operator_id=seeded_member.id, account_id=seeded_member.id
        )
    with pytest.raises(RuntimeError):
        admin_service.delete_account(operator_id="op_1", account_id=seeded_member.id)


def test_013_FR_013_FR_013_SC_006_revoke_repository_failure_is_audited(
    container, admin_service, seeded_member, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(
        container.session_repo,
        "delete_all_for_user",
        lambda _user_id: (_ for _ in ()).throw(OSError("session store down")),
    )
    with (
        caplog.at_level(logging.INFO, logger="app.services.admin_service"),
        pytest.raises(OSError),
    ):
        admin_service.revoke_sessions(operator_id="op_1", account_id=seeded_member.id)
    assert "operation=revoke" in caplog.text and "outcome=error" in caplog.text


@pytest.mark.parametrize("operation", ["list", "update", "delete", "revoke"])
def test_013_FR_013_FR_014_repository_lookup_failures_are_audited(
    container, admin_service, seeded_member, monkeypatch, caplog, operation
) -> None:
    if operation == "list":
        monkeypatch.setattr(
            container.user_repo,
            "list_users",
            lambda: (_ for _ in ()).throw(OSError("read failed")),
        )

        def call():
            return admin_service.list_accounts(operator_id="op_1")

    else:
        monkeypatch.setattr(
            container.user_repo,
            "get_by_id",
            lambda _account_id: (_ for _ in ()).throw(OSError("read failed")),
        )

        def call():
            return getattr(
                admin_service,
                {
                    "update": "update_account",
                    "delete": "delete_account",
                    "revoke": "revoke_sessions",
                }[operation],
            )(
                operator_id="op_1",
                account_id=seeded_member.id,
                **(
                    {"email": MEMBER_EMAIL, "display_name": None}
                    if operation == "update"
                    else {}
                ),
            )

    with (
        caplog.at_level(logging.INFO, logger="app.services.admin_service"),
        pytest.raises(OSError),
    ):
        call()
    assert f"operation={operation}" in caplog.text and "outcome=error" in caplog.text


def test_013_FR_006_FR_013_create_unexpected_failure_is_audited(
    admin_service, caplog
) -> None:
    class BrokenAuth:
        def create_admin_user(self, **_kwargs):
            raise OSError("create failed")

    admin_service.auth_service = BrokenAuth()
    with (
        caplog.at_level(logging.INFO, logger="app.services.admin_service"),
        pytest.raises(OSError),
    ):
        admin_service.create_account(
            operator_id="op_1", email=MEMBER_EMAIL, password=PASSWORD, display_name=None
        )
    assert "operation=create" in caplog.text and "outcome=error" in caplog.text


def test_013_FR_009_FR_013_FR_014_SC_005_delete_not_found_and_purge_failure_are_audited(
    container, admin_service, seeded_member, monkeypatch, caplog
) -> None:
    with (
        caplog.at_level(logging.INFO, logger="app.services.admin_service"),
        pytest.raises(NotFoundError),
    ):
        admin_service.delete_account(operator_id="op_1", account_id="missing")

    class BrokenAccount:
        def purge_account(self, _account_id):
            raise OSError("purge failed")

    admin_service.account_service = BrokenAccount()
    with pytest.raises(OSError):
        admin_service.delete_account(operator_id="op_1", account_id=seeded_member.id)
    assert "outcome=error" in caplog.text


def test_013_user_profile_repository_rejects_missing_and_duplicate_accounts(
    container, seeded_member
) -> None:
    _create_invite(container, "invite_duplicate")
    _signup(container, email="operator@example.com", code="invite_duplicate")
    with pytest.raises(NotFoundError):
        container.user_repo.update_profile(
            "missing", email=MEMBER_EMAIL, display_name=None
        )
    with pytest.raises(ConflictError):
        container.user_repo.update_profile(
            seeded_member.id, email="operator@example.com", display_name=None
        )


def test_013_user_email_transaction_rejects_a_missing_account(container) -> None:
    with pytest.raises(NotFoundError):
        container.user_repo.update_email("missing", "renamed@example.com")


def test_013_user_email_transaction_returns_an_unchanged_account(
    container, seeded_member
) -> None:
    unchanged = container.user_repo.update_email(seeded_member.id, MEMBER_EMAIL)

    assert unchanged == seeded_member


def test_013_user_email_transaction_rolls_back_when_the_user_write_fails(
    container, seeded_member, monkeypatch
) -> None:
    original_dump = container.user_repo.dump_model

    def fail_updated_user(path, model):
        if path.name == f"{seeded_member.id}.json":
            raise OSError("injected user-file failure")
        return original_dump(path, model)

    monkeypatch.setattr(container.user_repo, "dump_model", fail_updated_user)

    with pytest.raises(OSError, match="injected user-file failure"):
        container.user_repo.update_email(seeded_member.id, "renamed@example.com")

    assert container.user_repo.get_by_email(MEMBER_EMAIL) == seeded_member
    assert container.user_repo.get_by_email("renamed@example.com") is None
