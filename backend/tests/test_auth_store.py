"""Real SQLite authority and legacy facade contract tests for modern auth."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from typing import TYPE_CHECKING

import allure
import pytest
from pydantic import ValidationError

from app.exceptions import ConflictError, NotFoundError, RepositoryError
from app.repositories.session import SessionRepository
from app.repositories.user import UserRepository
from app.schemas.auth import Session, User
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.repositories.auth_store import AuthStore

pytestmark = [
    allure.epic("Authentication & access"),
    allure.feature("Transactional Identity storage"),
    allure.story("022-FR-002/004/014/018/019; 022-SC-002/003/005"),
]


def _user(identifier: str = "owner", email: str = "owner@example.com") -> User:
    return User(id=identifier, email=email, password_hash="hash", created_at=utcnow())


def _session(user_id: str = "owner", token_hash: str | None = None) -> Session:
    now = utcnow()
    return Session(
        token_hash=token_hash or "digest",
        user_id=user_id,
        created_at=now,
        expires_at=now + timedelta(days=1),
    )


def _store(root: Path) -> AuthStore:
    from app.repositories.auth_store import AuthStore

    return AuthStore(root)


def test_022_fr002_empty_root_sqlite_preserves_legacy_facade_results(tmp_path):
    """Users and sessions round trip without creating credential JSON files."""
    users = UserRepository(tmp_path)
    sessions = SessionRepository(tmp_path)
    created = users.create(_user(email="  OWNER@Example.com "))
    session = _session()
    sessions.create(session)
    assert created.email == "owner@example.com"
    assert users.get_by_email(" OWNER@example.com ") == created
    assert sessions.get("digest") == session
    assert (tmp_path / "auth.sqlite3").is_file()
    assert not list(tmp_path.rglob("*.json"))


def test_022_fr002_store_pragmas_and_nested_transaction_rollback(tmp_path):
    """Nested facade writes reuse one connection and roll back together."""
    store = _store(tmp_path)
    users = UserRepository(tmp_path, store)
    sessions = SessionRepository(tmp_path, store)
    with store.connection() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA secure_delete").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
    with (
        pytest.raises(RuntimeError, match="abort authority"),
        store.transaction() as outer,
    ):
        users.create(_user())
        with store.transaction() as nested, store.connection() as current:
            assert outer is nested is current
            sessions.create(_session())
        raise RuntimeError("abort authority")
    assert users.get_by_id("owner") is None
    assert sessions.get("digest") is None


def test_022_fr004_two_stores_enforce_normalized_email_unique_claim(tmp_path):
    """Independent SQLite writers cannot claim the same normalized address."""
    stores = [_store(tmp_path), _store(tmp_path)]
    barrier = Barrier(2)

    def claim(index: int) -> str:
        repository = UserRepository(tmp_path, stores[index])
        barrier.wait(timeout=10)
        try:
            repository.create(_user(f"owner_{index}", " SAME@Example.com "))
        except ConflictError:
            return "conflict"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(claim, range(2)))
    assert sorted(outcomes) == ["conflict", "created"]
    assert len(UserRepository(tmp_path, stores[0]).list_users()) == 1


def test_022_fr019_stale_save_and_mutation_cannot_resurrect_deleted_user(tmp_path):
    """A stale model cannot re-create an account after another writer purges it."""
    first = UserRepository(tmp_path, _store(tmp_path))
    second = UserRepository(tmp_path, _store(tmp_path))
    stale = first.create(_user())
    second.delete(stale.id)
    with pytest.raises(NotFoundError):
        first.save(stale)
    with pytest.raises(NotFoundError):
        first.mutate(stale.id, lambda user: user)
    assert first.list_users() == []


def test_022_fr014_fresh_mutations_preserve_other_writers_and_immutable_id(tmp_path):
    """Fresh mutations preserve deletion markers and reject account-ID changes."""
    first = UserRepository(tmp_path, _store(tmp_path))
    second = UserRepository(tmp_path, _store(tmp_path))
    first.create(_user())
    requested = utcnow()
    second.mutate(
        "owner",
        lambda user: user.model_copy(update={"deletion_requested_at": requested}),
    )
    first.mutate("owner", lambda user: user.model_copy(update={"display_name": "New"}))
    assert first.get_by_id("owner").deletion_requested_at == requested
    with pytest.raises(ConflictError):
        first.mutate("owner", lambda user: user.model_copy(update={"id": "intruder"}))
    assert first.get_by_id("intruder") is None


def test_022_fr014_email_changes_invalidate_verification_and_advance_version(tmp_path):
    """Legacy profile and email changes cannot retain old mailbox authority."""
    users = UserRepository(tmp_path)
    verified = users.create(_user().model_copy(update={"email_verified_at": utcnow()}))
    named = users.update_profile(verified.id, email=verified.email, display_name="Name")
    assert named.email_verified_at == verified.email_verified_at
    assert named.auth_version == verified.auth_version
    changed = users.update_email(verified.id, " NEW@example.com ")
    assert changed.email == "new@example.com"
    assert changed.email_verified_at is None
    assert changed.auth_version == verified.auth_version + 1
    assert users.get_by_email(verified.email) is None


def test_022_fr014_unknown_raw_fields_survive_every_user_mutation(tmp_path):
    """Unmodelled legacy payload fields survive saves, profile edits and mutations."""
    store = _store(tmp_path)
    users = UserRepository(tmp_path, store)
    user = users.create(_user())
    unknown = {"legacy_preferences": {"nested": [1, "kept"]}}
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT payload_json FROM users WHERE id=?", (user.id,)
        ).fetchone()
        payload = json.loads(row[0]) | unknown
        connection.execute(
            "UPDATE users SET payload_json=? WHERE id=?", (json.dumps(payload), user.id)
        )
    users.save(user.model_copy(update={"display_name": "Saved"}))
    users.mutate(
        user.id, lambda current: current.model_copy(update={"display_name": "Mutated"})
    )
    users.update_profile(user.id, email="profile@example.com", display_name="Profile")
    users.update_email(user.id, "final@example.com")
    with store.connection() as connection:
        row = connection.execute(
            "SELECT email,auth_version,payload_json FROM users WHERE id=?", (user.id,)
        ).fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["legacy_preferences"] == unknown["legacy_preferences"]
    assert payload["id"] == user.id
    assert payload["email"] == row["email"] == "final@example.com"
    assert payload["auth_version"] == row["auth_version"] == 2


def test_022_fr002_existing_db_never_reads_or_writes_legacy_json(tmp_path):
    """An authoritative DB never falls back to a newly planted JSON record."""
    users = UserRepository(tmp_path)
    users.create(_user())
    users.users_dir.mkdir(exist_ok=True)
    users._user_path("ghost").write_text(
        json.dumps(_user("ghost", "ghost@example.com").model_dump(mode="json"))
    )
    users.index_path.write_text("malformed legacy index")
    assert users.get_by_id("ghost") is None
    assert users.get_by_email("ghost@example.com") is None
    users.update_email("owner", "changed@example.com")
    assert users.index_path.read_text() == "malformed legacy index"
    users.delete("owner")
    assert users._user_path("ghost").exists()


def test_022_fr002_nonempty_unmigrated_root_fails_without_creating_db(tmp_path):
    """Ordinary startup refuses legacy credentials until explicit migration."""
    legacy = tmp_path / "users"
    legacy.mkdir()
    (legacy / "owner.json").write_text(json.dumps(_user().model_dump(mode="json")))
    with pytest.raises(RepositoryError, match="migrat"):
        UserRepository(tmp_path)
    assert not (tmp_path / "auth.sqlite3").exists()


def test_022_fr018_user_delete_cascades_sessions_and_owned_metadata(tmp_path):
    """Deleting an account removes its sessions and owned authentication proofs."""
    store = _store(tmp_path)
    users = UserRepository(tmp_path, store)
    sessions = SessionRepository(tmp_path, store)
    users.create(_user())
    sessions.create(_session())
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO auth_proofs(digest,user_id,purpose,auth_version,created_at,expires_at) VALUES(?,?,?,?,?,?)",
            (
                "proof_digest",
                "owner",
                "reauth",
                0,
                utcnow().isoformat(),
                (utcnow() + timedelta(minutes=5)).isoformat(),
            ),
        )
    users.delete("owner")
    users.delete("owner")
    assert sessions.get("digest") is None
    with store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM auth_proofs").fetchone()[0] == 0


def test_022_fr002_sessions_require_owner_and_revoke_only_matching_rows(tmp_path):
    """Foreign keys require a real owner and bulk revocation preserves its keep token."""
    store = _store(tmp_path)
    users = UserRepository(tmp_path, store)
    sessions = SessionRepository(tmp_path, store)
    with pytest.raises(ConflictError):
        sessions.create(_session("missing"))
    users.create(_user())
    users.create(_user("other", "other@example.com"))
    for owner, digest in [("owner", "keep"), ("owner", "revoke"), ("other", "other")]:
        sessions.create(_session(owner, digest))
    assert sessions.delete_all_for_user("owner", keep="keep") == 1
    assert sessions.get("keep") is not None
    assert sessions.get("revoke") is None
    assert sessions.get("other") is not None
    expired = _session("owner", "expired").model_copy(
        update={"expires_at": utcnow() - timedelta(seconds=1)}
    )
    sessions.create(expired)
    assert sessions.get("expired") is None
    with store.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM sessions WHERE token_hash='expired'"
            ).fetchone()[0]
            == 0
        )


def test_022_fr002_corrupt_existing_database_has_no_json_fallback(tmp_path):
    """An unreadable authoritative SQLite database fails visibly."""
    (tmp_path / "auth.sqlite3").write_bytes(b"not a sqlite database")
    with pytest.raises((RepositoryError, sqlite3.DatabaseError)):
        UserRepository(tmp_path)


def test_022_fr004_two_connections_consume_proof_once(tmp_path):
    """Two independent authority transactions consume a proof only once."""
    stores = [_store(tmp_path), _store(tmp_path)]
    UserRepository(tmp_path, stores[0]).create(_user())
    now = utcnow()
    with stores[0].transaction() as connection:
        connection.execute(
            "INSERT INTO auth_proofs(digest,user_id,purpose,auth_version,created_at,expires_at) VALUES(?,?,?,?,?,?)",
            (
                "once",
                "owner",
                "reauth",
                0,
                now.isoformat(),
                (now + timedelta(minutes=5)).isoformat(),
            ),
        )
    barrier = Barrier(2)

    def consume(index: int) -> int:
        barrier.wait(timeout=10)
        with stores[index].transaction() as connection:
            return connection.execute(
                "UPDATE auth_proofs SET consumed_at=? WHERE digest=? AND consumed_at IS NULL",
                (utcnow().isoformat(), "once"),
            ).rowcount

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(consume, range(2))) == [0, 1]


def test_022_fr012_conflicting_profile_update_rolls_back_all_fields(tmp_path):
    """A conflicting normalized address cannot partially commit the profile."""
    users = UserRepository(tmp_path)
    original = users.create(_user())
    users.create(_user("other", "other@example.com"))
    with pytest.raises(ConflictError):
        users.update_profile("owner", email=" OTHER@Example.com ", display_name="Lost")
    assert users.get_by_id("owner") == original
    assert users.get_by_email(original.email) == original


def test_022_fr019_stale_credential_save_cannot_rewind_authority(tmp_path):
    """A stale full-record save cannot undo a concurrent credential mutation."""
    first = UserRepository(tmp_path, _store(tmp_path))
    second = UserRepository(tmp_path, _store(tmp_path))
    stale = first.create(_user())
    fresh = second.mutate(
        "owner", lambda user: user.model_copy(update={"password_hash": "new hash"})
    )
    assert fresh.auth_version == stale.auth_version + 1
    with pytest.raises(ConflictError):
        first.save(stale.model_copy(update={"display_name": "Stale"}))
    assert first.get_by_id("owner").password_hash == "new hash"


def test_022_fr018_metadata_cleanup_is_bounded_and_erases_expired_secrets(tmp_path):
    """Short-lived metadata cleanup bounds work and removes expired sealed payloads."""
    from app.repositories.auth_metadata import AuthMetadataRepository

    store = _store(tmp_path)
    metadata = AuthMetadataRepository(tmp_path, store)
    now = utcnow()
    expired = (now - timedelta(seconds=1)).isoformat()
    active = (now + timedelta(minutes=5)).isoformat()
    with store.transaction() as connection:
        for identifier, expiry in [
            ("expired_a", expired),
            ("expired_b", expired),
            ("active", active),
        ]:
            connection.execute(
                "INSERT INTO auth_attempts(id,provider,intent,channel,client_challenge,created_at,expires_at,sealed_payload,key_id) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    "google",
                    "login",
                    "web",
                    "client_s256",
                    now.isoformat(),
                    expiry,
                    "sealed fixture",
                    "v1",
                ),
            )
    assert metadata.cleanup_expired(now=now, limit=1) == 1
    with store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM auth_attempts").fetchone()[0] == 2
        )
    assert metadata.cleanup_expired(now=now, limit=1) == 1
    with store.connection() as connection:
        assert (
            connection.execute("SELECT id FROM auth_attempts").fetchone()[0] == "active"
        )


def test_022_fr014_passwordless_defaults_do_not_invent_verified_authority():
    """Passwordless users start without a credential, verification or authority version."""
    user = User(id="passwordless", email="new@example.com", created_at=utcnow())
    assert user.password_hash == ""
    assert user.email_verified_at is None
    assert user.auth_version == 0
    session = _session()
    assert session.auth_method == "password"
    assert session.provider_binding_id is None
    assert session.auth_version == 0
    with pytest.raises(ValidationError):
        User.model_validate(user.model_dump() | {"auth_version": -1})


def test_022_fr002_session_refresh_preserves_unknown_fields_and_owner(tmp_path):
    """Legacy session refresh preserves unmodelled fields and cannot transfer ownership."""
    store = _store(tmp_path)
    users = UserRepository(tmp_path, store)
    sessions = SessionRepository(tmp_path, store)
    users.create(_user())
    users.create(_user("other", "other@example.com"))
    original = _session()
    sessions.create(original)
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT payload_json FROM sessions WHERE token_hash=?",
            (original.token_hash,),
        ).fetchone()
        payload = json.loads(row[0]) | {"legacy_device": {"name": "preserved"}}
        connection.execute(
            "UPDATE sessions SET payload_json=? WHERE token_hash=?",
            (json.dumps(payload), original.token_hash),
        )
    updated = original.model_copy(
        update={"expires_at": original.expires_at + timedelta(days=1)}
    )
    sessions.create(updated)
    with store.connection() as connection:
        payload = json.loads(
            connection.execute(
                "SELECT payload_json FROM sessions WHERE token_hash=?",
                (original.token_hash,),
            ).fetchone()[0]
        )
    assert payload["legacy_device"] == {"name": "preserved"}
    assert sessions.get(original.token_hash) == updated
    with pytest.raises(ConflictError):
        sessions.create(updated.model_copy(update={"user_id": "other"}))
    assert sessions.get(original.token_hash).user_id == "owner"


def test_022_fr018_cleanup_inside_outer_transaction_reuses_authority(tmp_path):
    """Metadata cleanup can join an enclosing authority transaction and roll back."""
    from app.repositories.auth_metadata import AuthMetadataRepository

    store = _store(tmp_path)
    metadata = AuthMetadataRepository(tmp_path, store)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO auth_budgets(scope,fingerprint,key_id,window_started_at,expires_at) VALUES(?,?,?,?,?)",
            (
                "send_address",
                "fingerprint",
                "v1",
                utcnow().isoformat(),
                (utcnow() - timedelta(seconds=1)).isoformat(),
            ),
        )
    with pytest.raises(RuntimeError, match="abort cleanup"), store.transaction():
        assert metadata.cleanup_expired(now=utcnow()) == 1
        raise RuntimeError("abort cleanup")
    with store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM auth_budgets").fetchone()[0] == 1
        )
