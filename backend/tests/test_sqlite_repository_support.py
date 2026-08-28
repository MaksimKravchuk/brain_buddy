from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from unittest.mock import patch

import pytest

from app.exceptions import ConflictError, RepositoryError, StorageUnavailableError
from app.modules.tasks.repository import TaskRepository
from app.repositories.sqlite import SQLiteRepositorySupport
from app.workflows.voice_brain_dump.repository import OperationRepository


class TinyRepository(SQLiteRepositorySupport):
    _thread_state = threading.local()
    _process_lock = RLock()

    def __init__(self, path: Path) -> None:
        self.db_path = path
        self.db_path.touch()

    @contextmanager
    def command(self, owner: str):
        with self._command_lock(
            owner,
            lock=self._process_lock,
            thread_state=self._thread_state,
            resource="Tiny command",
            operational_message="tiny unavailable",
            repository_message=f"tiny failed for {owner}",
        ):
            yield


class OtherRepository(TinyRepository):
    _thread_state = threading.local()
    _process_lock = RLock()


class TrackedConnection:
    def __init__(self) -> None:
        self.events: list[str] = []

    def execute(self, sql: str):
        self.events.append(sql)
        if sql == "BEGIN IMMEDIATE":
            return self
        raise sqlite3.ProgrammingError("forced")

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")

    def close(self) -> None:
        self.events.append("close")


class FailingConnection(TrackedConnection):
    def execute(self, sql: str):
        self.events.append(sql)
        raise sqlite3.ProgrammingError("forced")


@pytest.mark.parametrize(
    ("repository_cls", "owner_id", "expected"),
    [
        (
            TaskRepository,
            "owner-α",
            "Task storage failed while writing Task command 'owner-α'.",
        ),
        (
            OperationRepository,
            "owner-β",
            "Voice operation storage failed while writing Voice operation command 'owner-β'.",
        ),
    ],
)
def test_public_command_lock_preserves_exact_owner_error(
    repository_cls, owner_id: str, expected: str
) -> None:
    repository = repository_cls.__new__(repository_cls)
    repository._connect = lambda: FailingConnection()
    with pytest.raises(RepositoryError) as raised, repository.command_lock(owner_id):
        pass
    assert str(raised.value) == expected


@pytest.mark.parametrize("repository_cls", [TaskRepository, OperationRepository])
def test_public_command_lock_rolls_back_closes_and_restores_thread_state(
    repository_cls,
) -> None:
    repository = repository_cls.__new__(repository_cls)
    previous = object()
    repository._thread_state.conn = previous
    connection = TrackedConnection()
    repository._connect = lambda: connection
    with pytest.raises(KeyboardInterrupt), repository.command_lock("owner"):
        raise KeyboardInterrupt
    assert connection.events == ["BEGIN IMMEDIATE", "rollback", "close"]
    assert repository._thread_state.conn is previous


@pytest.mark.parametrize("repository_cls", [TaskRepository, OperationRepository])
def test_public_command_lock_commits_and_closes_on_success(repository_cls) -> None:
    repository = repository_cls.__new__(repository_cls)
    if hasattr(repository._thread_state, "conn"):
        del repository._thread_state.conn
    connection = TrackedConnection()
    repository._connect = lambda: connection
    with repository.command_lock("owner"):
        pass
    assert connection.events == ["BEGIN IMMEDIATE", "commit", "close"]
    assert repository._thread_state.conn is None


def test_connect_passes_explicit_timeout_and_autocommit(tmp_path: Path) -> None:
    repository = TinyRepository(tmp_path / "settings.sqlite3")
    with (
        patch(
            "app.repositories.sqlite.sqlite3.connect", wraps=sqlite3.connect
        ) as connect,
        repository._owned_connection(),
    ):
        pass
    connect.assert_called_once_with(
        repository.db_path, timeout=5.0, isolation_level=None
    )


def test_connection_settings_reuse_and_lifecycle(tmp_path: Path) -> None:
    repository = TinyRepository(tmp_path / "settings.sqlite3")
    previous = object()
    repository._thread_state.conn = previous
    with repository.command("owner"):
        first = repository._thread_state.conn
        assert first.row_factory is sqlite3.Row
        assert first.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert first.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert first.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        with repository._connection(repository._thread_state) as second:
            assert second is first
        assert first.in_transaction
    assert repository._thread_state.conn is previous


def test_command_commits_and_baseexception_rolls_back(tmp_path: Path) -> None:
    repository = TinyRepository(tmp_path / "transaction.sqlite3")
    with repository.command("owner"):
        connection = repository._thread_state.conn
        connection.execute("CREATE TABLE values_table (value INTEGER)")
        connection.execute("INSERT INTO values_table VALUES (1)")
    with sqlite3.connect(repository.db_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 1
        )
    with pytest.raises(KeyboardInterrupt), repository.command("owner"):
        repository._thread_state.conn.execute("INSERT INTO values_table VALUES (2)")
        raise KeyboardInterrupt
    with sqlite3.connect(repository.db_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 1
        )


def test_exact_sqlite_error_mappings_and_messages() -> None:
    with (
        pytest.raises(ConflictError) as conflict,
        SQLiteRepositorySupport.sqlite_guard("Tiny", "id", "unavailable", "failed"),
    ):
        raise sqlite3.IntegrityError("duplicate")
    assert conflict.value.resource == "Tiny" and conflict.value.identifier == "id"
    with (
        pytest.raises(StorageUnavailableError, match="unavailable"),
        SQLiteRepositorySupport.sqlite_guard("Tiny", "id", "unavailable", "failed"),
    ):
        raise sqlite3.OperationalError("busy")
    with (
        pytest.raises(RepositoryError, match="failed"),
        SQLiteRepositorySupport.sqlite_guard("Tiny", "id", "unavailable", "failed"),
    ):
        raise sqlite3.ProgrammingError("bad")


def test_different_subclasses_and_databases_are_independent(tmp_path: Path) -> None:
    entered = threading.Barrier(2)
    completed: list[str] = []

    def worker(repository: TinyRepository) -> None:
        with repository.command("owner"):
            entered.wait(1)
            completed.append(repository.db_path.name)

    one = threading.Thread(
        target=worker, args=(TinyRepository(tmp_path / "one.sqlite3"),)
    )
    two = threading.Thread(
        target=worker, args=(OtherRepository(tmp_path / "two.sqlite3"),)
    )
    one.start()
    two.start()
    one.join(2)
    two.join(2)
    assert not one.is_alive() and not two.is_alive()
    assert sorted(completed) == ["one.sqlite3", "two.sqlite3"]


def test_same_subclass_commands_serialize_with_bounded_threads(tmp_path: Path) -> None:
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_worker() -> None:
        with TinyRepository(tmp_path / "one.sqlite3").command("owner"):
            first_entered.set()
            release_first.wait(1)

    def second_worker() -> None:
        with TinyRepository(tmp_path / "two.sqlite3").command("owner"):
            second_entered.set()

    one = threading.Thread(target=first_worker)
    two = threading.Thread(target=second_worker)
    one.start()
    assert first_entered.wait(1)
    two.start()
    assert not second_entered.wait(0.1)
    release_first.set()
    one.join(2)
    two.join(2)
    assert not one.is_alive() and not two.is_alive()
    assert second_entered.is_set()
