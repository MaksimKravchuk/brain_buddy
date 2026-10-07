"""Bounded, once-only email dispatch and durable purpose-separated abuse budgets.

Eligibility, client proof validation and authority issuance belong to the caller.
A valid code check never consumes a challenge: repeat ``code_matches`` in the
final authority transaction, then conditionally consume with the account action.
"""

from __future__ import annotations

import json
import logging
import secrets
import smtplib
import sqlite3
import ssl
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from email.message import EmailMessage
from math import ceil

from app.core.config import ModernAuthSettings
from app.repositories.auth_store import AuthStore
from app.services.auth_secret_box import AuthSecretBox, AuthSecretError, SecretContext
from app.utils.time import ensure_utc, from_isoformat, utcnow

_PURPOSES = {
    "login",
    "recover",
    "verify_email",
    "change_email",
    "reauth",
    "provider_mailbox",
}
_LEASE_SECONDS = 30
_WINDOW = timedelta(hours=1)
_LIMITS = {"send": (5, 20, 50), "guess": (10, 30, 100)}
logger = logging.getLogger(__name__)


class AuthMailError(ValueError):
    """A bounded safe error with no recipient, code or transport details."""

    def __init__(self) -> None:
        super().__init__("Authentication email operation is unavailable or invalid.")


class AuthMailRateLimitError(AuthMailError):
    """A safe retry bound; do not expose the affected address or budget scope."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__()
        self.retry_after_seconds = max(1, retry_after_seconds)


class AuthMailService:
    """Join root writes; lease and acknowledge SMTP in separate transactions."""

    def __init__(
        self,
        store: AuthStore,
        secret_box: AuthSecretBox,
        settings: ModernAuthSettings,
        *,
        send: Callable[[str, str, str], None] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.store = store
        self.secret_box = secret_box
        self.settings = settings
        self._send = send or self._smtp_send
        self._clock = clock

    def _now(self) -> datetime:
        return ensure_utc(self._clock())

    @staticmethod
    def _stamp(now: datetime) -> str:
        return now.isoformat(timespec="microseconds")

    def _outside_transaction(self) -> None:
        with self.store.connection() as conn:
            if conn.in_transaction:
                raise AuthMailError()

    def reserve_send(self, address: str, client_challenge: str, network: str) -> None:
        """Reserve all send budgets once; enqueue itself never reserves again."""
        with self.store.transaction() as conn:
            self._budget(conn, "send", address, client_challenge, network, reserve=True)

    def reserve_guess(self, address: str, client_challenge: str, network: str) -> None:
        """Reserve failed-guess budgets; successful guesses do not increment them."""
        with self.store.transaction() as conn:
            self._budget(
                conn, "guess", address, client_challenge, network, reserve=True
            )

    def _budget(
        self,
        conn: sqlite3.Connection,
        kind: str,
        address: str,
        client: str,
        network: str,
        *,
        reserve: bool,
    ) -> None:
        now = self._now()
        stamp = self._stamp(now)
        if reserve:
            conn.execute(
                "DELETE FROM auth_budgets WHERE julianday(expires_at)<=julianday(?)",
                (stamp,),
            )
        live = conn.execute(
            "SELECT DISTINCT key_id FROM auth_budgets "
            "WHERE julianday(expires_at)>julianday(?)",
            (stamp,),
        ).fetchall()
        if any(row["key_id"] not in self.secret_box.key_ids for row in live):
            raise AuthMailError()
        entries: list[tuple[str, str, int, str | None]] = []
        for scope, value, limit in zip(
            ("address", "client", "network"),
            (address.strip().lower(), client, network),
            _LIMITS[kind],
            strict=True,
        ):
            label = f"{kind}:{scope}"
            fingerprints = self.secret_box.budget_fingerprints(value, label)
            rows = conn.execute(
                "SELECT * FROM auth_budgets WHERE scope=? "
                "AND julianday(expires_at)>julianday(?)",
                (label, stamp),
            ).fetchall()
            matching = [
                row
                for row in rows
                if row["fingerprint"] == fingerprints.get(row["key_id"])
                and from_isoformat(row["window_started_at"]) > now - _WINDOW
            ]
            if sum(row["count"] for row in matching) >= limit:
                earliest = min(
                    from_isoformat(row["window_started_at"]) for row in matching
                )
                raise AuthMailRateLimitError(
                    ceil((earliest + _WINDOW - now).total_seconds())
                )
            resend_at = None
            if kind == "send" and scope == "address":
                previous = [
                    from_isoformat(row["resend_at"])
                    for row in matching
                    if row["resend_at"]
                ]
                if previous and max(previous) > now:
                    raise AuthMailRateLimitError(
                        ceil((max(previous) - now).total_seconds())
                    )
                resend_at = self._stamp(now + timedelta(seconds=60))
            entries.append(
                (label, fingerprints[self.secret_box.current_key_id], limit, resend_at)
            )
        if reserve:
            for label, fingerprint, _limit, resend_at in entries:
                conn.execute(
                    "INSERT INTO auth_budgets(scope,fingerprint,key_id,window_started_at,"
                    "count,resend_at,expires_at) VALUES(?,?,?,?,1,?,?) "
                    "ON CONFLICT(scope,fingerprint,key_id,window_started_at) "
                    "DO UPDATE SET count=count+1,resend_at=excluded.resend_at",
                    (
                        label,
                        fingerprint,
                        self.secret_box.current_key_id,
                        stamp,
                        resend_at,
                        self._stamp(now + _WINDOW),
                    ),
                )

    @staticmethod
    def _context(row: sqlite3.Row, kind: str) -> SecretContext:
        return SecretContext(
            kind=f"{kind}:{row['purpose']}",
            attempt_id=row["id"],
            owner_id=row["user_id"] or "",
            client_id=row["client_challenge"],
            generation=row["generation"],
        )

    def _challenge(self, conn: sqlite3.Connection, challenge_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM auth_challenges WHERE id=?", (challenge_id,)
        ).fetchone()
        if not isinstance(row, sqlite3.Row):
            raise AuthMailError()
        return row

    def _live(self, row: sqlite3.Row) -> bool:
        expiry = from_isoformat(row["expires_at"])
        return (
            expiry > self._now()
            and expiry <= from_isoformat(row["created_at"]) + timedelta(minutes=10)
            and row["failures"] < 5
            and row["status"] in {"pending", "active", "failed"}
        )

    def enqueue(self, challenge_id: str, code: str) -> str:
        """Seal one eligible generation; caller reserves send once beforehand."""
        with self.store.transaction() as conn:
            row = self._challenge(conn, challenge_id)
            if (
                not self._live(row)
                or not row["eligible"]
                or row["purpose"] not in _PURPOSES
            ):
                raise AuthMailError()
            if conn.execute(
                "SELECT 1 FROM auth_mail_jobs WHERE challenge_id=? AND generation=?",
                (challenge_id, row["generation"]),
            ).fetchone():
                raise AuthMailError()
            code_hmac = self.secret_box.code_digest(
                code, self._context(row, "email_code")
            )
            payload = json.dumps(
                {
                    "recipient": row["destination"],
                    "code": code,
                    "purpose": row["purpose"],
                }
            ).encode()
            sealed = self.secret_box.seal(payload, self._context(row, "mail_job"))
            job_id = f"mail_{uuid.uuid4().hex}"
            conn.execute(
                "INSERT INTO auth_mail_jobs(id,challenge_id,generation,created_at,"
                "expires_at,sealed_payload,key_id) VALUES(?,?,?,?,?,?,?)",
                (
                    job_id,
                    challenge_id,
                    row["generation"],
                    self._stamp(self._now()),
                    row["expires_at"],
                    sealed,
                    self.secret_box.current_key_id,
                ),
            )
            conn.execute(
                "UPDATE auth_challenges SET code_hmac=?,key_id=?,status='pending',resend_at=? WHERE id=?",
                (
                    code_hmac,
                    self.secret_box.current_key_id,
                    self._stamp(self._now() + timedelta(seconds=60)),
                    challenge_id,
                ),
            )
            return job_id

    def resend(self, challenge_id: str, *, network: str) -> str:
        """Explicit retry only: supersede code/jobs while retaining expiry and guesses."""
        with self.store.transaction() as conn:
            row = self._challenge(conn, challenge_id)
            if not self._live(row) or not row["eligible"]:
                raise AuthMailError()
            if row["resend_at"] and from_isoformat(row["resend_at"]) > self._now():
                raise AuthMailRateLimitError(
                    ceil(
                        (from_isoformat(row["resend_at"]) - self._now()).total_seconds()
                    )
                )
            self.reserve_send(row["destination"], row["client_challenge"], network)
            code = f"{secrets.randbelow(1_000_000):06d}"
            # A replacement must not accidentally reuse the previous six digits.
            while (
                row["code_hmac"]
                and row["key_id"]
                and self.secret_box.verify_code(
                    code,
                    row["code_hmac"],
                    self._context(row, "email_code"),
                    key_id=row["key_id"],
                )
            ):
                code = f"{secrets.randbelow(1_000_000):06d}"
            conn.execute(
                "UPDATE auth_mail_jobs SET status='superseded',sealed_payload=NULL,key_id=NULL "
                "WHERE challenge_id=? AND status IN ('pending','leased')",
                (challenge_id,),
            )
            conn.execute(
                "UPDATE auth_challenges SET generation=generation+1,code_hmac=NULL,"
                "key_id=NULL,status='pending' WHERE id=?",
                (challenge_id,),
            )
            return self.enqueue(challenge_id, code)

    def code_matches(
        self,
        conn: sqlite3.Connection,
        challenge_id: str,
        code: str,
        *,
        network: str | None = None,
    ) -> bool:
        """Read-only finalization recheck; caller consumes in this same transaction."""
        row = conn.execute(
            "SELECT * FROM auth_challenges WHERE id=?", (challenge_id,)
        ).fetchone()
        if row is not None and network is not None:
            self._budget(
                conn,
                "guess",
                row["destination"],
                row["client_challenge"],
                network,
                reserve=False,
            )
        return bool(
            row is not None
            and row["status"] == "active"
            and self._live(row)
            and row["eligible"]
            and row["code_hmac"]
            and row["key_id"]
            and self.secret_box.verify_code(
                code,
                row["code_hmac"],
                self._context(row, "email_code"),
                key_id=row["key_id"],
            )
        )

    def verify_code(self, challenge_id: str, code: str, *, network: str) -> bool:
        """Commit invalid-guess counters before returning; never call inside finalization."""
        self._outside_transaction()
        with self.store.transaction() as conn:
            row = self._challenge(conn, challenge_id)
            if not self._live(row):
                return False
            self._budget(
                conn,
                "guess",
                row["destination"],
                row["client_challenge"],
                network,
                reserve=False,
            )
            if self.code_matches(conn, challenge_id, code):
                return True
            self.reserve_guess(row["destination"], row["client_challenge"], network)
            conn.execute(
                "UPDATE auth_challenges SET failures=failures+1,"
                "status=CASE WHEN failures>=4 THEN 'failed' ELSE status END,"
                "code_hmac=CASE WHEN failures>=4 THEN NULL ELSE code_hmac END,"
                "key_id=CASE WHEN failures>=4 THEN NULL ELSE key_id END WHERE id=?",
                (challenge_id,),
            )
            return False

    @staticmethod
    def _retire(
        conn: sqlite3.Connection, job: sqlite3.Row, status: str = "failed"
    ) -> None:
        conn.execute(
            "UPDATE auth_mail_jobs SET status=?,sealed_payload=NULL,key_id=NULL,lease_id=NULL WHERE id=?",
            (status, job["id"]),
        )
        conn.execute(
            "UPDATE auth_challenges SET status='failed',code_hmac=NULL,key_id=NULL "
            "WHERE id=? AND generation=? AND status='pending'",
            (job["challenge_id"], job["generation"]),
        )

    def _lease(self) -> tuple[dict[str, str], str, str] | None:
        with self.store.transaction() as conn:
            now = self._now()
            jobs = conn.execute(
                "SELECT * FROM auth_mail_jobs WHERE status IN ('pending','leased') "
                "ORDER BY created_at,id"
            ).fetchall()
            selected: sqlite3.Row | None = None
            selected_row: sqlite3.Row | None = None
            for job in jobs:
                row = self._challenge(conn, job["challenge_id"])
                if (
                    from_isoformat(job["expires_at"]) <= now
                    or (
                        job["status"] == "leased"
                        and job["leased_at"]
                        and from_isoformat(job["leased_at"])
                        + timedelta(seconds=_LEASE_SECONDS)
                        <= now
                    )
                    or not self._live(row)
                    or not row["eligible"]
                    or row["generation"] != job["generation"]
                    or row["status"] != "pending"
                ):
                    self._retire(conn, job)
                elif job["status"] == "pending" and selected is None:
                    selected, selected_row = job, row
            conn.execute(
                "UPDATE auth_challenges SET code_hmac=NULL,key_id=NULL,status='expired' "
                "WHERE julianday(expires_at)<=julianday(?) AND status IN ('pending','active','failed')",
                (self._stamp(now),),
            )
            conn.execute(
                "DELETE FROM auth_budgets WHERE julianday(expires_at)<=julianday(?)",
                (self._stamp(now),),
            )
            if selected is None or selected_row is None:
                return None
            lease_id = uuid.uuid4().hex
            conn.execute(
                "UPDATE auth_mail_jobs SET status='leased',lease_id=?,leased_at=? WHERE id=?",
                (lease_id, self._stamp(now), selected["id"]),
            )
            try:
                payload = json.loads(
                    self.secret_box.open(
                        selected["sealed_payload"],
                        self._context(selected_row, "mail_job"),
                    )
                )
                if not isinstance(payload, dict) or set(payload) != {
                    "recipient",
                    "code",
                    "purpose",
                }:
                    raise AuthMailError()
                if any(not isinstance(value, str) for value in payload.values()):
                    raise AuthMailError()
                if (
                    payload["recipient"] != selected_row["destination"]
                    or payload["purpose"] != selected_row["purpose"]
                ):
                    raise AuthMailError()
            except (AuthSecretError, ValueError, TypeError):
                self._retire(conn, selected)
                return None
            return payload, selected["id"], lease_id

    def dispatch_one(self) -> bool:
        """Lease once, perform bounded transport outside writes, acknowledge exact generation."""
        self._outside_transaction()
        leased = self._lease()
        if leased is None:
            return False
        payload, job_id, lease_id = leased
        delivered = False
        try:
            self._send(payload["recipient"], payload["code"], payload["purpose"])
            delivered = True
        except (
            Exception
        ):  # noqa: BLE001 -- transport internals/credentials never escape
            logger.warning(
                "Authentication email delivery failed.",
                extra={"event": "auth_mail_delivery", "outcome": "failed"},
            )
        finally:
            payload.clear()
        with self.store.transaction() as conn:
            job = conn.execute(
                "SELECT * FROM auth_mail_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if job is None or job["status"] != "leased" or job["lease_id"] != lease_id:
                return True
            row = self._challenge(conn, job["challenge_id"])
            if (
                delivered
                and self._live(row)
                and row["eligible"]
                and row["generation"] == job["generation"]
                and row["status"] == "pending"
                and from_isoformat(job["leased_at"]) + timedelta(seconds=_LEASE_SECONDS)
                > self._now()
            ):
                conn.execute(
                    "UPDATE auth_challenges SET status='active' WHERE id=?",
                    (row["id"],),
                )
                self._retire(conn, job, "delivered")
            else:
                self._retire(conn, job)
        return True

    def _smtp_send(self, recipient: str, code: str, purpose: str) -> None:
        if not self.settings.email_available or purpose not in _PURPOSES:
            raise AuthMailError()
        message = EmailMessage()
        message["From"] = self.settings.smtp_sender
        message["To"] = recipient
        message["Subject"] = "Your BrainBuddy verification code"
        message.set_content(
            f"Your BrainBuddy code is {code}. It expires within 10 minutes.\n"
        )
        context = ssl.create_default_context()
        if self.settings.smtp_tls == "tls":
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=10,
                context=context,
            )
        else:
            smtp = smtplib.SMTP(
                self.settings.smtp_host, self.settings.smtp_port, timeout=10
            )
        with smtp:
            if self.settings.smtp_tls == "starttls":
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(
                self.settings.smtp_username,
                self.settings.smtp_password.get_secret_value(),
            )
            if smtp.send_message(message):
                raise AuthMailError()


__all__ = ["AuthMailError", "AuthMailRateLimitError", "AuthMailService"]
