"""Explicit stopped-writer import and irreversible Identity cleanup checkpoints.

The migration lock serializes this tool and backup erasure. Legacy binaries do
not honor it: an operator must stop every legacy writer before acknowledging
the import prerequisite. Committed imports never read source credential content.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import EmailStr, TypeAdapter

from app.exceptions import RepositoryError
from app.repositories.auth_store import AUTH_SCHEMA_EPOCH, AuthStore
from app.repositories.user import UserRepository
from app.schemas.auth import Session, User
from app.services.auth_secret_box import AuthSecretBox, SecretContext
from app.utils.time import utcnow

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_INDEX = "_by_email.json"
_JOURNAL = "_profile_transaction.json"
_BACKUP = ".auth-migration-backup.enc"
_LOCK = ".auth-migration.lock"
_MAX_BACKUP_AGE = timedelta(hours=24)
_EMAIL = TypeAdapter(EmailStr)
_SOURCE_ERROR = "Authentication migration source validation failed."


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryError(_SOURCE_ERROR)
        result[key] = value
    return result


def _json(content: bytes) -> Any:
    return json.loads(
        content, object_pairs_hook=_object, parse_constant=lambda _value: _invalid()
    )


def _invalid() -> Any:
    raise RepositoryError(_SOURCE_ERROR)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise RepositoryError(_SOURCE_ERROR)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RepositoryError(_SOURCE_ERROR)
    return parsed.astimezone(UTC)


def _identifier(value: object) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise RepositoryError(_SOURCE_ERROR)
    return value


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Only nonsecret checkpoints and measured aggregate counts leave the tool."""

    schema_epoch: int
    import_committed: bool
    cleanup_complete: bool
    users_imported: int
    sessions_imported: int
    sessions_revoked: int


@dataclass(frozen=True, slots=True)
class _Snapshot:
    users: list[dict[str, Any]]
    sessions: list[dict[str, Any]]
    sources: dict[str, bytes]
    counts: dict[str, int]

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            _canonical({"users": self.users, "sessions": self.sessions})
        ).hexdigest()


class AuthMigration:
    """Validate, protect, import once, then finish cleanup independently of keys."""

    def __init__(
        self,
        root: Path,
        secret_box: AuthSecretBox | None,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.root = root
        self.secret_box = secret_box
        self.clock = clock
        self.backup_path = root / _BACKUP

    @contextmanager
    def _locked(self) -> Iterator[None]:
        descriptor: int | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                self.root / _LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
            )
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        except OSError, ValueError, sqlite3.Error:
            # Validation exceptions may contain private source input; expose only
            # the coarse checkpoint failure, including when logged with a traceback.
            raise RepositoryError(
                "Authentication migration operation failed."
            ) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _ledger(self) -> dict[str, Any] | None:
        database = self.root / "auth.sqlite3"
        if database.is_symlink():
            raise RepositoryError("Invalid authentication migration database.")
        if not database.exists():
            return None
        if not database.is_file():
            raise RepositoryError("Invalid authentication migration database.")
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT * FROM auth_migration_ledger WHERE id=1"
            ).fetchone()
            if row is None or row["schema_epoch"] != AUTH_SCHEMA_EPOCH:
                raise RepositoryError("Unsupported authentication migration epoch.")
            return dict(row)
        finally:
            connection.close()

    def _inventory(self) -> list[Path]:
        paths: list[Path] = []
        for name in ("users", "sessions"):
            directory = self.root / name
            if directory.is_symlink():
                raise RepositoryError(_SOURCE_ERROR)
            if not directory.exists():
                continue
            if not directory.is_dir():
                raise RepositoryError(_SOURCE_ERROR)
            for path in sorted(directory.iterdir()):
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise RepositoryError(_SOURCE_ERROR)
                if name == "users" and path.name in {_INDEX, _JOURNAL}:
                    paths.append(path)
                    continue
                pattern = _ID if name == "users" else _HASH
                if path.suffix != ".json" or pattern.fullmatch(path.stem) is None:
                    raise RepositoryError(_SOURCE_ERROR)
                paths.append(path)
        return paths

    @staticmethod
    def _user(payload: object, identifier: str) -> dict[str, Any]:
        if not isinstance(payload, dict) or not {
            "id",
            "email",
            "password_hash",
            "created_at",
        }.issubset(payload):
            raise RepositoryError(_SOURCE_ERROR)
        if (
            _identifier(payload["id"]) != identifier
            or not isinstance(payload["email"], str)
            or not isinstance(payload["password_hash"], str)
        ):
            raise RepositoryError(_SOURCE_ERROR)
        email = UserRepository.normalize_email(payload["email"])
        _EMAIL.validate_python(email)
        _timestamp(payload["created_at"])
        if payload.get("deletion_requested_at") is not None:
            _timestamp(payload["deletion_requested_at"])
        user = User.model_validate(
            payload | {"email": email, "email_verified_at": None, "auth_version": 0}
        )
        return dict(payload) | user.model_dump(mode="json")

    @staticmethod
    def _index(payload: object) -> dict[str, str]:
        if not isinstance(payload, dict):
            raise RepositoryError(_SOURCE_ERROR)
        result: dict[str, str] = {}
        for email, identifier in payload.items():
            if not isinstance(email, str) or email != UserRepository.normalize_email(
                email
            ):
                raise RepositoryError(_SOURCE_ERROR)
            _EMAIL.validate_python(email)
            result[email] = _identifier(identifier)
        return result

    @staticmethod
    def _reconstructed(users: dict[str, dict[str, Any]]) -> dict[str, str]:
        result: dict[str, str] = {}
        for identifier, payload in users.items():
            email = payload["email"]
            if email in result:
                raise RepositoryError(_SOURCE_ERROR)
            result[email] = identifier
        return result

    def _recover_journal(
        self,
        users: dict[str, dict[str, Any]],
        journal: object,
        actual_index: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        fields = {"phase", "user_id", "old_user", "new_user", "old_index", "new_index"}
        if (
            not isinstance(journal, dict)
            or set(journal) != fields
            or not isinstance(journal["phase"], str)
            or journal["phase"] not in {"prepared", "committed"}
        ):
            raise RepositoryError(_SOURCE_ERROR)
        identifier = _identifier(journal["user_id"])
        other = {key: value for key, value in users.items() if key != identifier}
        states: list[dict[str, dict[str, Any]]] = []
        indexes: list[dict[str, str]] = []
        for label in ("old", "new"):
            raw = journal[f"{label}_user"]
            state = dict(other)
            if raw is not None:
                state[identifier] = self._user(raw, identifier)
            index = self._index(journal[f"{label}_index"])
            if index != self._reconstructed(state):
                raise RepositoryError(_SOURCE_ERROR)
            states.append(state)
            indexes.append(index)
        if actual_index not in indexes:
            raise RepositoryError(_SOURCE_ERROR)
        current = users.get(identifier)
        known = set(User.model_fields)
        if not any(
            current is None
            and state.get(identifier) is None
            or current is not None
            and state.get(identifier) is not None
            and {key: current.get(key) for key in known}
            == {key: state[identifier].get(key) for key in known}
            for state in states
        ):
            raise RepositoryError(_SOURCE_ERROR)
        selected = states[int(journal["phase"] == "committed")]
        if current is not None and identifier in selected:
            selected[identifier] = current | selected[identifier]
        return selected

    def _snapshot(self) -> _Snapshot:
        sources = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self._inventory()
        }
        users: dict[str, dict[str, Any]] = {}
        for name, content in sources.items():
            path = Path(name)
            if path.parent.name == "users" and path.name not in {_INDEX, _JOURNAL}:
                users[path.stem] = self._user(_json(content), path.stem)
        index = self._index(_json(sources.get(f"users/{_INDEX}", b"{}")))
        if (journal := sources.get(f"users/{_JOURNAL}")) is not None:
            users = self._recover_journal(users, _json(journal), index)
        elif index != self._reconstructed(users):
            raise RepositoryError(_SOURCE_ERROR)
        sessions: list[dict[str, Any]] = []
        revoked = 0
        source_sessions = 0
        now = self.clock()
        for name, content in sources.items():
            path = Path(name)
            if path.parent.name != "sessions":
                continue
            source_sessions += 1
            payload = _json(content)
            if not isinstance(payload, dict) or payload.get("token_hash") != path.stem:
                raise RepositoryError(_SOURCE_ERROR)
            _identifier(payload.get("user_id"))
            created = _timestamp(payload.get("created_at"))
            expires = _timestamp(payload.get("expires_at"))
            if expires <= created:
                raise RepositoryError(_SOURCE_ERROR)
            session = Session.model_validate(
                payload
                | {
                    "auth_version": 0,
                    "auth_method": "password",
                    "provider_binding_id": None,
                    "confirmed_at": None,
                }
            )
            if expires <= now or session.user_id not in users:
                revoked += 1
            else:
                sessions.append(payload | session.model_dump(mode="json"))
        counts = {
            "users_imported": len(users),
            "sessions_imported": len(sessions),
            "sessions_revoked": revoked,
            "source_user_files": sum(
                name.startswith("users/") and Path(name).name not in {_INDEX, _JOURNAL}
                for name in sources
            ),
            "source_session_files": source_sessions,
        }
        return _Snapshot(
            [users[key] for key in sorted(users)],
            sorted(sessions, key=lambda item: item["token_hash"]),
            sources,
            counts,
        )

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_backup(self, snapshot: _Snapshot, now: datetime) -> datetime:
        if self.secret_box is None:
            raise RepositoryError("Configured authentication encryption is required.")
        expiry = now + _MAX_BACKUP_AGE
        manifest = {
            "schema_epoch": AUTH_SCHEMA_EPOCH,
            "created_at": now.isoformat(),
            "expires_at": expiry.isoformat(),
            "counts": snapshot.counts,
            "validation_digest": snapshot.digest,
            "files": {
                name: {
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "content": base64.b64encode(content).decode("ascii"),
                }
                for name, content in snapshot.sources.items()
            },
        }
        plaintext = _canonical(manifest)
        context = SecretContext(
            kind="migration_backup",
            attempt_id=snapshot.digest,
            generation=AUTH_SCHEMA_EPOCH,
        )
        envelope = {
            "schema_epoch": AUTH_SCHEMA_EPOCH,
            "created_at": now.isoformat(),
            "expires_at": expiry.isoformat(),
            "key_id": self.secret_box.current_key_id,
            "validation_digest": snapshot.digest,
            "sealed_payload": self.secret_box.seal(plaintext, context),
        }
        descriptor = os.open(
            self.backup_path,
            os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(_canonical(envelope))
            output.flush()
            os.fsync(output.fileno())
        self._sync_directory(self.root)
        measured = _json(self.backup_path.read_bytes())
        if (
            measured != envelope
            or self.secret_box.open(measured["sealed_payload"], context) != plaintext
        ):
            raise RepositoryError(
                "Authentication migration backup verification failed."
            )
        return expiry

    def _verify_import(
        self, connection: sqlite3.Connection, snapshot: _Snapshot
    ) -> None:
        user_rows = connection.execute("SELECT * FROM users ORDER BY id").fetchall()
        session_rows = connection.execute(
            "SELECT * FROM sessions ORDER BY token_hash"
        ).fetchall()
        users = [json.loads(row["payload_json"]) for row in user_rows]
        sessions = [json.loads(row["payload_json"]) for row in session_rows]
        user_columns = (
            "id",
            "email",
            "password_hash",
            "email_verified_at",
            "auth_version",
            "created_at",
            "deletion_requested_at",
        )
        session_columns = (
            "token_hash",
            "user_id",
            "created_at",
            "expires_at",
            "auth_version",
            "auth_method",
            "confirmed_at",
            "provider_binding_id",
        )
        for rows, payloads, columns in (
            (user_rows, users, user_columns),
            (session_rows, sessions, session_columns),
        ):
            for row, payload in zip(rows, payloads, strict=True):
                if any(row[column] != payload.get(column) for column in columns):
                    raise RepositoryError(
                        "Authentication migration indexed authority verification failed."
                    )
        measured = hashlib.sha256(
            _canonical({"users": users, "sessions": sessions})
        ).hexdigest()
        if (
            measured != snapshot.digest
            or len(users) != snapshot.counts["users_imported"]
            or len(sessions) != snapshot.counts["sessions_imported"]
        ):
            raise RepositoryError(
                "Authentication migration import verification failed."
            )
        if (
            connection.execute("PRAGMA foreign_key_check").fetchone() is not None
            or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
        ):
            raise RepositoryError(
                "Authentication migration integrity verification failed."
            )

    def _import(
        self, store: AuthStore, snapshot: _Snapshot, expiry: datetime, now: datetime
    ) -> None:
        with store.transaction() as connection:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name<>'auth_migration_ledger' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            for table in tables:
                # Quote names from the owned DB schema as identifiers, never SQL.
                identifier = '"' + table["name"].replace('"', '""') + '"'
                if connection.execute(
                    f"SELECT EXISTS(SELECT 1 FROM {identifier})"  # noqa: S608
                ).fetchone()[0]:
                    raise RepositoryError(
                        "Authentication store already contains authority."
                    )
            for payload in snapshot.users:
                connection.execute(
                    "INSERT INTO users(email,password_hash,email_verified_at,auth_version,created_at,deletion_requested_at,payload_json,id) VALUES(?,?,?,?,?,?,?,?)",
                    UserRepository._values(User.model_validate(payload), payload),
                )
            for payload in snapshot.sessions:
                connection.execute(
                    "INSERT INTO sessions(token_hash,user_id,created_at,expires_at,auth_version,auth_method,confirmed_at,provider_binding_id,payload_json) VALUES(?,?,?,?,0,'password',NULL,NULL,?)",
                    (
                        payload["token_hash"],
                        payload["user_id"],
                        payload["created_at"],
                        payload["expires_at"],
                        _canonical(payload).decode("ascii"),
                    ),
                )
            self._verify_import(connection, snapshot)
            connection.execute(
                "UPDATE auth_migration_ledger SET import_committed=1,cleanup_complete=0,imported_at=?,counts_json=?,validation_digest=?,backup_path=?,backup_expires_at=? WHERE id=1",
                (
                    now.isoformat(),
                    _canonical(snapshot.counts).decode("ascii"),
                    snapshot.digest,
                    _BACKUP,
                    expiry.isoformat(),
                ),
            )

    def _cleanup_sources(self, store: AuthStore) -> None:
        with store.transaction() as connection:
            connection.execute(
                "UPDATE auth_migration_ledger SET cleanup_complete=0 WHERE id=1"
            )
        for path in self._inventory():
            path.unlink(missing_ok=True)
        if self._inventory():
            raise RepositoryError("Authentication migration cleanup is incomplete.")
        for name in ("users", "sessions"):
            directory = self.root / name
            if directory.exists():
                self._sync_directory(directory)
        with store.transaction() as connection:
            connection.execute(
                "UPDATE auth_migration_ledger SET cleanup_complete=1,cleanup_completed_at=? WHERE id=1",
                (self.clock().isoformat(),),
            )
        store.checkpoint()

    @staticmethod
    def _result(ledger: dict[str, Any]) -> MigrationResult:
        counts = json.loads(ledger["counts_json"])
        values = [
            counts.get(name, 0)
            for name in ("users_imported", "sessions_imported", "sessions_revoked")
        ]
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in values
        ):
            raise RepositoryError("Invalid authentication migration counts.")
        return MigrationResult(
            AUTH_SCHEMA_EPOCH,
            bool(ledger["import_committed"]),
            bool(ledger["cleanup_complete"]),
            *values,
        )

    def migrate(self, *, writers_stopped: bool = False) -> MigrationResult:
        """Import only with explicit acknowledgement; committed retries only clean up."""
        with self._locked():
            ledger = self._ledger()
            if ledger is None or not ledger["import_committed"]:
                if not writers_stopped:
                    raise RepositoryError(
                        "Every legacy authentication writer must be stopped."
                    )
                snapshot = self._snapshot()
                now = self.clock()
                expiry = self._write_backup(snapshot, now)
                # Check the measured source snapshot again before creating authority.
                if {
                    str(path.relative_to(self.root)): path.read_bytes()
                    for path in self._inventory()
                } != snapshot.sources:
                    raise RepositoryError("Authentication migration sources changed.")
                store = AuthStore(self.root, require_ready=False)
                self._import(store, snapshot, expiry, now)
            else:
                store = AuthStore(self.root, require_ready=False)
            self._cleanup_sources(store)
            self._cleanup_expired_backup()
            complete = self._ledger()
            if complete is None:
                raise RepositoryError("Authentication migration ledger is missing.")
            return self._result(complete)

    def resume_cleanup(self) -> MigrationResult | None:
        """Startup may finish an already committed import without keys or source reads."""
        with self._locked():
            ledger = self._ledger()
            if ledger is None or not ledger["import_committed"]:
                return None
            store = AuthStore(self.root, require_ready=False)
            self._cleanup_sources(store)
            self._cleanup_expired_backup()
            complete = self._ledger()
            if complete is None:
                raise RepositoryError("Authentication migration ledger is missing.")
            return self._result(complete)

    def _erase_backup(self) -> bool:
        exists = self.backup_path.exists() or self.backup_path.is_symlink()
        self.backup_path.unlink(missing_ok=True)
        if exists:
            self._sync_directory(self.root)
        if self._ledger() is not None:
            store = AuthStore(self.root, require_ready=False)
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE auth_migration_ledger SET backup_path=NULL,backup_expires_at=NULL WHERE id=1"
                )
            store.checkpoint()
        return exists

    def erase_backup(self) -> bool:
        """Erase the entire aggregate backup on any account purge, without keys."""
        with self._locked():
            return self._erase_backup()

    def _cleanup_expired_backup(self) -> bool:
        if not self.backup_path.exists() or self.backup_path.is_symlink():
            return self._erase_backup()
        ledger = self._ledger()
        try:
            envelope = _json(self.backup_path.read_bytes())
            created = _timestamp(envelope["created_at"])
            expiry = _timestamp(envelope["expires_at"])
            if expiry <= created or expiry > created + _MAX_BACKUP_AGE:
                return self._erase_backup()
            if ledger is not None and ledger["backup_expires_at"] is not None:
                expiry = min(expiry, _timestamp(ledger["backup_expires_at"]))
        except ValueError, TypeError, KeyError, RepositoryError:
            return self._erase_backup()
        return self._erase_backup() if expiry <= self.clock() else False

    def cleanup_expired_backup(self) -> bool:
        """Enforce the backup deadline even when no decryption key is available."""
        with self._locked():
            return self._cleanup_expired_backup()


__all__ = ["AuthMigration", "MigrationResult"]
