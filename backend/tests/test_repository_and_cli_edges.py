"""Regression tests for command and repository edge behaviour."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import allure
import pytest
from typer.testing import CliRunner

from app import cli
from app.exceptions import ConflictError, NotFoundError
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


def test_purge_due_accounts_cli_reports_purged_count(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_config", lambda: None)
    monkeypatch.setattr(cli, "build_container", lambda _config: container)
    user = User(
        id="user_cli_purge",
        email="cli-purge@example.com",
        password_hash="x",
        created_at=datetime.now(UTC),
        deletion_requested_at=datetime.now(UTC) - timedelta(days=15),
    )
    container.user_repo.create(user)

    result = CliRunner().invoke(cli.app, ["purge-due-accounts"])

    assert result.exit_code == 0
    assert "Purged 1 account(s)." in result.stdout
    assert container.user_repo.get_by_id("user_cli_purge") is None


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


@allure.epic("Authentication & Access")
@allure.feature("Identity storage")
@allure.story("022-FR-002: canonical session expiry preserves other sessions")
def test_session_repository_removes_expired_sessions_and_ignores_missing_delete(
    data_dir,
) -> None:
    repository = SessionRepository(data_dir)
    now = datetime.now(UTC)
    UserRepository(data_dir, repository.store).create(
        User(id="user", email="owner@example.com", password_hash="hash", created_at=now)
    )
    expired = Session(
        token_hash="expired",
        user_id="user",
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    repository.create(expired)
    valid = expired.model_copy(
        update={"token_hash": "valid", "expires_at": now + timedelta(hours=1)}
    )
    repository.create(valid)
    with repository.store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 2

    assert repository.get(expired.token_hash) is None
    with repository.store.connection() as connection:
        assert (
            connection.execute("SELECT token_hash FROM sessions").fetchall()[0][0]
            == valid.token_hash
        )
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    repository.delete("already-missing")
    assert repository.get(valid.token_hash) == valid


@allure.epic("Authentication & Access")
@allure.feature("Identity storage")
@allure.story("022-FR-002: legacy email normalization survives reopening")
def test_user_repository_normalizes_canonical_sqlite_record_and_payload(
    data_dir,
) -> None:
    repository = UserRepository(data_dir)
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
    with repository.store.connection() as connection:
        row = connection.execute(
            "SELECT email,payload_json FROM users WHERE id=?", (created.id,)
        ).fetchone()
    assert row["email"] == "user@example.com"
    assert json.loads(row["payload_json"])["email"] == row["email"]
    assert UserRepository(data_dir).get_by_email(" USER@example.com ") == created
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
