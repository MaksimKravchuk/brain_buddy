"""Tests for the account-deletion grace period and purge lifecycle."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.container import Container
from app.utils.time import utcnow

from .conftest import (
    SECOND_USER_EMAIL,
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    BrainBuddyTestClient,
)
from .test_brain_dump_operations_api import _start_operation, _upload_and_seal


def _container(client: TestClient) -> Container:
    return client.app.state.container  # type: ignore[attr-defined]


def _data_dir(client: TestClient) -> Path:
    return _container(client).user_repo.root


def _user_id(client: TestClient) -> str:
    return client.get("/api/account").json()["id"]


def _request_deletion(client: TestClient) -> dict:
    resp = client.post(
        "/api/account/delete", json={"current_password": TEST_USER_PASSWORD}
    )
    assert resp.status_code == 202, resp.text
    return resp.json()


def _backdate_deletion(client: TestClient, user_id: str, *, days: int) -> None:
    repo = _container(client).user_repo
    user = repo.get_by_id(user_id)
    assert user is not None and user.deletion_requested_at is not None
    repo.save(
        user.model_copy(
            update={"deletion_requested_at": utcnow() - timedelta(days=days)}
        )
    )


def _owner_rows(db_path: Path, table: str, owner_id: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE owner_id = ?", (owner_id,)
        ).fetchone()[0]


# ----------------------------------------------------------------------
# Requesting deletion
# ----------------------------------------------------------------------


def test_request_deletion_schedules_purge_and_revokes_sessions(
    api_client: TestClient,
) -> None:
    """A 202 announces the purge date; every session dies immediately."""

    other = BrainBuddyTestClient(api_client.app)  # type: ignore[attr-defined]
    login = other.post(
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert login.status_code == 200

    body = _request_deletion(api_client)
    assert body["deletion_requested_at"] < body["purge_at"]

    assert api_client.get("/api/account").status_code == 401
    assert other.get("/api/account").status_code == 401


def test_request_deletion_wrong_password_is_403(api_client: TestClient) -> None:
    """A failed re-auth schedules nothing and keeps the session alive."""

    resp = api_client.post(
        "/api/account/delete", json={"current_password": "wrong-pass"}
    )
    assert resp.status_code == 403
    account = api_client.get("/api/account")
    assert account.status_code == 200
    assert account.json()["deletion_requested_at"] is None


def test_repeat_deletion_request_keeps_original_purge_date(
    api_client: TestClient,
) -> None:
    """Re-requesting deletion never moves the purge date later."""

    user_id = _user_id(api_client)
    _request_deletion(api_client)

    container = _container(api_client)
    first = container.user_repo.get_by_id(user_id)
    assert first is not None and first.deletion_requested_at is not None

    again = container.account_service.request_deletion(
        first, current_password=TEST_USER_PASSWORD
    )
    assert again.deletion_requested_at == first.deletion_requested_at


# ----------------------------------------------------------------------
# Logging back in
# ----------------------------------------------------------------------


def test_login_during_grace_cancels_deletion(api_client: TestClient) -> None:
    """A login inside the grace period cancels the pending deletion."""

    _request_deletion(api_client)

    fresh = BrainBuddyTestClient(api_client.app)  # type: ignore[attr-defined]
    login = fresh.post(
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["deletion_cancelled"] is True

    account = fresh.get("/api/account")
    assert account.json()["deletion_requested_at"] is None

    # A normal login afterwards doesn't claim to have cancelled anything.
    again = BrainBuddyTestClient(api_client.app).post(  # type: ignore[attr-defined]
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert again.json()["deletion_cancelled"] is False


def test_login_after_grace_is_refused_generically(api_client: TestClient) -> None:
    """Past the grace period the login fails like any bad credential."""

    user_id = _user_id(api_client)
    _request_deletion(api_client)
    _backdate_deletion(api_client, user_id, days=15)

    login = BrainBuddyTestClient(api_client.app).post(  # type: ignore[attr-defined]
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert login.status_code == 401
    assert login.json()["message"] == "Invalid email or password."


# ----------------------------------------------------------------------
# Purge
# ----------------------------------------------------------------------


def test_purge_due_accounts_erases_everything(second_api_client) -> None:
    """Every store loses the purged owner's data; the other user keeps theirs."""

    client_a, client_b = second_api_client
    container = _container(client_a)
    data_dir = _data_dir(client_a)
    owner_a = _user_id(client_a)
    owner_b = _user_id(client_b)

    # Seed user A: a tree, a task, and a sealed voice operation with audio.
    tree_a = client_a.post("/api/trees", json={"name": "Alice thinking"})
    assert tree_a.status_code == 201
    tree_a_id = tree_a.json()["id"]
    task_a = client_a.post(
        "/api/tasks",
        headers={"Idempotency-Key": "purge-task-a"},
        json={"title": "Alice secret task"},
    )
    assert task_a.status_code == 201
    operation = _start_operation(client_a, key="purge-voice-a")
    _upload_and_seal(client_a, operation, b"Pay VAT. Send invoice.", "purge-seal-a")

    # Seed user B with the same shapes.
    tree_b = client_b.post("/api/trees", json={"name": "Bob thinking"})
    assert tree_b.status_code == 201
    tree_b_id = tree_b.json()["id"]
    task_b = client_b.post(
        "/api/tasks",
        headers={"Idempotency-Key": "purge-task-b"},
        json={"title": "Bob keeps this"},
    )
    assert task_b.status_code == 201

    _request_deletion(client_a)
    _backdate_deletion(client_a, owner_a, days=15)

    purged = container.account_service.purge_due_accounts()
    assert purged == 1

    # Account storage: user file, email index, and sessions are gone.
    assert container.user_repo.get_by_id(owner_a) is None
    assert container.user_repo.get_by_email(TEST_USER_EMAIL) is None
    assert container.session_repo.delete_all_for_user(owner_a) == 0

    # Trees: index entry and directory (versions/validation included) gone.
    assert container.tree_service.list_trees(owner_id=owner_a) == []
    assert not (data_dir / tree_a_id).exists()

    # Tasks: SQLite rows and JSON mirrors gone.
    tasks_db = data_dir / "tasks.sqlite3"
    for table in ("tasks", "projects", "tags", "idempotency_records"):
        assert _owner_rows(tasks_db, table, owner_a) == 0
    for dirname in ("tasks", "projects", "contexts", "task-commands"):
        assert not (data_dir / dirname / owner_a).exists()

    # Voice: SQLite rows, mirrors, and raw audio media gone.
    voice_db = data_dir / "voice_operations.sqlite3"
    for table in ("brain_dump_operations", "idempotency_records"):
        assert _owner_rows(voice_db, table, owner_a) == 0
    for dirname in (
        "brain-dump-operations",
        "brain-dump-media",
        "voice-operation-commands",
    ):
        assert not (data_dir / dirname / owner_a).exists()

    # Invites: the consumed invite no longer names the purged user.
    for path in (data_dir / "invites").glob("*.json"):
        assert owner_a not in path.read_text(encoding="utf-8")

    # The purged email can no longer sign in.
    login = BrainBuddyTestClient(client_a.app).post(  # type: ignore[attr-defined]
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert login.status_code == 401

    # User B is untouched.
    assert client_b.get("/api/account").json()["email"] == SECOND_USER_EMAIL
    assert client_b.get(f"/api/trees/{tree_b_id}").status_code == 200
    assert _owner_rows(tasks_db, "tasks", owner_b) == 1

    # Nothing further to purge.
    assert container.account_service.purge_due_accounts() == 0


def test_purge_account_is_idempotent(api_client: TestClient) -> None:
    """Running the purge twice (crash-retry semantics) is harmless."""

    container = _container(api_client)
    owner = _user_id(api_client)
    tree = api_client.post("/api/trees", json={"name": "Short-lived"})
    assert tree.status_code == 201

    container.account_service.purge_account(owner)
    container.account_service.purge_account(owner)

    assert container.user_repo.get_by_id(owner) is None
    assert container.tree_service.list_trees(owner_id=owner) == []


def test_stale_profile_save_cannot_unschedule_deletion(api_client: TestClient) -> None:
    """A mutation via a pre-deletion user snapshot must not clear the flag.

    Regression: request handlers hold a request-scoped copy of the user; a
    full-record save from that stale copy could silently resurrect an
    account whose deletion was scheduled meanwhile.
    """

    container = _container(api_client)
    user_id = _user_id(api_client)
    stale = container.user_repo.get_by_id(user_id)
    assert stale is not None and stale.deletion_requested_at is None

    _request_deletion(api_client)

    updated = container.account_service.update_profile(stale, display_name="Racer")
    assert updated.display_name == "Racer"
    assert updated.deletion_requested_at is not None

    fresh = container.user_repo.get_by_id(user_id)
    assert fresh is not None and fresh.deletion_requested_at is not None


def test_account_purge_survives_voice_sweep_failure(
    api_client: TestClient, monkeypatch
) -> None:
    """A broken voice pipeline must never starve GDPR erasure."""

    from app.main import _run_maintenance_sweep

    container = _container(api_client)
    owner = _user_id(api_client)
    _request_deletion(api_client)
    _backdate_deletion(api_client, owner, days=15)

    def _boom(**_kwargs: object) -> int:
        raise RuntimeError("persistently corrupt voice operation")

    monkeypatch.setattr(
        container.voice_brain_dump_service, "recover_due_provider_leases", _boom
    )

    _run_maintenance_sweep(container)

    assert container.user_repo.get_by_id(owner) is None


def test_purge_removes_stale_index_entry_after_interrupted_delete(
    api_client: TestClient,
) -> None:
    """A retried purge cleans index entries whose tree files are already gone."""

    import shutil

    container = _container(api_client)
    owner = _user_id(api_client)
    tree = api_client.post("/api/trees", json={"name": "Half deleted"})
    assert tree.status_code == 201
    tree_id = tree.json()["id"]

    # Simulate a purge that died between removing the tree directory and
    # updating index.json: the files are gone but the entry survives.
    shutil.rmtree(_data_dir(api_client) / tree_id)
    assert container.tree_service.list_trees(owner_id=owner) != []

    container.account_service.purge_account(owner)

    assert container.tree_service.list_trees(owner_id=owner) == []
    assert all(entry.owner_id != owner for entry in container.index_repo.load_all())


def test_accounts_inside_grace_are_not_purged(api_client: TestClient) -> None:
    """The sweep must never touch an account still inside its grace window."""

    container = _container(api_client)
    owner = _user_id(api_client)
    _request_deletion(api_client)

    assert container.account_service.purge_due_accounts() == 0
    assert container.user_repo.get_by_id(owner) is not None
