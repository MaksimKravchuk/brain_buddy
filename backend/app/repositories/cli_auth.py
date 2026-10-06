"""Transient hashed grants in the existing, single Identity SQLite authority."""

import logging
import math
import re
import sqlite3

from app.core.logging import get_correlation_id
from app.exceptions import RepositoryError
from app.repositories.auth_store import AuthStore

logger = logging.getLogger(__name__)

_TABLE = """CREATE TABLE IF NOT EXISTS cli_device_grants (
 device_hash TEXT PRIMARY KEY,
 code_hash TEXT NOT NULL UNIQUE,
 created_at REAL NOT NULL,
 expires_at REAL NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','approved','denied','consumed')),
 interval INTEGER NOT NULL CHECK(interval >= 5),
 next_poll_at REAL NOT NULL,
 user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
 source_hash TEXT,
 auth_version INTEGER,
 auth_method TEXT,
 binding_id TEXT,
 generation INTEGER,
 FOREIGN KEY(source_hash,user_id) REFERENCES sessions(token_hash,user_id) ON DELETE CASCADE,
 FOREIGN KEY(binding_id,user_id) REFERENCES auth_identity_bindings(id,user_id) ON DELETE CASCADE
)"""
_COLUMNS = (
    "device_hash",
    "code_hash",
    "created_at",
    "expires_at",
    "state",
    "interval",
    "next_poll_at",
    "user_id",
    "source_hash",
    "auth_version",
    "auth_method",
    "binding_id",
    "generation",
)


class CliAuthRepository:
    def __init__(self, store: AuthStore) -> None:
        self.store = store
        # Additive, restart-idempotent migration; import epoch and ledger stay owned
        # by AuthStore. Refuse an incompatible table rather than repairing authority.
        with store.transaction() as connection:
            connection.execute(_TABLE)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS cli_device_expiry ON cli_device_grants(expires_at)"
            )
            columns = tuple(
                row["name"]
                for row in connection.execute("PRAGMA table_info(cli_device_grants)")
            )
            schema = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='cli_device_grants'"
            ).fetchone()[0]

            def normalize(text: str) -> str:
                return "".join(text.lower().replace("if not exists", "").split())

            if columns != _COLUMNS or normalize(schema) != normalize(_TABLE):
                raise RepositoryError("CLI authorization schema is incompatible.")

    @staticmethod
    def valid(row: sqlite3.Row) -> bool:
        hashes = all(
            isinstance(row[name], str) and re.fullmatch(r"[0-9a-f]{64}", row[name])
            for name in ("device_hash", "code_hash")
        )
        times = all(
            type(row[name]) in {int, float} and math.isfinite(row[name])
            for name in ("created_at", "expires_at", "next_poll_at")
        )
        if (
            not hashes
            or not times
            or abs(row["expires_at"] - row["created_at"] - 600) > 0.001
            or type(row["interval"]) is not int
            or row["interval"] < 5
        ):
            return False
        if row["state"] == "pending":
            return all(
                row[name] is None
                for name in (
                    "user_id",
                    "source_hash",
                    "auth_version",
                    "auth_method",
                    "binding_id",
                    "generation",
                )
            )
        if (
            row["state"] not in {"approved", "denied", "consumed"}
            or not isinstance(row["user_id"], str)
            or not isinstance(row["source_hash"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", row["source_hash"])
            or type(row["auth_version"]) is not int
            or row["auth_version"] < 0
        ):
            return False
        if row["auth_method"] in {"google", "apple"}:
            return (
                isinstance(row["binding_id"], str)
                and type(row["generation"]) is int
                and row["generation"] >= 1
            )
        return (
            row["auth_method"] in {"password", "email"}
            and row["binding_id"] is None
            and row["generation"] is None
        )

    @classmethod
    def lookup(
        cls,
        connection: sqlite3.Connection,
        *,
        device_hash: str | None = None,
        code_hash: str | None = None,
    ) -> sqlite3.Row | None:
        query, value = (
            ("SELECT * FROM cli_device_grants WHERE device_hash=?", device_hash)
            if device_hash is not None
            else ("SELECT * FROM cli_device_grants WHERE code_hash=?", code_hash)
        )
        row: sqlite3.Row | None = connection.execute(query, (value,)).fetchone()
        if row is not None and not cls.valid(row):
            connection.execute(
                "DELETE FROM cli_device_grants WHERE device_hash=?",
                (row["device_hash"],),
            )
            logger.warning(
                "Invalid CLI authorization grant erased: correlation=%s",
                get_correlation_id(),
            )
            return None
        return row

    @classmethod
    def prune(cls, connection: sqlite3.Connection, now: float) -> int:
        corrupt = [
            row["device_hash"]
            for row in connection.execute("SELECT * FROM cli_device_grants")
            if not cls.valid(row)
        ]
        for digest in corrupt:
            connection.execute(
                "DELETE FROM cli_device_grants WHERE device_hash=?", (digest,)
            )
        if corrupt:
            logger.warning(
                "Invalid CLI authorization grants erased: count=%s correlation=%s",
                len(corrupt),
                get_correlation_id(),
            )
        return (
            len(corrupt)
            + connection.execute(
                "DELETE FROM cli_device_grants WHERE expires_at<=?", (now,)
            ).rowcount
        )

    def cleanup(self, now: float) -> int:
        with self.store.transaction() as connection:
            removed = self.prune(connection, now)
        self.store.checkpoint()
        return removed
