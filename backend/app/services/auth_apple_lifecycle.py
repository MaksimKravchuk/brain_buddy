"""Generation-bound Apple credentials, bounded cleanup leases and signed notices."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

from pydantic import SecretStr

from app.repositories.auth_metadata import erase_settled_apple_unlinks
from app.repositories.auth_store import AuthStore
from app.services.auth_provider_service import (
    AppleNotification,
    ProviderError,
    ProviderTokens,
    RevocationTokenType,
)
from app.services.auth_secret_box import AuthSecretBox, AuthSecretError, SecretContext
from app.utils.time import ensure_utc, from_isoformat, utcnow

logger = logging.getLogger(__name__)
_ISSUER = "https://appleid.apple.com"
_NAMESPACE = "brainbuddy"
_LEASE = timedelta(seconds=30)
_LIFETIME = timedelta(hours=24)
_RECEIPTS = timedelta(days=8)
_REFRESH_KIND: RevocationTokenType = "refresh_token"


class _AppleGateway(Protocol):
    def revoke_apple(
        self,
        token: str | SecretStr,
        issuing_client: str,
        *,
        token_type: RevocationTokenType = _REFRESH_KIND,
    ) -> None: ...

    def verify_notification(self, signed_payload: str) -> AppleNotification: ...


class AuthAppleLifecycleError(ValueError):
    """Coarse lifecycle failures carry no provider credentials or assertions."""

    def __init__(self, code: str, status_code: int) -> None:
        super().__init__("Apple authentication cleanup could not be completed.")
        self.code = code
        self.status_code = status_code


class AuthAppleLifecycle:
    """Share caller writes and keep every provider network call outside them."""

    def __init__(
        self,
        store: AuthStore,
        secret_box: AuthSecretBox | None,
        gateway: _AppleGateway,
        *,
        clock: Callable[[], datetime] = utcnow,
        deletion_grace: timedelta = timedelta(days=14),
    ) -> None:
        self.store = store
        self.secret_box = secret_box
        self.gateway = gateway
        self.clock = clock
        self.deletion_grace = deletion_grace

    def _now(self) -> datetime:
        return ensure_utc(self.clock())

    @staticmethod
    def _stamp(value: datetime) -> str:
        return value.isoformat(timespec="microseconds")

    @staticmethod
    def _binding(connection: sqlite3.Connection, binding_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT b.*,u.deletion_requested_at FROM auth_identity_bindings b "
            "JOIN users u ON u.id=b.user_id WHERE b.id=? AND b.provider='apple'",
            (binding_id,),
        ).fetchone()
        if row is None:
            raise AuthAppleLifecycleError("owner_mismatch", 404)
        return cast(sqlite3.Row, row)

    @staticmethod
    def _write(connection: sqlite3.Connection) -> None:
        if not connection.in_transaction:
            raise AuthAppleLifecycleError("method_unavailable", 503)

    def _outside_transaction(self) -> None:
        with self.store.connection() as connection:
            if connection.in_transaction:
                raise AuthAppleLifecycleError("method_unavailable", 503)

    @staticmethod
    def _context(row: sqlite3.Row | dict[str, Any], kind: str) -> SecretContext:
        return SecretContext(
            kind=kind,
            attempt_id=row["id"],
            owner_id=row["user_id"],
            binding_id=row["binding_id"],
            client_id=row["issuing_client"],
            generation=row["generation"],
        )

    def _open(self, row: sqlite3.Row, kind: str) -> dict[str, str]:
        if self.secret_box is None or not row["sealed_payload"] or not row["key_id"]:
            raise AuthSecretError()
        if not row["sealed_payload"].startswith(f"bb-auth.v1.{row['key_id']}."):
            raise AuthSecretError()
        payload = json.loads(
            self.secret_box.open(row["sealed_payload"], self._context(row, kind))
        )
        if (
            not isinstance(payload, dict)
            or set(payload) != {"token", "token_type"}
            or not isinstance(payload["token"], str)
            or not 1 <= len(payload["token"]) <= 16384
            or payload["token_type"] not in {"refresh_token", "access_token"}
        ):
            raise AuthSecretError()
        return payload

    def ensure_replaceable(
        self, connection: sqlite3.Connection, binding_id: str
    ) -> None:
        """A worker must settle its lease before any newer consent can commit."""
        self._write(connection)
        self._binding(connection, binding_id)
        now = self._stamp(self._now())
        if (
            connection.execute(
                "SELECT 1 FROM auth_apple_cleanup_jobs WHERE binding_id=? AND status='leased' "
                "AND (lease_expires_at IS NULL OR julianday(lease_expires_at)>julianday(?))",
                (binding_id, now),
            ).fetchone()
            is not None
        ):
            raise AuthAppleLifecycleError("conflict", 409)
        # The lease exceeds the gateway timeout; an abandoned worker cannot
        # permanently block fresh consent. Its acknowledgment fails the CAS.
        connection.execute(
            "UPDATE auth_apple_cleanup_jobs SET status='cancelled',sealed_payload=NULL,key_id=NULL,lease_id=NULL,lease_expires_at=NULL "
            "WHERE binding_id=? AND (status='pending' OR (status='leased' AND julianday(lease_expires_at)<=julianday(?)))",
            (binding_id, now),
        )

    def record_grant(
        self, connection: sqlite3.Connection, binding_id: str, tokens: ProviderTokens
    ) -> None:
        """Store only the revocation-required token for this owner/client/generation."""
        self._write(connection)
        binding = self._binding(connection, binding_id)
        identity = tokens.identity
        metadata = json.loads(binding["payload_json"])
        if (
            identity.provider != "apple"
            or identity.issuer != binding["issuer"]
            or identity.issuer != _ISSUER
            or identity.namespace != binding["namespace"]
            or identity.namespace != _NAMESPACE
            or identity.subject != binding["subject"]
            or identity.audience != tokens.issuing_client
            or binding["state"] != "active"
            or not isinstance(tokens.revocation_token, SecretStr)
            or tokens.revocation_token_type not in {"refresh_token", "access_token"}
            or identity.issued_at < metadata.get("apple_consent_issued_at", 0)
            or identity.issued_at <= metadata.get("apple_revocation_event_at", -1)
        ):
            raise AuthAppleLifecycleError("invalid_proof", 400)
        if self.secret_box is None:
            raise AuthAppleLifecycleError("method_unavailable", 503)
        row = {
            "id": uuid.uuid4().hex,
            "user_id": binding["user_id"],
            "binding_id": binding_id,
            "issuing_client": tokens.issuing_client,
            "generation": binding["generation"],
        }
        payload = {
            "token": tokens.revocation_token.get_secret_value(),
            "token_type": tokens.revocation_token_type,
        }
        try:
            sealed = self.secret_box.seal(
                json.dumps(payload).encode(), self._context(row, "apple_grant")
            )
        except AuthSecretError:
            raise AuthAppleLifecycleError("method_unavailable", 503) from None
        finally:
            payload.clear()
        self.ensure_replaceable(connection, binding_id)
        connection.execute(
            "DELETE FROM auth_apple_grants WHERE binding_id=? AND issuing_client=?",
            (binding_id, tokens.issuing_client),
        )
        connection.execute(
            "INSERT INTO auth_apple_grants(id,user_id,binding_id,issuing_client,generation,sealed_payload,key_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                row["id"],
                row["user_id"],
                binding_id,
                row["issuing_client"],
                row["generation"],
                sealed,
                self.secret_box.current_key_id,
                self._stamp(self._now()),
            ),
        )
        metadata["apple_consent_issued_at"] = identity.issued_at
        metadata.pop("apple_confirmation_required", None)
        metadata.pop("unlinked_expires_at", None)
        connection.execute(
            "UPDATE auth_identity_bindings SET payload_json=? WHERE id=?",
            (json.dumps(metadata), binding_id),
        )

    def schedule_cleanup(
        self, connection: sqlite3.Connection, binding_id: str, reason: str
    ) -> None:
        """Transfer grants to bounded jobs; missing keys never delay local erasure."""
        self._write(connection)
        binding = self._binding(connection, binding_id)
        now = self._now()
        expiry = now + _LIFETIME
        if binding["deletion_requested_at"]:
            expiry = min(
                expiry,
                from_isoformat(binding["deletion_requested_at"]) + self.deletion_grace,
            )
        grants = connection.execute(
            "SELECT * FROM auth_apple_grants WHERE binding_id=?", (binding_id,)
        ).fetchall()
        for grant in grants:
            row = dict(grant) | {"id": uuid.uuid4().hex}
            sealed: str | None = None
            key_id: str | None = None
            status = "pending" if expiry > now else "expired"
            try:
                if self.secret_box is None:
                    raise AuthSecretError()
                payload = self._open(grant, "apple_grant")
                try:
                    sealed = self.secret_box.seal(
                        json.dumps(payload).encode(),
                        self._context(row, "apple_cleanup"),
                    )
                    key_id = self.secret_box.current_key_id
                finally:
                    payload.clear()
            except (AuthSecretError, ValueError, TypeError):
                status = "failed"
            if status != "pending":
                sealed = key_id = None
            connection.execute(
                "INSERT INTO auth_apple_cleanup_jobs(id,user_id,binding_id,issuing_client,generation,sealed_payload,key_id,reason,status,created_at,expires_at,next_attempt_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["id"],
                    row["user_id"],
                    binding_id,
                    row["issuing_client"],
                    row["generation"],
                    sealed,
                    key_id,
                    reason,
                    status,
                    self._stamp(now),
                    self._stamp(expiry),
                    self._stamp(now),
                    json.dumps({"binding_generation": binding["generation"]}),
                ),
            )
        connection.execute(
            "DELETE FROM auth_apple_grants WHERE binding_id=?", (binding_id,)
        )

    @staticmethod
    def _retire(connection: sqlite3.Connection, job_id: str, status: str) -> None:
        connection.execute(
            "UPDATE auth_apple_cleanup_jobs SET status=?,sealed_payload=NULL,key_id=NULL,lease_id=NULL,lease_expires_at=NULL WHERE id=?",
            (status, job_id),
        )

    def _lease(self) -> tuple[sqlite3.Row, dict[str, str], str] | None:
        with self.store.transaction() as connection:
            now = self._now()
            erase_settled_apple_unlinks(connection, now=now)
            jobs = connection.execute(
                "SELECT * FROM auth_apple_cleanup_jobs WHERE status IN ('pending','leased') ORDER BY created_at,id LIMIT 100"
            ).fetchall()
            for job in jobs:
                if (
                    job["status"] == "leased"
                    and from_isoformat(job["lease_expires_at"]) > now
                ):
                    if from_isoformat(job["expires_at"]) <= now:
                        connection.execute(
                            "UPDATE auth_apple_cleanup_jobs SET sealed_payload=NULL,key_id=NULL WHERE id=?",
                            (job["id"],),
                        )
                    continue
                binding = self._binding(connection, job["binding_id"])
                generation = json.loads(job["payload_json"]).get("binding_generation")
                if (
                    from_isoformat(job["expires_at"]) < now + _LEASE
                    or job["attempts"] >= 5
                ):
                    self._retire(connection, job["id"], "failed")
                    continue
                if generation != binding["generation"]:
                    self._retire(connection, job["id"], "cancelled")
                    continue
                if (
                    job["next_attempt_at"]
                    and from_isoformat(job["next_attempt_at"]) > now
                ):
                    continue
                try:
                    payload = self._open(job, "apple_cleanup")
                except (AuthSecretError, ValueError, TypeError):
                    self._retire(connection, job["id"], "failed")
                    continue
                lease_id = uuid.uuid4().hex
                connection.execute(
                    "UPDATE auth_apple_cleanup_jobs SET status='leased',attempts=attempts+1,lease_id=?,lease_expires_at=? WHERE id=?",
                    (lease_id, self._stamp(now + _LEASE), job["id"]),
                )
                return job, payload, lease_id
            erase_settled_apple_unlinks(connection, now=now)
        self.store.checkpoint()
        return None

    def dispatch_one(self) -> bool:
        """Lease/CAS bounds retries; Apple revocation runs after the lease commits."""
        self._outside_transaction()
        leased = self._lease()
        if leased is None:
            return False
        job, payload, lease_id = leased
        delivered = False
        try:
            token_type: RevocationTokenType = (
                _REFRESH_KIND
                if payload["token_type"] == _REFRESH_KIND
                else "access_token"
            )
            self.gateway.revoke_apple(
                SecretStr(payload["token"]),
                job["issuing_client"],
                token_type=token_type,
            )
            delivered = True
        except Exception:  # noqa: BLE001 -- provider secrets must not escape/log
            logger.warning(
                "Apple credential cleanup remains unconfirmed.",
                extra={"event": "auth_apple_cleanup", "outcome": "failed"},
            )
        finally:
            payload.clear()
        with self.store.transaction() as connection:
            current = connection.execute(
                "SELECT * FROM auth_apple_cleanup_jobs WHERE id=?", (job["id"],)
            ).fetchone()
            if (
                current is None
                or current["status"] != "leased"
                or current["lease_id"] != lease_id
            ):
                return True
            binding = self._binding(connection, current["binding_id"])
            now = self._now()
            if (
                json.loads(current["payload_json"]).get("binding_generation")
                != binding["generation"]
            ):
                self._retire(connection, current["id"], "cancelled")
            elif delivered:
                self._retire(connection, current["id"], "delivered")
            elif (
                current["attempts"] >= 5
                or from_isoformat(current["expires_at"]) <= now
                or not current["sealed_payload"]
            ):
                self._retire(connection, current["id"], "failed")
            else:
                retry = min(
                    now + timedelta(seconds=60 * 2 ** (current["attempts"] - 1)),
                    from_isoformat(current["expires_at"]),
                )
                connection.execute(
                    "UPDATE auth_apple_cleanup_jobs SET status='pending',lease_id=NULL,lease_expires_at=NULL,next_attempt_at=? WHERE id=? AND lease_id=?",
                    (self._stamp(retry), current["id"], lease_id),
                )
            erase_settled_apple_unlinks(connection, now=now)
        self.store.checkpoint()
        return True

    def _disable(
        self,
        connection: sqlite3.Connection,
        binding: sqlite3.Row,
        metadata: dict[str, Any],
    ) -> None:
        connection.execute(
            "UPDATE auth_identity_bindings SET state='revoked',updated_at=?,payload_json=? WHERE id=?",
            (self._stamp(self._now()), json.dumps(metadata), binding["id"]),
        )
        connection.execute(
            "DELETE FROM sessions WHERE provider_binding_id=?", (binding["id"],)
        )
        connection.execute(
            "DELETE FROM auth_proofs WHERE provider_binding_id=?", (binding["id"],)
        )
        connection.execute(
            "DELETE FROM auth_attempts WHERE user_id=? AND provider='apple'",
            (binding["user_id"],),
        )
        connection.execute(
            "DELETE FROM auth_apple_grants WHERE binding_id=?", (binding["id"],)
        )
        connection.execute(
            "UPDATE auth_apple_cleanup_jobs SET status=CASE WHEN status='leased' THEN status ELSE 'cancelled' END,sealed_payload=NULL,key_id=NULL WHERE binding_id=? AND status IN ('pending','leased')",
            (binding["id"],),
        )

    def process_notification(self, payload: str) -> None:
        """Verify first; insert replay receipt and its bounded effects atomically."""
        self._outside_transaction()
        try:
            event = self.gateway.verify_notification(payload)
        except ProviderError as exc:
            raise AuthAppleLifecycleError(
                exc.code, 400 if exc.code == "invalid_proof" else 503
            ) from None
        except (ValueError, TypeError):
            raise AuthAppleLifecycleError("invalid_proof", 400) from None
        digest = hashlib.sha256(
            f"{_NAMESPACE}\0{_ISSUER}\0{event.jti}".encode()
        ).hexdigest()
        fingerprint = hashlib.sha256(
            f"{_NAMESPACE}\0{event.subject}".encode()
        ).hexdigest()
        with self.store.transaction() as connection:
            now = self._now()
            connection.execute(
                "DELETE FROM auth_apple_notification_receipts WHERE julianday(expires_at)<=julianday(?)",
                (self._stamp(now),),
            )
            if (
                connection.execute(
                    "SELECT 1 FROM auth_apple_notification_receipts WHERE digest=?",
                    (digest,),
                ).fetchone()
                is not None
            ):
                return
            binding = connection.execute(
                "SELECT * FROM auth_identity_bindings WHERE provider='apple' AND issuer=? AND namespace=? AND subject=?",
                (_ISSUER, _NAMESPACE, event.subject),
            ).fetchone()
            connection.execute(
                "INSERT INTO auth_apple_notification_receipts(digest,namespace,event,subject_fingerprint,generation,event_at,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    digest,
                    _NAMESPACE,
                    event.event_type,
                    fingerprint,
                    None if binding is None else binding["generation"],
                    datetime.fromtimestamp(event.event_time, tz=now.tzinfo).isoformat(),
                    self._stamp(now),
                    self._stamp(now + _RECEIPTS),
                ),
            )
            if binding is None or binding["state"] == "unlinked":
                return
            metadata = json.loads(binding["payload_json"])
            consent_at = metadata.get(
                "apple_consent_issued_at",
                int(from_isoformat(binding["created_at"]).timestamp()),
            )
            if event.event_time < consent_at:
                return
            if event.event_type in {"consent-revoked", "account-deleted"}:
                metadata["apple_revocation_event_at"] = event.event_time
                if event.event_time == consent_at:
                    metadata["apple_confirmation_required"] = True
                self._disable(connection, binding, metadata)
            elif (
                event.email is not None
                and event.email == binding["email"]
                and binding["is_private_email"]
                and event.is_private_email is not False
                and event.event_time > metadata.get("apple_email_event_at", 0)
            ):
                metadata["email_delivery_disabled"] = (
                    event.event_type == "email-disabled"
                )
                metadata["apple_email_event_at"] = event.event_time
                connection.execute(
                    "UPDATE auth_identity_bindings SET payload_json=? WHERE id=?",
                    (json.dumps(metadata), binding["id"]),
                )
        self.store.checkpoint()


__all__ = ["AuthAppleLifecycle", "AuthAppleLifecycleError"]
