"""Explicit approval and atomic consume/session mint in shared Identity storage."""

import hashlib
import secrets
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock

from app.core.config import _cli_verification_origin
from app.core.rate_limit import BoundedKeyRateLimiter
from app.repositories.cli_auth import CliAuthRepository
from app.repositories.feature_flag import FlagMode
from app.schemas.auth import Session, User
from app.services.auth_service import AuthService
from app.services.feature_flag_service import FeatureFlagService
from app.utils.time import utcnow

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class CliAuthError(Exception):
    def __init__(
        self, code: str, status_code: int = 400, retry_after: int | None = None
    ):
        super().__init__(code)
        self.code, self.status_code, self.retry_after = code, status_code, retry_after


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _display(value: str) -> str:
    return value[:4] + "-" + value[4:]


class CliAuthService:
    def __init__(
        self,
        *,
        auth_service: AuthService,
        feature_flags: FeatureFlagService,
        origin: str,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.auth, self.flags = auth_service, feature_flags
        self.origin = _cli_verification_origin(origin)
        self.clock = clock
        self.repo = CliAuthRepository(self.auth.user_repo.store)
        self.start_limit = BoundedKeyRateLimiter(
            max_attempts=10, window_seconds=60, max_keys=1024
        )
        self.start_global = BoundedKeyRateLimiter(
            max_attempts=120, window_seconds=60, max_keys=1
        )
        self.browser_limit = BoundedKeyRateLimiter(
            max_attempts=10, window_seconds=600, max_keys=1024
        )
        self.browser_global = BoundedKeyRateLimiter(
            max_attempts=120, window_seconds=60, max_keys=1
        )
        # Serialize admission and failure recording so concurrent guesses cannot
        # all enter before the ten-attempt browser budget is charged.
        self.browser_admission = Lock()

    def available(self, user: User | None = None) -> None:
        overlay = self.flags.repository.read()
        entry = overlay.flags.get("cli_auth")
        admitted = (
            self.origin
            and not overlay.degraded
            and entry
            and entry.mode != FlagMode.OFF
        )
        if not admitted or (
            user is not None and not self.flags.is_effective("cli_auth", user)
        ):
            raise CliAuthError("cli_auth_unavailable", 404)

    def start(self) -> dict[str, object]:
        self.available()
        now = self.clock().timestamp()
        with self.repo.store.transaction() as connection:
            self.repo.prune(connection, now)
            if (
                connection.execute("SELECT count(*) FROM cli_device_grants").fetchone()[
                    0
                ]
                >= 1024
            ):
                raise CliAuthError("rate_limited", 429, 60)
            for _ in range(8):
                proof = secrets.token_urlsafe(32)
                code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
                try:
                    connection.execute(
                        "INSERT INTO cli_device_grants(device_hash,code_hash,created_at,expires_at,state,interval,next_poll_at) VALUES(?,?,?,?, 'pending',5,?)",
                        (_digest(proof), _digest(code), now, now + 600, now + 5),
                    )
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise CliAuthError("cli_auth_unavailable", 503)
            self.available()
        uri = self.origin + "/cli/authorize"
        return {
            "device_code": proof,
            "user_code": _display(code),
            "verification_uri": uri,
            "verification_uri_complete": uri + "#user_code=" + _display(code),
            "expires_in": 600,
            "interval": 5,
            "protocol_version": 1,
        }

    def _source(
        self,
        connection: sqlite3.Connection,
        source_hash: str,
        row: sqlite3.Row | None = None,
    ) -> tuple[User, Session, int | None]:
        session = self.auth.session_repo.get(source_hash)
        user = self.auth.user_repo.get_by_id(session.user_id) if session else None
        if (
            not session
            or not user
            or user.deletion_requested_at is not None
            or user.auth_version != session.auth_version
            or (
                user.email in self.auth.reserved_emails
                and session.auth_method != "password"
            )
        ):
            raise CliAuthError("cli_auth_unavailable", 404)
        generation = None
        if session.auth_method in {"google", "apple"}:
            binding = connection.execute(
                "SELECT * FROM auth_identity_bindings WHERE id=? AND user_id=?",
                (session.provider_binding_id, user.id),
            ).fetchone()
            if (
                binding is None
                or binding["state"] != "active"
                or binding["provider"] != session.auth_method
            ):
                raise CliAuthError("cli_auth_unavailable", 404)
            generation = binding["generation"]
        if (
            row is not None
            and row["user_id"] is not None
            and (
                row["user_id"] != user.id
                or row["source_hash"] != source_hash
                or row["auth_version"] != user.auth_version
                or row["auth_method"] != session.auth_method
                or row["binding_id"] != session.provider_binding_id
                or row["generation"] != generation
            )
        ):
            raise CliAuthError("cli_auth_unavailable", 404)
        self.available(user)
        return user, session, generation

    def browser(
        self, code: str, raw_source: str | None, decision: str | None = None
    ) -> dict[str, object]:
        if not raw_source:
            raise CliAuthError("cli_auth_unavailable", 404)
        source_hash = self.auth.hash_session_token(raw_source)
        normalized = code.replace("-", "")
        with self.repo.store.transaction() as connection:
            row = self.repo.lookup(connection, code_hash=_digest(normalized))
            if row is not None and row["expires_at"] <= self.clock().timestamp():
                connection.execute(
                    "DELETE FROM cli_device_grants WHERE device_hash=?",
                    (row["device_hash"],),
                )
                row = None
            if row is not None:
                user, session, generation = self._source(connection, source_hash, row)
                state = row["state"]
                if decision:
                    requested = "approved" if decision == "approve" else "denied"
                    if state != "pending" and state != requested:
                        raise CliAuthError("decision_conflict", 409)
                    if state == "pending":
                        connection.execute(
                            "UPDATE cli_device_grants SET state=?,user_id=?,source_hash=?,auth_version=?,auth_method=?,binding_id=?,generation=? WHERE device_hash=? AND state='pending'",
                            (
                                requested,
                                user.id,
                                source_hash,
                                user.auth_version,
                                session.auth_method,
                                session.provider_binding_id,
                                generation,
                                row["device_hash"],
                            ),
                        )
                    self._source(connection, source_hash)
                    return {"state": requested}
                return {
                    "user_code": _display(normalized),
                    "client_name": "BrainBuddy CLI",
                    "created_at": datetime.fromtimestamp(
                        row["created_at"], UTC
                    ).isoformat(),
                    "expires_at": datetime.fromtimestamp(
                        row["expires_at"], UTC
                    ).isoformat(),
                    "state": state,
                }
        raise CliAuthError("cli_auth_unavailable", 404)

    def token(self, proof: str) -> tuple[User, str, Session]:
        self.available()
        now = self.clock().timestamp()
        outcome: CliAuthError | None = None
        result = None
        # Errors for poll state are raised AFTER commit. Issuance exceptions abort
        # both conditional consumption and the nested ordinary session insertion.
        with self.repo.store.transaction() as connection:
            row = self.repo.lookup(connection, device_hash=_digest(proof))
            if row is None:
                outcome = CliAuthError("invalid_device_code")
            elif row["expires_at"] <= now:
                connection.execute(
                    "DELETE FROM cli_device_grants WHERE device_hash=?",
                    (row["device_hash"],),
                )
                outcome = CliAuthError("authorization_expired")
            elif row["state"] == "consumed":
                outcome = CliAuthError("authorization_consumed", 409)
            elif row["state"] == "denied":
                outcome = CliAuthError("authorization_denied", 403)
            elif now < row["next_poll_at"]:
                interval = row["interval"] + 5
                connection.execute(
                    "UPDATE cli_device_grants SET interval=?,next_poll_at=? WHERE device_hash=?",
                    (interval, now + interval, row["device_hash"]),
                )
                outcome = CliAuthError("slow_down", retry_after=interval)
            elif row["state"] == "pending":
                connection.execute(
                    "UPDATE cli_device_grants SET next_poll_at=? WHERE device_hash=?",
                    (now + row["interval"], row["device_hash"]),
                )
                outcome = CliAuthError(
                    "authorization_pending", retry_after=row["interval"]
                )
            else:
                user, source, _ = self._source(connection, row["source_hash"], row)
                updated = connection.execute(
                    "UPDATE cli_device_grants SET state='consumed' WHERE device_hash=? AND state='approved'",
                    (row["device_hash"],),
                ).rowcount
                if updated != 1:
                    raise CliAuthError("authorization_consumed", 409)
                raw, session = self.auth._create_session(
                    user.id,
                    auth_method=source.auth_method,
                    provider_binding_id=source.provider_binding_id,
                )
                fresh, _, _ = self._source(connection, row["source_hash"], row)
                if (
                    row["expires_at"] <= self.clock().timestamp()
                    or session.auth_version != fresh.auth_version
                ):
                    raise CliAuthError("authorization_expired")
                result = fresh, raw, session
        if outcome:
            raise outcome
        assert result is not None
        return result

    def cleanup(self) -> int:
        return self.repo.cleanup(self.clock().timestamp())
