"""Operational migration is explicit; committed cleanup and erasure are automatic."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import app
from app.container import build_container
from app.core.config import AppConfig, AppEnvironment, DataSettings, get_config
from app.exceptions import RepositoryError
from app.services.auth_migration import AuthMigration
from app.services.auth_secret_box import AuthSecretBox


def legacy(root: Path) -> None:
    users = root / "users"
    users.mkdir(parents=True)
    users.joinpath("user_original.json").write_text(
        json.dumps(
            {
                "id": "user_original",
                "email": "original@example.com",
                "password_hash": "$argon2id$legacy",
                "created_at": "2026-01-01T00:00:00Z",
            }
        )
    )
    users.joinpath("_by_email.json").write_text(
        json.dumps({"original@example.com": "user_original"})
    )


def test_022_FR_002_startup_refuses_unmigrated_nonempty_legacy_root(
    tmp_path: Path,
) -> None:
    legacy(tmp_path)
    with pytest.raises(RepositoryError):
        build_container(
            AppConfig(
                environment=AppEnvironment.TEST, data=DataSettings(root_dir=tmp_path)
            )
        )
    assert not tmp_path.joinpath("auth.sqlite3").exists()
    assert tmp_path.joinpath("users/user_original.json").exists()


def test_022_FR_014_startup_resumes_committed_cleanup_without_keys(
    tmp_path: Path, monkeypatch
) -> None:
    legacy(tmp_path)
    migration = AuthMigration(tmp_path, AuthSecretBox({"k1": b"1" * 32}, "k1"))
    monkeypatch.setattr(
        migration,
        "_cleanup_sources",
        lambda _store: (_ for _ in ()).throw(OSError("simulated crash")),
    )
    with pytest.raises(RepositoryError):
        migration.migrate(writers_stopped=True)
    container = build_container(
        AppConfig(environment=AppEnvironment.TEST, data=DataSettings(root_dir=tmp_path))
    )
    assert container.user_repo.get_by_id("user_original") is not None
    assert not tmp_path.joinpath("users/user_original.json").exists()
    assert container.user_repo.store is container.session_repo.store


def test_022_FR_018_cli_import_and_account_purge_erase_entire_backup(
    tmp_path: Path, monkeypatch
) -> None:
    legacy(tmp_path)
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_AUTH_CURRENT_KEY_ID", "k1")
    monkeypatch.setenv(
        "BRAIN_BUDDY_AUTH_KEYRING",
        json.dumps({"k1": base64.b64encode(b"1" * 32).decode()}),
    )
    get_config.cache_clear()
    runner = CliRunner()
    refused = runner.invoke(app, ["migrate-auth"])
    assert refused.exit_code != 0
    assert not tmp_path.joinpath("auth.sqlite3").exists()
    result = runner.invoke(app, ["migrate-auth", "--writers-stopped"])
    assert result.exit_code == 0, result.output
    assert "original@example.com" not in result.output
    assert "legacy" not in result.output
    assert json.loads(result.output)["users_imported"] == 1
    assert tmp_path.joinpath(".auth-migration-backup.enc").exists()
    container = build_container(get_config())
    container.account_service.purge_account("user_original")
    assert not tmp_path.joinpath(".auth-migration-backup.enc").exists()
    assert container.user_repo.get_by_id("user_original") is None
