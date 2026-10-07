"""Bounded lifecycle helpers for Identity-owned relational authentication metadata."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from .auth_store import AuthStore

_EXPIRING_TABLES = (
    "auth_mail_jobs",
    "auth_handoffs",
    "auth_challenges",
    "auth_attempts",
    "auth_proofs",
    "auth_budgets",
    "auth_apple_cleanup_jobs",
    "auth_apple_notification_receipts",
)
_OWNED_TABLES = (
    "auth_proofs",
    "auth_challenges",
    "auth_attempts",
    "auth_apple_cleanup_jobs",
    "auth_apple_grants",
    "auth_identity_bindings",
)


def erase_settled_apple_unlinks(
    connection: sqlite3.Connection, *, now: datetime, limit: int = 100
) -> int:
    """Erase bounded cleanup-only mappings after work settles, never across a live lease."""
    rows = connection.execute(
        "SELECT b.id,b.namespace,b.subject FROM auth_identity_bindings b "
        "WHERE b.provider='apple' AND b.state='unlinked' "
        "AND NOT EXISTS (SELECT 1 FROM auth_apple_cleanup_jobs j WHERE j.binding_id=b.id "
        "AND j.status='leased' AND (j.lease_expires_at IS NULL OR julianday(j.lease_expires_at)>julianday(?))) "
        "AND (julianday(json_extract(b.payload_json,'$.unlinked_expires_at'))<=julianday(?) "
        "OR NOT EXISTS (SELECT 1 FROM auth_apple_cleanup_jobs j WHERE j.binding_id=b.id "
        "AND j.status IN ('pending','leased') AND j.sealed_payload IS NOT NULL AND j.attempts<5 "
        "AND julianday(j.expires_at)>julianday(?))) ORDER BY b.updated_at,b.id LIMIT ?",
        (now.isoformat(), now.isoformat(), now.isoformat(), limit),
    ).fetchall()
    for row in rows:
        fingerprint = hashlib.sha256(
            f"{row['namespace']}\0{row['subject']}".encode()
        ).hexdigest()
        connection.execute(
            "DELETE FROM auth_apple_notification_receipts WHERE namespace=? AND subject_fingerprint=?",
            (row["namespace"], fingerprint),
        )
        connection.execute(
            "DELETE FROM auth_identity_bindings WHERE id=? AND state='unlinked'",
            (row["id"],),
        )
    return len(rows)


class AuthMetadataRepository:
    """Share the facade transaction; authority transitions use store SQL directly."""

    def __init__(self, root: Path, store: AuthStore | None = None) -> None:
        self.store = store if store is not None else AuthStore(root)

    def list_bindings(self, user_id: str) -> list[sqlite3.Row]:
        with self.store.connection() as connection:
            return list(
                connection.execute(
                    "SELECT * FROM auth_identity_bindings WHERE user_id=? ORDER BY provider,id",
                    (user_id,),
                ).fetchall()
            )

    def delete_for_user(self, user_id: str) -> int:
        """Remove owned metadata; cascades erase dependent mail and handoff secrets."""
        removed = 0
        with self.store.transaction() as connection:
            for table in _OWNED_TABLES:
                # Table identifiers come solely from the fixed module allowlist.
                removed += connection.execute(
                    f"DELETE FROM {table} WHERE user_id=?", (user_id,)  # noqa: S608
                ).rowcount
        return removed

    def cleanup_expired(self, *, now: datetime, limit: int = 100) -> int:
        """Bound total direct deletions, erasing expired sealed payloads with rows."""
        if not 1 <= limit <= 1000:
            raise ValueError("Cleanup limit must be between 1 and 1000.")
        removed = 0
        with self.store.transaction() as connection:
            for table in _EXPIRING_TABLES:
                remaining = limit - removed
                if remaining == 0:
                    break
                if table == "auth_apple_cleanup_jobs":
                    connection.execute(
                        "UPDATE auth_apple_cleanup_jobs SET sealed_payload=NULL,key_id=NULL WHERE status='leased' AND expires_at<=? AND lease_expires_at>?",
                        (now.isoformat(), now.isoformat()),
                    )
                    removed += connection.execute(
                        "DELETE FROM auth_apple_cleanup_jobs WHERE rowid IN (SELECT rowid FROM auth_apple_cleanup_jobs WHERE expires_at<=? AND (status!='leased' OR lease_expires_at IS NULL OR lease_expires_at<=?) ORDER BY expires_at LIMIT ?)",
                        (now.isoformat(), now.isoformat(), remaining),
                    ).rowcount
                    continue
                # Table identifiers come solely from the fixed module allowlist.
                removed += connection.execute(
                    f"DELETE FROM {table} WHERE rowid IN "  # noqa: S608
                    f"(SELECT rowid FROM {table} WHERE expires_at<=? ORDER BY expires_at LIMIT ?)",
                    (now.isoformat(), remaining),
                ).rowcount
            if removed < limit:
                removed += erase_settled_apple_unlinks(
                    connection, now=now, limit=limit - removed
                )
        if removed:
            self.store.checkpoint()
        return removed


__all__ = ["AuthMetadataRepository", "erase_settled_apple_unlinks"]
