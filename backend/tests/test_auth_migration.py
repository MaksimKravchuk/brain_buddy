"""Synthetic stopped-writer migration, parity and crash-boundary tests."""

from __future__ import annotations

import fcntl
import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import allure
import pytest

from app.exceptions import RepositoryError
from app.repositories.auth_store import AuthStore
from app.repositories.session import SessionRepository
from app.repositories.user import UserRepository
from app.services.auth_secret_box import AuthSecretBox

pytestmark = [
    allure.epic("Authentication & access"),
    allure.feature("Explicit Identity migration"),
    allure.story("022-FR-002/014/018/019; 022-SC-002/003/005"),
]

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)
DIGEST = "a" * 64


def _user(
    identifier: str = "user_owner", email: str = "owner@example.com"
) -> dict[str, Any]:
    return {
        "id": identifier,
        "email": email,
        "password_hash": "$argon2id$synthetic-preserved-hash",
        "created_at": (NOW - timedelta(days=30)).isoformat(),
        "display_name": "Synthetic owner",
        "deletion_requested_at": None,
        "legacy_preferences": {"nested": ["preserved", 3]},
    }


def _session(
    digest: str = DIGEST, *, owner: str = "user_owner", expired: bool = False
) -> dict[str, Any]:
    return {
        "token_hash": digest,
        "user_id": owner,
        "created_at": (NOW - timedelta(days=2)).isoformat(),
        "expires_at": (NOW + timedelta(days=-1 if expired else 20)).isoformat(),
        "legacy_client": {"version": "kept"},
    }


def _write(root: Path, relative: str, payload: object) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")


def _legacy(root: Path) -> None:
    _write(root, "users/user_owner.json", _user())
    _write(root, "users/_by_email.json", {"owner@example.com": "user_owner"})
    _write(root, f"sessions/{DIGEST}.json", _session())


def _migration(root: Path, *, secret_box: AuthSecretBox | None = None):
    from app.services.auth_migration import AuthMigration

    return AuthMigration(
        root, secret_box or AuthSecretBox({"v1": b"1" * 32}, "v1"), clock=lambda: NOW
    )


def test_022_fr002_import_preserves_identity_hash_session_and_unknown_fields(tmp_path):
    """Import preserves existing authority and unknown payload fields without claiming verification."""
    _legacy(tmp_path)
    _write(tmp_path, f"sessions/{'b' * 64}.json", _session("b" * 64, expired=True))
    _write(tmp_path, f"sessions/{'c' * 64}.json", _session("c" * 64, owner="orphan"))
    (tmp_path / "tasks.sqlite3").write_bytes(b"unrelated task fixture")
    result = _migration(tmp_path).migrate(writers_stopped=True)
    assert result.import_committed and result.cleanup_complete
    assert (
        result.users_imported,
        result.sessions_imported,
        result.sessions_revoked,
    ) == (1, 1, 2)
    store = AuthStore(tmp_path)
    user = UserRepository(tmp_path, store).get_by_id("user_owner")
    assert user.password_hash == _user()["password_hash"]
    assert user.auth_version == 0 and user.email_verified_at is None
    session = SessionRepository(tmp_path, store).get(DIGEST)
    assert session.user_id == user.id
    assert session.expires_at == datetime.fromisoformat(_session()["expires_at"])
    assert session.auth_method == "password"
    with store.connection() as connection:
        payload = json.loads(
            connection.execute("SELECT payload_json FROM users").fetchone()[0]
        )
        session_payload = json.loads(
            connection.execute("SELECT payload_json FROM sessions").fetchone()[0]
        )
    assert payload["legacy_preferences"] == _user()["legacy_preferences"]
    assert session_payload["legacy_client"] == _session()["legacy_client"]
    assert not list((tmp_path / "users").glob("*.json"))
    assert not list((tmp_path / "sessions").glob("*.json"))
    assert (tmp_path / "tasks.sqlite3").read_bytes() == b"unrelated task fixture"


def test_022_fr002_import_requires_stopped_writer_acknowledgement(tmp_path):
    """A file lock alone cannot authorize importing while legacy writers may run."""
    _legacy(tmp_path)
    with pytest.raises(RepositoryError, match="stopped"):
        _migration(tmp_path).migrate()
    assert not (tmp_path / "auth.sqlite3").exists()
    assert (tmp_path / "users/user_owner.json").exists()


@pytest.mark.parametrize(
    "phase,expected_email",
    [("prepared", "owner@example.com"), ("committed", "new@example.com")],
)
def test_022_fr002_journal_recovery_selects_validated_original_semantics(
    tmp_path, phase, expected_email
):
    """Prepared journals restore the old snapshot and committed journals select the new snapshot."""
    _legacy(tmp_path)
    old = _user()
    new = old | {"email": "new@example.com", "display_name": "Updated"}
    _write(tmp_path, "users/user_owner.json", new)
    _write(tmp_path, "users/_by_email.json", {"new@example.com": "user_owner"})
    _write(
        tmp_path,
        "users/_profile_transaction.json",
        {
            "phase": phase,
            "user_id": "user_owner",
            "old_user": old,
            "new_user": new,
            "old_index": {"owner@example.com": "user_owner"},
            "new_index": {"new@example.com": "user_owner"},
        },
    )
    _migration(tmp_path).migrate(writers_stopped=True)
    user = UserRepository(tmp_path).get_by_id("user_owner")
    assert user.email == expected_email
    assert user.email_verified_at is None


@pytest.mark.parametrize(
    "damage",
    [
        "malformed_user",
        "wrong_id",
        "duplicate_email",
        "divergent_index",
        "malformed_index",
        "wrong_hash",
        "naive_time",
        "bad_journal",
        "journal_other_owner",
        "unsafe_filename",
        "symlink",
    ],
)
def test_022_fr002_invalid_sources_abort_before_db_creation(tmp_path, damage):
    """Malformed, divergent or unsafe source credentials cannot create a new authority."""
    _legacy(tmp_path)
    if damage == "malformed_user":
        (tmp_path / "users/user_owner.json").write_text("{")
    elif damage == "wrong_id":
        _write(tmp_path, "users/user_owner.json", _user("another"))
    elif damage == "duplicate_email":
        _write(tmp_path, "users/another.json", _user("another", " OWNER@Example.com "))
    elif damage == "divergent_index":
        _write(tmp_path, "users/_by_email.json", {"wrong@example.com": "user_owner"})
    elif damage == "malformed_index":
        _write(tmp_path, "users/_by_email.json", [])
    elif damage == "wrong_hash":
        _write(tmp_path, f"sessions/{DIGEST}.json", _session("b" * 64))
    elif damage == "naive_time":
        _write(
            tmp_path,
            "users/user_owner.json",
            _user() | {"created_at": "2026-01-01T00:00:00"},
        )
    elif damage == "bad_journal":
        _write(tmp_path, "users/_profile_transaction.json", {"phase": "unknown"})
    elif damage == "journal_other_owner":
        _write(
            tmp_path,
            "users/_profile_transaction.json",
            {
                "phase": "prepared",
                "user_id": "user_owner",
                "old_user": _user("other"),
                "new_user": _user(),
                "old_index": {},
                "new_index": {"owner@example.com": "user_owner"},
            },
        )
    elif damage == "unsafe_filename":
        _write(tmp_path, "users/unexpected.txt", {})
    else:
        (tmp_path / "users/link.json").symlink_to(tmp_path / "users/user_owner.json")
    before = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    with pytest.raises(RepositoryError):
        _migration(tmp_path).migrate(writers_stopped=True)
    assert not (tmp_path / "auth.sqlite3").exists()
    for relative, content in before.items():
        assert (tmp_path / relative).read_bytes() == content


def test_022_fr018_backup_is_encrypted_restricted_and_expires_without_keys(tmp_path):
    """The temporary aggregate backup is protected and keyless expiry erases it."""
    _legacy(tmp_path)
    migration = _migration(tmp_path)
    migration.migrate(writers_stopped=True)
    backup = tmp_path / ".auth-migration-backup.enc"
    content = backup.read_bytes()
    assert b"owner@example.com" not in content
    assert b"argon2id" not in content
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    from app.services.auth_migration import AuthMigration

    later = AuthMigration(tmp_path, None, clock=lambda: NOW + timedelta(hours=24))
    assert later.cleanup_expired_backup()
    assert not backup.exists()


def test_022_fr018_purge_erases_backup_without_key_or_decryption(tmp_path):
    """Any account purge can erase the entire aggregate credential backup without keys."""
    _legacy(tmp_path)
    _migration(tmp_path).migrate(writers_stopped=True)
    from app.services.auth_migration import AuthMigration

    migration = AuthMigration(tmp_path, None, clock=lambda: NOW)
    assert migration.erase_backup()
    assert not migration.erase_backup()
    with AuthStore(tmp_path).connection() as connection:
        assert (
            connection.execute(
                "SELECT backup_path FROM auth_migration_ledger"
            ).fetchone()[0]
            is None
        )


def test_022_fr019_postcommit_cleanup_failure_resumes_without_source_reads(
    tmp_path, monkeypatch
):
    """After commit a crash resumes cleanup and cannot import source credentials again."""
    _legacy(tmp_path)
    migration = _migration(tmp_path)
    original = Path.unlink
    failed = False

    def interrupted(path: Path, *args, **kwargs):
        nonlocal failed
        if path.name == "user_owner.json" and not failed:
            failed = True
            raise OSError("synthetic cleanup interruption")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupted)
    with pytest.raises(RepositoryError):
        migration.migrate(writers_stopped=True)
    store = AuthStore(tmp_path, require_ready=False)
    with store.connection() as connection:
        ledger = connection.execute(
            "SELECT import_committed,cleanup_complete FROM auth_migration_ledger"
        ).fetchone()
    assert tuple(ledger) == (1, 0)
    with pytest.raises(RepositoryError, match="cleanup"):
        AuthStore(tmp_path)
    (tmp_path / "users/user_owner.json").write_text("not JSON anymore")
    monkeypatch.setattr(Path, "unlink", original)
    result = _migration(tmp_path).migrate()
    assert result.cleanup_complete
    assert UserRepository(tmp_path).get_by_id("user_owner").email == "owner@example.com"


def test_022_fr019_completed_import_never_resurrects_purged_user_from_source(tmp_path):
    """A committed ledger prevents every later migration call from resurrecting an account."""
    _legacy(tmp_path)
    migration = _migration(tmp_path)
    migration.migrate(writers_stopped=True)
    UserRepository(tmp_path).delete("user_owner")
    _legacy(tmp_path)
    result = migration.migrate(writers_stopped=True)
    assert result.import_committed
    assert UserRepository(tmp_path).list_users() == []
    assert SessionRepository(tmp_path).get(DIGEST) is None


def test_022_fr002_prepared_empty_db_retry_is_safe(tmp_path):
    """An empty uncommitted schema can retry the validated import safely."""
    _legacy(tmp_path)
    AuthStore(tmp_path, require_ready=False)
    result = _migration(tmp_path).migrate(writers_stopped=True)
    assert result.import_committed and result.cleanup_complete


@pytest.mark.parametrize("damage", ["payload", "indexed_email", "missing_session"])
def test_022_fr002_failed_import_verification_rolls_back_authority(
    tmp_path, monkeypatch, damage
):
    """Any measured row or indexed-authority mismatch aborts the entire import transaction."""
    _legacy(tmp_path)
    migration = _migration(tmp_path)
    verify = migration._verify_import

    def corrupt(connection, snapshot):
        if damage == "payload":
            connection.execute(
                "UPDATE users SET payload_json=json_set(payload_json,'$.display_name','tampered')"
            )
        elif damage == "indexed_email":
            connection.execute("UPDATE users SET email='tampered@example.com'")
        else:
            connection.execute("DELETE FROM sessions")
        verify(connection, snapshot)

    monkeypatch.setattr(migration, "_verify_import", corrupt)
    with pytest.raises(RepositoryError):
        migration.migrate(writers_stopped=True)
    store = AuthStore(tmp_path, require_ready=False)
    with store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT import_committed FROM auth_migration_ledger"
            ).fetchone()[0]
            == 0
        )
    assert (tmp_path / "users/user_owner.json").exists()


def test_022_fr018_unverified_backup_aborts_before_database_creation(
    tmp_path, monkeypatch
):
    """A backup that cannot decrypt to the measured original manifest cannot authorize import."""
    _legacy(tmp_path)
    secret_box = AuthSecretBox({"v1": b"1" * 32}, "v1")
    monkeypatch.setattr(
        secret_box, "open", lambda _envelope, _context: b"wrong manifest"
    )
    with pytest.raises(RepositoryError, match="backup"):
        _migration(tmp_path, secret_box=secret_box).migrate(writers_stopped=True)
    assert not (tmp_path / "auth.sqlite3").exists()
    assert (tmp_path / "users/user_owner.json").exists()


def test_022_fr002_missing_key_cannot_create_plaintext_fallback(tmp_path):
    """A missing backup key leaves original credential authority intact."""
    from app.services.auth_migration import AuthMigration

    _legacy(tmp_path)
    with pytest.raises(RepositoryError, match="encryption"):
        AuthMigration(tmp_path, None, clock=lambda: NOW).migrate(writers_stopped=True)
    assert not (tmp_path / "auth.sqlite3").exists()
    assert not (tmp_path / ".auth-migration-backup.enc").exists()


def test_022_fr002_migration_lock_excludes_another_process_handle(tmp_path):
    """A second migration cannot proceed while an independent file handle owns the lock."""
    _legacy(tmp_path)
    with (tmp_path / ".auth-migration.lock").open("wb") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RepositoryError):
            _migration(tmp_path).migrate(writers_stopped=True)
    assert not (tmp_path / "auth.sqlite3").exists()


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_022_fr019_committed_resume_uses_no_backup_or_source_credentials(
    tmp_path, damage
):
    """Missing or corrupt backups cannot roll back or block the committed account authority."""
    from app.services.auth_migration import AuthMigration

    _legacy(tmp_path)
    _migration(tmp_path).migrate(writers_stopped=True)
    backup = tmp_path / ".auth-migration-backup.enc"
    if damage == "missing":
        backup.unlink()
    else:
        backup.write_bytes(b"corrupt encrypted backup fixture")
    result = AuthMigration(tmp_path, None, clock=lambda: NOW).resume_cleanup()
    assert result.import_committed and result.cleanup_complete
    assert (
        UserRepository(tmp_path).get_by_id("user_owner").password_hash
        == _user()["password_hash"]
    )
    assert not backup.exists()


def test_022_fr002_duplicate_json_keys_are_rejected_before_import(tmp_path):
    """A repeated index key cannot silently hide a conflicting address claim."""
    _legacy(tmp_path)
    (tmp_path / "users/_by_email.json").write_text(
        '{"owner@example.com":"other","owner@example.com":"user_owner"}'
    )
    with pytest.raises(RepositoryError):
        _migration(tmp_path).migrate(writers_stopped=True)
    assert not (tmp_path / "auth.sqlite3").exists()


def test_022_fr002_journal_cannot_rebind_unrelated_index_entries(tmp_path):
    """Both journal states must match independently reconstructed unrelated accounts."""
    _legacy(tmp_path)
    _write(tmp_path, "users/another.json", _user("another", "another@example.com"))
    _write(
        tmp_path,
        "users/_by_email.json",
        {"owner@example.com": "user_owner", "another@example.com": "another"},
    )
    _write(
        tmp_path,
        "users/_profile_transaction.json",
        {
            "phase": "prepared",
            "user_id": "user_owner",
            "old_user": _user(),
            "new_user": _user(),
            "old_index": {
                "owner@example.com": "user_owner",
                "another@example.com": "user_owner",
            },
            "new_index": {
                "owner@example.com": "user_owner",
                "another@example.com": "another",
            },
        },
    )
    with pytest.raises(RepositoryError):
        _migration(tmp_path).migrate(writers_stopped=True)
    assert not (tmp_path / "auth.sqlite3").exists()


def test_022_fr002_prepared_db_with_modern_attempt_is_not_an_empty_retry(tmp_path):
    """Legacy import cannot mix authority with an existing modern login attempt."""
    _legacy(tmp_path)
    store = AuthStore(tmp_path, require_ready=False)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO auth_attempts(id,provider,intent,channel,client_challenge,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
            (
                "already_started",
                "google",
                "login",
                "web",
                "client_digest",
                NOW.isoformat(),
                (NOW + timedelta(minutes=10)).isoformat(),
            ),
        )
    with pytest.raises(RepositoryError, match="authority"):
        _migration(tmp_path).migrate(writers_stopped=True)
    with store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        assert (
            connection.execute("SELECT count(*) FROM auth_attempts").fetchone()[0] == 1
        )
        assert (
            connection.execute(
                "SELECT import_committed FROM auth_migration_ledger"
            ).fetchone()[0]
            == 0
        )
