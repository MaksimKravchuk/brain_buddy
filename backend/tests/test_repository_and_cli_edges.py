"""Regression tests for command and repository edge behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app import cli
from app.exceptions import ConflictError, NotFoundError, StorageUnavailableError
from app.repositories import (
    InviteRepository,
    ProviderRepository,
    SessionRepository,
    UserRepository,
)
from app.schemas.api import TreeCreateRequest, VersionCreateRequest
from app.schemas.auth import Invite, Session, User
from app.schemas.domain import ProviderConfig


def test_create_invite_cli_persists_and_prints_a_one_shot_code(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_config", lambda: None)
    monkeypatch.setattr(cli, "build_container", lambda _config: container)

    result = CliRunner().invoke(cli.app, ["create-invite"])

    assert result.exit_code == 0
    code = result.stdout.strip()
    assert code
    assert container.invite_repo.get(code) is not None


def test_provider_registry_round_trips_default_and_provider_config(data_dir) -> None:
    repository = ProviderRepository(data_dir)

    assert repository.load().providers == {}
    configured = repository.upsert_provider("local", ProviderConfig(model="test-model"))
    defaulted = repository.set_default_provider("local")

    assert configured.providers["local"].model == "test-model"
    assert defaulted.default_provider == "local"
    assert repository.load().providers["local"].model == "test-model"


def test_invite_repository_rejects_duplicate_and_consumed_or_unknown_codes(
    data_dir,
) -> None:
    repository = InviteRepository(data_dir)
    invite = Invite(code="once", created_at=datetime.now(UTC))
    repository.create(invite)

    with pytest.raises(ConflictError):
        repository.create(invite)
    with pytest.raises(NotFoundError):
        repository.mark_used("missing", user_id="user", used_at=datetime.now(UTC))

    consumed = repository.mark_used("once", user_id="user", used_at=datetime.now(UTC))

    assert consumed.is_used
    with pytest.raises(ConflictError):
        repository.mark_used("once", user_id="other", used_at=datetime.now(UTC))


def test_session_repository_removes_expired_sessions_and_ignores_missing_delete(
    data_dir,
) -> None:
    repository = SessionRepository(data_dir)
    now = datetime.now(UTC)
    expired = Session(
        token_hash="expired",
        user_id="user",
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    repository.create(expired)

    assert repository.get(expired.token_hash) is None
    assert not repository._session_path(expired.token_hash).exists()
    repository.delete("already-missing")


def test_session_repository_get_maps_exists_os_error_to_storage_unavailable(
    data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A storage outage surfacing through `Path.exists()` must not raise a bare OSError.

    Since Python 3.13, `Path.exists()` re-raises OS errors other than
    ENOENT/ENOTDIR/EACCES/ELOOP instead of swallowing them, so a transient
    disk outage during the existence check must still be translated by the
    repository's own `_file_guard`, not leak out as a raw 500.
    """

    repository = SessionRepository(data_dir)
    now = datetime.now(UTC)
    session = Session(
        token_hash="present",
        user_id="user",
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    repository.create(session)

    def _boom(self: Path) -> bool:
        raise OSError("simulated storage outage")

    monkeypatch.setattr(Path, "exists", _boom)

    with pytest.raises(StorageUnavailableError):
        repository.get(session.token_hash)


def test_session_repository_get_maps_expired_unlink_os_error_to_storage_unavailable(
    data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lazy cleanup of an expired session must also translate outage errors.

    `get()` unlinks an expired session file inline; a permission/outage error
    during that unlink (anything other than the already-missing case) must
    surface as `StorageUnavailableError`, not propagate as a bare OSError.
    """

    repository = SessionRepository(data_dir)
    now = datetime.now(UTC)
    expired = Session(
        token_hash="expired-outage",
        user_id="user",
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    repository.create(expired)

    def _boom(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError("simulated storage outage")

    monkeypatch.setattr(Path, "unlink", _boom)

    with pytest.raises(StorageUnavailableError):
        repository.get(expired.token_hash)


def test_user_repository_handles_malformed_index_and_normalizes_new_users(
    data_dir,
) -> None:
    repository = UserRepository(data_dir)
    repository.index_path.write_text("[]", encoding="utf-8")
    now = datetime.now(UTC)
    user = User(
        id="user_1",
        email="  USER@EXAMPLE.COM ",
        password_hash="hash",
        created_at=now,
    )

    assert repository.get_by_id("missing") is None
    created = repository.create(user)

    assert created.email == "user@example.com"
    assert repository.get_by_email("USER@example.com") == created
    with pytest.raises(ConflictError):
        repository.create(user)


def test_version_repository_rejects_missing_snapshot_and_deletes_existing_one(
    tree_service, version_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Version repository"), owner_id="owner"
    )
    version = version_service.create_version(
        tree.id, VersionCreateRequest(label="before delete")
    )
    repository = version_service.version_repo

    with pytest.raises(NotFoundError):
        repository.load(tree.id, "missing")

    repository.delete(tree.id, version.id)

    with pytest.raises(NotFoundError):
        repository.delete(tree.id, version.id)
