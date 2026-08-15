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
    user, token, deletion_cancelled = container.auth_service.login(
        email="bob@example.com", password="very-long-password"
    )
    assert deletion_cancelled is False
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
    _, token, _ = container.auth_service.login(
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
    _, token, _ = container.auth_service.login(
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


def test_login_stale_snapshot_cannot_clear_a_marker_purge_advances_mid_call(
    container,
) -> None:
    """`login` must not trust the snapshot it read before acquiring the
    repository write lock.

    If a purge's hard-purge marker step lands in the window between login's
    initial read (which sees a cancellable, within-grace marker) and its
    cancellation `mutate` call, the mutate's own fresh re-check must see the
    now-past-due marker and refuse — not blindly clear whatever the stale
    snapshot showed, and not create a session. A narrow hook on
    `UserRepository.mutate` reproduces this interleaving deterministically,
    without sleeps or real threads standing in for the concurrent purge.
    """

    code = _create_invite(container)
    user, _ = container.auth_service.signup(
        email="stale-race@example.com",
        password="very-long-password",
        invite_code=code,
    )
    container.account_service.request_deletion(
        user, current_password="very-long-password"
    )
    pending = container.user_repo.get_by_id(user.id)
    assert pending is not None and pending.deletion_requested_at is not None

    real_mutate = container.user_repo.mutate
    triggered = False

    def _mutate_with_purge_barrier(user_id, mutator):
        nonlocal triggered
        if not triggered:
            triggered = True
            # Stand in for a concurrent `purge_account` whose hard-purge
            # marker step lands in the gap between login's snapshot read
            # and this `mutate` call — `.save()` bypasses `mutate` itself so
            # the barrier doesn't recurse into this hook.
            fresh = container.user_repo.get_by_id(user_id)
            assert fresh is not None
            cutoff = utcnow() - container.account_service.deletion_grace
            container.user_repo.save(
                fresh.model_copy(update={"deletion_requested_at": cutoff})
            )
        return real_mutate(user_id, mutator)

    container.user_repo.mutate = _mutate_with_purge_barrier  # type: ignore[method-assign]

    with pytest.raises(InvalidCredentialsError):
        container.auth_service.login(
            email="stale-race@example.com", password="very-long-password"
        )

    assert triggered

    refreshed = container.user_repo.get_by_id(user.id)
    assert refreshed is not None
    assert refreshed.deletion_requested_at is not None
    assert (
        utcnow()
        >= refreshed.deletion_requested_at + container.auth_service.deletion_grace
    )
    # No session was created for the refused login.
    assert container.session_repo.delete_all_for_user(user.id) == 0


def test_login_unmarked_snapshot_purge_interposes_before_fresh_mutate(
    container,
) -> None:
    """An unmarked snapshot must not let login skip the fresh marker check.

    `login`'s initial `get_by_email` read is only ever a stale snapshot. If a
    real purge marks, scrubs and deletes the account entirely in the window
    between that read and login's write-locked mutate, the now-mandatory
    fresh mutate must still observe it — even though the stale snapshot it
    started with carried no marker at all — and refuse before any session is
    created. A hook on the first `UserRepository.mutate` call reproduces this
    deterministically: on the old code path (which only calls `mutate` when
    the stale snapshot already carries a marker) the hook never fires, the
    purge never runs, and login sails through — this must fail red first.
    """

    code = _create_invite(container)
    user, _ = container.auth_service.signup(
        email="unmarked-race@example.com",
        password="very-long-password",
        invite_code=code,
    )
    assert user.deletion_requested_at is None

    real_mutate = container.user_repo.mutate
    triggered = False

    def _mutate_with_purge_barrier(user_id, mutator):
        nonlocal triggered
        if not triggered:
            triggered = True
            # Stand in for a concurrent purge that starts and completes in
            # full — marker, cohort/session scrub, and final user delete —
            # in the gap between login's stale snapshot read and this
            # `mutate` call.
            container.account_service.purge_account(user_id)
        return real_mutate(user_id, mutator)

    container.user_repo.mutate = _mutate_with_purge_barrier  # type: ignore[method-assign]

    with pytest.raises(InvalidCredentialsError):
        container.auth_service.login(
            email="unmarked-race@example.com", password="very-long-password"
        )

    assert triggered
    assert container.user_repo.get_by_id(user.id) is None
    # No orphan session survives the refused login.
    assert container.session_repo.delete_all_for_user(user.id) == 0


def test_login_purge_interposes_between_fresh_mutate_and_session_create(
    container,
) -> None:
    """Closing the fresh-mutate window isn't enough on its own — a purge can
    also land between that mutate and session creation.

    A hook on `_create_session` reproduces a purge (marker, scrub, and final
    user delete) that completes entirely in that narrower gap, after login's
    fresh check has already passed but before the session row exists. Once
    the session is created, login must re-read the user, notice the account
    is gone, delete the just-created session, and refuse — never return a
    token for a session whose owner no longer exists.
    """

    code = _create_invite(container)
    user, _ = container.auth_service.signup(
        email="post-mutate-race@example.com",
        password="very-long-password",
        invite_code=code,
    )
    assert user.deletion_requested_at is None

    real_create_session = container.auth_service._create_session
    triggered = False

    def _create_session_with_purge_barrier(user_id):
        nonlocal triggered
        if not triggered:
            triggered = True
            # Stand in for a concurrent purge that starts and completes in
            # full after login's fresh marker check but before the session
            # row is written.
            container.account_service.purge_account(user_id)
        return real_create_session(user_id)

    container.auth_service._create_session = _create_session_with_purge_barrier  # type: ignore[method-assign]

    with pytest.raises(InvalidCredentialsError):
        container.auth_service.login(
            email="post-mutate-race@example.com", password="very-long-password"
        )

    assert triggered
    assert container.user_repo.get_by_id(user.id) is None
    # The session created just before the post-check must not survive it.
    assert container.session_repo.delete_all_for_user(user.id) == 0
