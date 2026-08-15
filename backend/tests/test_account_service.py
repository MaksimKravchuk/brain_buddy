"""DD-13's fail-closed purge ordering and the sweep's per-account isolation.

Requirement ids live on the individual tests below, deliberately **not** in
this docstring: `scripts/check_requirement_coverage.py` scans file text, so an
id parked in a module header reports covered while nothing asserts it.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from app.container import Container
from app.exceptions import NotFoundError
from app.modules.agents.domain import AgentConnectionDocument
from app.repositories.feature_flag import DegradedRuntimeFlagsError
from app.schemas.api import TreeCreateRequest
from app.schemas.auth import Invite, Session, User
from app.schemas.tasks import TaskCreateRequest
from app.utils.identifiers import generate_id
from app.utils.time import utcnow
from app.workflows.voice_brain_dump.domain import (
    BrainDumpConsent,
    BrainDumpOperationDocument,
)

PASSWORD_HASH_SENTINEL = "argon2-stored-hash-sentinel"


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


def _write_document(container: Container, payload: object) -> Path:
    path = container.feature_flag_repo.document_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_010_FR_007_purge_scrubs_every_cohort_before_deleting_the_account(
    container: Container,
) -> None:
    """A healthy document is scrubbed before the account record is deleted."""

    member = _member(container, "user_purged", "purged@example.com", due=False)
    _write_document(
        container,
        {
            "voice_brain_dump": {
                "mode": "selected_users",
                "selected_users": ["user_purged", "user_kept"],
            },
            "future_flag": {"selected_users": ["user_purged"], "kept": True},
        },
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
    stored = json.loads(
        container.feature_flag_repo.document_path.read_text(encoding="utf-8")
    )
    assert stored["voice_brain_dump"]["selected_users"] == ["user_kept"]
    assert stored["future_flag"] == {"selected_users": [], "kept": True}
    assert container.user_repo.get_by_id(member.id) is None


def test_010_FR_004_a_degraded_document_halts_the_purge_before_any_deletion(
    container: Container,
) -> None:
    """Every owned record — account, session, voice, agent, task, tree, and
    invite data — is retained until the degraded runtime-flag document is
    repaired, because `scrub_user` now runs before any destructive step."""

    member = _member(container, "user_blocked", "blocked@example.com", due=False)
    owned = _seed_owned_data(container, member)
    _write_document(container, "{not json at all")

    with pytest.raises(DegradedRuntimeFlagsError):
        container.account_service.purge_account(member.id)

    retained = container.user_repo.get_by_id(member.id)
    assert retained is not None
    assert retained.email == "blocked@example.com"
    assert retained.password_hash == PASSWORD_HASH_SENTINEL

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
    path = _write_document(container, "{not json at all")

    assert container.account_service.purge_due_accounts() == 0
    assert container.user_repo.get_by_id(member.id) is not None

    path.unlink()

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
