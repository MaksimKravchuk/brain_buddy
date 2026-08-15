"""DD-13's fail-closed purge ordering and the sweep's per-account isolation.

Requirement ids live on the individual tests below, deliberately **not** in
this docstring: `scripts/check_requirement_coverage.py` scans file text, so an
id parked in a module header reports covered while nothing asserts it.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import timedelta

import pytest

from app.container import Container
from app.exceptions import NotFoundError
from app.modules.agents.domain import AgentConnectionDocument
from app.repositories.feature_flag import (
    DegradedRuntimeFlagsError,
    FlagMode,
    FlagOverride,
)
from app.schemas.api import TreeCreateRequest
from app.schemas.auth import Invite, Session, User
from app.schemas.tasks import TaskCreateRequest
from app.services import InvalidCredentialsError
from app.services.feature_flag_service import SelectedUserNotFoundError
from app.utils.identifiers import generate_id
from app.utils.time import utcnow
from app.workflows.voice_brain_dump.domain import (
    BrainDumpConsent,
    BrainDumpOperationDocument,
)

PASSWORD_HASH_SENTINEL = "argon2-stored-hash-sentinel"
FEATURE_FLAG_SERVICE_LOGGER = "app.services.feature_flag_service"


def _member(container: Container, user_id: str, email: str, *, due: bool) -> User:
    user = User(
        id=user_id,
        email=email,
        password_hash=PASSWORD_HASH_SENTINEL,
        created_at=utcnow(),
        deletion_requested_at=utcnow() - timedelta(days=30) if due else None,
    )
    container.user_repo.create(user)
    return user


def _member_with_password(
    container: Container,
    user_id: str,
    email: str,
    password: str,
    *,
    due: bool,
) -> User:
    """Like `_member`, but with a real, verifiable password hash — needed to
    drive a real `AuthService.login` call rather than just reading the
    stored record."""

    user = User(
        id=user_id,
        email=email,
        password_hash=container.auth_service.hash_password(password),
        created_at=utcnow(),
        deletion_requested_at=utcnow() - timedelta(days=30) if due else None,
    )
    container.user_repo.create(user)
    return user


def _seed_owned_data(container: Container, member: User) -> dict[str, str]:
    """Create one representative record in every store `purge_account` touches."""

    now = utcnow()

    token_hash = generate_id("session")
    container.session_repo.create(
        Session(
            token_hash=token_hash,
            user_id=member.id,
            created_at=now,
            expires_at=now + timedelta(days=1),
        )
    )

    invite_code = generate_id("invite")
    container.invite_repo.create(
        Invite(
            code=invite_code,
            created_at=now,
            used_by_user_id=member.id,
            used_at=now,
        )
    )

    tree = container.tree_service.create_tree(
        TreeCreateRequest(name="Owned tree"), owner_id=member.id
    )

    task = container.task_service.create_task(
        TaskCreateRequest(title="Owned task"),
        owner_id=member.id,
        idempotency_key=generate_id("idem"),
    )

    operation_id = generate_id("op")
    container.voice_operation_repo.save_brain_dump_operation(
        BrainDumpOperationDocument(
            id=operation_id,
            owner_id=member.id,
            status="recording",
            consent=BrainDumpConsent(microphone=True, recorded_at=now),
            created_at=now,
            updated_at=now,
        )
    )

    connection_id = generate_id("conn")
    container.agent_repo.create_connection(
        AgentConnectionDocument(
            id=connection_id,
            owner_id=member.id,
            name="Owned connection",
            endpoint_url="https://example.com/webhook",
            created_at=now,
            updated_at=now,
        )
    )

    return {
        "token_hash": token_hash,
        "invite_code": invite_code,
        "tree_id": tree.id,
        "task_id": task.id,
        "operation_id": operation_id,
        "connection_id": connection_id,
    }


def _seed_cohort(
    container: Container,
    flag: str,
    mode: FlagMode,
    selected_users: tuple[str, ...],
) -> None:
    """Seed one managed flag's mode and cohort via the repository's own
    mutation seam — the same one `test_feature_flag_repository.py` uses."""

    def _apply(current: dict[str, FlagOverride]) -> dict[str, FlagOverride]:
        updated = dict(current)
        updated[flag] = FlagOverride(mode=mode, selected_users=selected_users)
        return updated

    container.feature_flag_repo.mutate(_apply)


def _degrade_store(container: Container, flag: str = "voice_brain_dump") -> None:
    """Malform the runtime-flag store by dropping one managed flag's row,
    mirroring the degradation seam in `test_feature_flag_repository.py`."""

    with sqlite3.connect(container.feature_flag_repo.db_path) as conn:
        conn.execute("DELETE FROM feature_flags WHERE flag = ?", (flag,))
        conn.commit()


def _repair_store(container: Container, flag: str = "voice_brain_dump") -> None:
    """Restore the row `_degrade_store` removed."""

    with sqlite3.connect(container.feature_flag_repo.db_path) as conn:
        conn.execute(
            "INSERT INTO feature_flags (flag, mode, selected_users) VALUES (?, 'off', '[]')",
            (flag,),
        )
        conn.commit()


def test_010_FR_007_purge_scrubs_every_cohort_before_deleting_the_account(
    container: Container,
) -> None:
    """A healthy store is scrubbed before the account record is deleted."""

    member = _member(container, "user_purged", "purged@example.com", due=False)
    _seed_cohort(
        container,
        "voice_brain_dump",
        FlagMode.SELECTED_USERS,
        ("user_kept", "user_purged"),
    )
    _seed_cohort(
        container,
        "mobile_task_classification",
        FlagMode.SELECTED_USERS,
        ("user_other", "user_purged"),
    )
    order: list[str] = []
    real_scrub = container.feature_flag_repo.scrub_user
    real_delete = container.user_repo.delete

    def _scrub(user_id: str) -> int:
        order.append("scrub")
        return real_scrub(user_id)

    def _delete(user_id: str) -> None:
        order.append("delete")
        real_delete(user_id)

    container.feature_flag_repo.scrub_user = _scrub  # type: ignore[method-assign]
    container.user_repo.delete = _delete  # type: ignore[method-assign]

    container.account_service.purge_account(member.id)

    assert order == ["scrub", "delete"]
    overlay = container.feature_flag_repo.read()
    assert overlay.degraded is False
    assert overlay.flags["voice_brain_dump"].selected_users == ("user_kept",)
    assert overlay.flags["mobile_task_classification"].selected_users == ("user_other",)
    assert container.user_repo.get_by_id(member.id) is None


def test_010_FR_007_purge_marks_deletion_before_scrub_closing_the_cohort_readd_race(
    container: Container, caplog: pytest.LogCaptureFixture
) -> None:
    """The durable `deletion_requested_at` marker must be stamped before
    `feature_flag_repo.scrub_user` ever runs.

    Without that ordering, a concurrent `add_selected_user` landing in the
    window after scrub releases its lock but before the user record is
    deleted finds a still-existing, not-yet-marked account and re-adds it to
    the cohort — leaving an orphaned ID once purge deletes the user. Hooking
    the real `scrub_user` to attempt exactly that add, from inside a real
    `purge_account` call, reproduces the race deterministically: on
    pre-fix code the add silently succeeds and the cohort ends up with the
    purged ID; with the marker set first, the add's own fresh
    `deletion_requested_at` check refuses it (010-FR-007, DD-13).
    """

    member = _member(container, "user_race", "race@example.com", due=False)
    container.feature_flag_service.set_mode(
        "voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op"
    )

    real_scrub = container.feature_flag_repo.scrub_user
    race_outcomes: list[BaseException | None] = []

    def _scrub_then_race_add(user_id: str) -> int:
        result = real_scrub(user_id)
        try:
            container.feature_flag_service.add_selected_user(
                "voice_brain_dump", operator_id="user_op", account_id=member.id
            )
        except SelectedUserNotFoundError as exc:
            race_outcomes.append(exc)
        else:
            race_outcomes.append(None)
        return result

    container.feature_flag_repo.scrub_user = _scrub_then_race_add  # type: ignore[method-assign]

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=FEATURE_FLAG_SERVICE_LOGGER):
        container.account_service.purge_account(member.id)

    assert len(race_outcomes) == 1
    assert isinstance(race_outcomes[0], SelectedUserNotFoundError)

    assert container.user_repo.get_by_id(member.id) is None
    overlay = container.feature_flag_repo.read()
    assert overlay.flags["voice_brain_dump"].selected_users == ()

    records = [
        r.getMessage() for r in caplog.records if r.name == FEATURE_FLAG_SERVICE_LOGGER
    ]
    assert not any("race@example.com" in message for message in records)


def test_010_FR_007_purge_advances_an_absent_or_within_grace_marker_to_a_past_due_cutoff(
    container: Container,
) -> None:
    """Purge's hard-purge marker step must not merely stamp `utcnow()`.

    A fresh `utcnow()` marker is still *inside* the grace period, so a
    concurrent, otherwise-legitimate login would see a perfectly ordinary
    cancellable deletion and clear it — undoing the point-of-no-return the
    marker exists to establish. The marker must instead land at (or before)
    the grace cutoff, so it reads as already past-due to anyone who
    fresh-checks it, whether the account never requested deletion at all or
    requested it moments ago.
    """

    grace = container.account_service.deletion_grace
    absent = _member(container, "user_absent_marker", "absent@example.com", due=False)
    recent = _member(container, "user_recent_marker", "recent@example.com", due=False)
    container.user_repo.mutate(
        recent.id,
        lambda fresh: fresh.model_copy(update={"deletion_requested_at": utcnow()}),
    )

    captured: dict[str, User] = {}
    real_scrub = container.feature_flag_repo.scrub_user

    def _capture_then_scrub(user_id: str) -> int:
        fresh = container.user_repo.get_by_id(user_id)
        assert fresh is not None
        captured[user_id] = fresh
        return real_scrub(user_id)

    container.feature_flag_repo.scrub_user = _capture_then_scrub  # type: ignore[method-assign]

    container.account_service.purge_account(absent.id)
    container.account_service.purge_account(recent.id)

    for member in (absent, recent):
        marker = captured[member.id]
        assert marker.deletion_requested_at is not None
        assert utcnow() >= marker.deletion_requested_at + grace


def test_010_FR_007_purge_marker_blocks_a_concurrent_login_and_cohort_readd(
    container: Container, caplog: pytest.LogCaptureFixture
) -> None:
    """The hard-purge marker purge stamps up front must also close the
    login-cancellation race, not just the cohort re-add race.

    A concurrent, otherwise-valid login landing after purge's marker step
    reads a marker that already reads as past-due (purge's own
    point-of-no-return stamp), so it must refuse like any bad credential and
    create no session — never clear the marker the way an ordinary
    within-grace cancellation would. Hooking the real `scrub_user` to attempt
    exactly that login, then the cohort re-add, from inside a real
    `purge_account` call reproduces both races deterministically in one pass
    (010-FR-007, DD-13).
    """

    password = "correct-horse-battery-staple-login-race"
    member = _member_with_password(
        container, "user_login_race", "login-race@example.com", password, due=False
    )
    container.feature_flag_service.set_mode(
        "voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op"
    )

    real_scrub = container.feature_flag_repo.scrub_user
    login_outcomes: list[BaseException | None] = []
    add_outcomes: list[BaseException | None] = []
    marker_after_login: list[User | None] = []

    def _scrub_then_race(user_id: str) -> int:
        marker_before = container.user_repo.get_by_id(user_id)
        assert marker_before is not None
        assert marker_before.deletion_requested_at is not None
        assert (
            utcnow()
            >= marker_before.deletion_requested_at
            + container.account_service.deletion_grace
        )

        try:
            container.auth_service.login(
                email="login-race@example.com", password=password
            )
        except InvalidCredentialsError as exc:
            login_outcomes.append(exc)
        else:
            login_outcomes.append(None)

        marker_after_login.append(container.user_repo.get_by_id(user_id))

        result = real_scrub(user_id)

        try:
            container.feature_flag_service.add_selected_user(
                "voice_brain_dump", operator_id="user_op", account_id=user_id
            )
        except SelectedUserNotFoundError as exc:
            add_outcomes.append(exc)
        else:
            add_outcomes.append(None)
        return result

    container.feature_flag_repo.scrub_user = _scrub_then_race  # type: ignore[method-assign]

    caplog.clear()
    with caplog.at_level(logging.INFO):
        container.account_service.purge_account(member.id)

    assert len(login_outcomes) == 1
    assert isinstance(login_outcomes[0], InvalidCredentialsError)
    assert marker_after_login[0] is not None
    assert marker_after_login[0].deletion_requested_at is not None

    assert len(add_outcomes) == 1
    assert isinstance(add_outcomes[0], SelectedUserNotFoundError)

    assert container.user_repo.get_by_id(member.id) is None
    overlay = container.feature_flag_repo.read()
    assert overlay.flags["voice_brain_dump"].selected_users == ()

    assert not any(
        "login-race@example.com" in record.getMessage() for record in caplog.records
    )


def test_010_FR_007_purge_preserves_an_already_past_due_deletion_marker_exactly(
    container: Container,
) -> None:
    """An account that already carries a past-due `deletion_requested_at`
    (the normal due-sweep path) must not have that timestamp rewritten by
    purge's own marker step. An absent or still-within-grace marker *is*
    advanced (see the cutoff test above) — only an already past-due
    timestamp is ever preserved exactly."""

    member = _member(container, "user_marked", "marked@example.com", due=True)
    original = member.deletion_requested_at
    assert original is not None

    captured: list[User] = []
    real_scrub = container.feature_flag_repo.scrub_user

    def _capture_then_scrub(user_id: str) -> int:
        fresh = container.user_repo.get_by_id(user_id)
        assert fresh is not None
        captured.append(fresh)
        return real_scrub(user_id)

    container.feature_flag_repo.scrub_user = _capture_then_scrub  # type: ignore[method-assign]

    container.account_service.purge_account(member.id)

    assert len(captured) == 1
    assert captured[0].deletion_requested_at == original
    assert container.user_repo.get_by_id(member.id) is None


def test_010_FR_004_a_degraded_document_halts_the_purge_before_any_deletion(
    container: Container,
) -> None:
    """Every owned record — account, session, voice, agent, task, tree, and
    invite data — is retained until the degraded runtime-flag document is
    repaired, because `scrub_user` now runs before any destructive step."""

    member = _member(container, "user_blocked", "blocked@example.com", due=False)
    owned = _seed_owned_data(container, member)
    _degrade_store(container)

    with pytest.raises(DegradedRuntimeFlagsError):
        container.account_service.purge_account(member.id)

    retained = container.user_repo.get_by_id(member.id)
    assert retained is not None
    assert retained.email == "blocked@example.com"
    assert retained.password_hash == PASSWORD_HASH_SENTINEL
    # The durable deletion-pending marker is stamped before scrub even runs,
    # so it survives a refusal here and keeps retries/cohort mutations
    # fail-safe while the document stays degraded (010-FR-007, DD-13).
    assert retained.deletion_requested_at is not None

    assert container.session_repo.get(owned["token_hash"]) is not None

    invite = container.invite_repo.get(owned["invite_code"])
    assert invite is not None
    assert invite.used_by_user_id == member.id

    assert container.tree_service.get_tree_for_owner(
        owned["tree_id"], owner_id=member.id
    )

    assert (
        container.task_repo.get_for_owner(owned["task_id"], owner_id=member.id)
        is not None
    )

    assert (
        container.voice_operation_repo.get_brain_dump_operation_for_owner(
            owned["operation_id"], owner_id=member.id
        )
        is not None
    )

    assert (
        container.agent_repo.get_connection(owned["connection_id"], owner_id=member.id)
        is not None
    )


def test_010_FR_007_a_repaired_document_lets_a_retried_purge_succeed(
    container: Container,
) -> None:
    """The 60-second sweep retries until an operator repairs the document."""

    member = _member(container, "user_retry", "retry@example.com", due=True)
    _degrade_store(container)

    assert container.account_service.purge_due_accounts() == 0
    assert container.user_repo.get_by_id(member.id) is not None

    _repair_store(container)

    assert container.account_service.purge_due_accounts() == 1
    assert container.user_repo.get_by_id(member.id) is None


def test_010_FR_004_the_sweep_isolates_one_account_s_failure_from_the_rest(
    container: Container,
) -> None:
    """One corrupt document must not stall every other member's GDPR deletion."""

    blocked = _member(container, "user_blocked", "blocked@example.com", due=True)
    other = _member(container, "user_other", "other@example.com", due=True)
    third = _member(container, "user_third", "third@example.com", due=True)

    real_scrub = container.feature_flag_repo.scrub_user

    def _selective_scrub(user_id: str) -> int:
        if user_id == blocked.id:
            raise DegradedRuntimeFlagsError()
        return real_scrub(user_id)

    container.feature_flag_repo.scrub_user = _selective_scrub  # type: ignore[method-assign]

    purged = container.account_service.purge_due_accounts()

    assert purged == 2
    assert container.user_repo.get_by_id(blocked.id) is not None
    assert container.user_repo.get_by_id(other.id) is None
    assert container.user_repo.get_by_id(third.id) is None


def test_010_FR_007_purge_of_an_unknown_account_still_tolerates_absent_data(
    container: Container,
) -> None:
    """Purge stays idempotent: a second pass over already-erased data is a no-op."""

    member = _member(container, "user_twice", "twice@example.com", due=False)
    container.account_service.purge_account(member.id)

    container.account_service.purge_account(member.id)

    assert container.user_repo.get_by_id(member.id) is None
    with pytest.raises(NotFoundError):
        container.admin_service.revoke_sessions(
            operator_id="user_op", account_id=member.id
        )
