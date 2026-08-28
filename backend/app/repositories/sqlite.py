"""Neutral SQLite connection and transaction mechanics for owned repositories."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.exceptions import ConflictError, RepositoryError, StorageUnavailableError


class SQLiteRepositorySupport:
    """Provide lifecycle mechanics without owning repository state or policy."""

    db_path: Path

    @staticmethod
    @contextmanager
    def sqlite_guard(
        resource: str,
        identifier: str,
        operational_message: str | None = None,
        repository_message: str | None = None,
    ) -> Iterator[None]:
        try:
            yield
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                resource,
                identifier,
                f"{resource} '{identifier}' conflicts with existing records.",
            ) from exc
        except sqlite3.OperationalError as exc:
            raise StorageUnavailableError(
                operational_message
                or "Storage is temporarily unavailable; retry the request."
            ) from exc
        except sqlite3.Error as exc:
            raise RepositoryError(
                repository_message
                or f"Storage failed while writing {resource} '{identifier}'."
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _owned_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _connection(
        self, thread_state: threading.local
    ) -> Iterator[sqlite3.Connection]:
        active = getattr(thread_state, "conn", None)
        if active is not None:
            yield active
            return
        with self._owned_connection() as connection:
            yield connection

    @contextmanager
    def _command_lock(
        self,
        owner_id: str,
        *,
        lock: threading.RLock,
        thread_state: threading.local,
        resource: str,
        operational_message: str,
        repository_message: str,
    ) -> Iterator[None]:
        with lock:
            connection = self._connect()
            previous = getattr(thread_state, "conn", None)
            thread_state.conn = connection
            try:
                with self.sqlite_guard(
                    resource, owner_id, operational_message, repository_message
                ):
                    connection.execute("BEGIN IMMEDIATE")
                    yield
                    connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                thread_state.conn = previous
                connection.close()


__all__ = ["SQLiteRepositorySupport"]
