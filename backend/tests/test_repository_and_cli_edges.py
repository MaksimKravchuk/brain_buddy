"""Regression tests for command and repository edge behaviour."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta

import allure
import pytest
from typer.testing import CliRunner

from app import cli
from app.exceptions import ConflictError, NotFoundError
from app.repositories import (
    InviteRepository,
    ProviderRepository,
    SessionRepository,
    UserRepository,
)
from app.schemas.api import TreeCreateRequest, VersionCreateRequest
from app.schemas.auth import Invite, Session, User
from app.schemas.domain import ProviderConfig


def test_create_invite_cli_persists_and_prints_a_one_shot_code(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_config", lambda: None)
    monkeypatch.setattr(cli, "build_container", lambda _config: container)

    result = CliRunner().invoke(cli.app, ["create-invite"])

    assert result.exit_code == 0
    code = result.stdout.strip()
    assert code
    assert container.invite_repo.get(code) is not None


def test_purge_due_accounts_cli_reports_purged_count(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_config", lambda: None)
    monkeypatch.setattr(cli, "build_container", lambda _config: container)
    user = User(
        id="user_cli_purge",
        email="cli-purge@example.com",
        password_hash="x",
        created_at=datetime.now(UTC),
        deletion_requested_at=datetime.now(UTC) - timedelta(days=15),
    )
    container.user_repo.create(user)

    result = CliRunner().invoke(cli.app, ["purge-due-accounts"])

    assert result.exit_code == 0
    assert "Purged 1 account(s)." in result.stdout
    assert container.user_repo.get_by_id("user_cli_purge") is None


def test_provider_registry_round_trips_default_and_provider_config(data_dir) -> None:
    repository = ProviderRepository(data_dir)

    assert repository.load().providers == {}
    configured = repository.upsert_provider("local", ProviderConfig(model="test-model"))
    defaulted = repository.set_default_provider("local")

    assert configured.providers["local"].model == "test-model"
    assert defaulted.default_provider == "local"
    assert repository.load().providers["local"].model == "test-model"


def test_invite_repository_rejects_duplicate_and_consumed_or_unknown_codes(
    data_dir,
) -> None:
    repository = InviteRepository(data_dir)
    invite = Invite(code="once", created_at=datetime.now(UTC))
    repository.create(invite)

    with pytest.raises(ConflictError):
        repository.create(invite)
    with pytest.raises(NotFoundError):
        repository.mark_used("missing", user_id="user", used_at=datetime.now(UTC))

    consumed = repository.mark_used("once", user_id="user", used_at=datetime.now(UTC))

    assert consumed.is_used
    with pytest.raises(ConflictError):
        repository.mark_used("once", user_id="other", used_at=datetime.now(UTC))


def test_invite_repository_serializes_competing_consumers_across_instances(
    data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = InviteRepository(data_dir)
    second = InviteRepository(data_dir)
    invite = Invite(code="thread-race", created_at=datetime.now(UTC))
    first.create(invite)

    first_save_started = threading.Event()
    release_first_save = threading.Event()
    second_read_started = threading.Event()
    original_first_save = first._save_unlocked
    original_second_get = second.get

    def pause_first_save(candidate: Invite) -> None:
        first_save_started.set()
        if not release_first_save.wait(timeout=5):
            raise TimeoutError("the first invite write was never released")
        original_first_save(candidate)

    def observe_second_read(code: str) -> Invite | None:
        second_read_started.set()
        return original_second_get(code)

    monkeypatch.setattr(first, "_save_unlocked", pause_first_save)
    monkeypatch.setattr(second, "get", observe_second_read)
    results: list[Invite | BaseException] = []

    def consume(repository: InviteRepository, user_id: str) -> None:
        try:
            results.append(
                repository.mark_used(
                    invite.code, user_id=user_id, used_at=datetime.now(UTC)
                )
            )
        except BaseException as exc:
            results.append(exc)

    first_thread = threading.Thread(target=consume, args=(first, "user-first"))
    second_thread = threading.Thread(target=consume, args=(second, "user-second"))
    first_thread.start()
    try:
        assert first_save_started.wait(timeout=5)
        second_thread.start()
        assert not second_read_started.wait(timeout=0.1)
    finally:
        release_first_save.set()
        first_thread.join(timeout=5)
        if second_thread.ident is not None:
            second_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    successes = [result for result in results if isinstance(result, Invite)]
    failures = [result for result in results if isinstance(result, ConflictError)]
    assert len(successes) == len(failures) == 1
    assert first.get(invite.code).used_by_user_id == successes[0].used_by_user_id


def test_invite_repository_serializes_consumption_across_processes(
    data_dir, tmp_path
) -> None:
    repository = InviteRepository(data_dir)
    invite = Invite(code="process-race", created_at=datetime.now(UTC))
    repository.create(invite)

    first_ready = tmp_path / "first-ready"
    second_attempted = tmp_path / "second-attempted"
    second_read = tmp_path / "second-read"
    release_first = tmp_path / "release-first"
    first_result = tmp_path / "first-result"
    second_result = tmp_path / "second-result"
    first_script = """
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from app.repositories import InviteRepository

root, ready, release, result = map(Path, sys.argv[1:])
repository = InviteRepository(root)
save = repository._save_unlocked
def pause_save(invite):
    ready.touch()
    deadline = time.monotonic() + 5
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not release.exists():
        raise TimeoutError("parent did not release the first invite write")
    save(invite)
repository._save_unlocked = pause_save
try:
    repository.mark_used(
        "process-race", user_id="user-first", used_at=datetime.now(UTC)
    )
    result.write_text("success", encoding="utf-8")
except Exception as exc:
    result.write_text(type(exc).__name__, encoding="utf-8")
"""
    second_script = """
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from app.exceptions import ConflictError
from app.repositories import InviteRepository

root, attempted, read, result = map(Path, sys.argv[1:])
repository = InviteRepository(root)
get = repository.get
def observe_get(code):
    read.touch()
    return get(code)
repository.get = observe_get
attempted.touch()
try:
    repository.mark_used(
        "process-race", user_id="user-second", used_at=datetime.now(UTC)
    )
    result.write_text("success", encoding="utf-8")
except ConflictError:
    result.write_text("conflict", encoding="utf-8")
"""

    first_process = (
        subprocess.Popen(  # noqa: S603 - fixed interpreter and inline test script
            [
                sys.executable,
                "-c",
                first_script,
                str(data_dir),
                str(first_ready),
                str(release_first),
                str(first_result),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    )
    second_process = None
    try:
        deadline = time.monotonic() + 5
        while not first_ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert first_ready.exists()
        second_process = (
            subprocess.Popen(  # noqa: S603 - fixed interpreter and inline test script
                [
                    sys.executable,
                    "-c",
                    second_script,
                    str(data_dir),
                    str(second_attempted),
                    str(second_read),
                    str(second_result),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
        deadline = time.monotonic() + 5
        while not second_attempted.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert second_attempted.exists()
        deadline = time.monotonic() + 0.2
        while not second_read.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not second_read.exists()
    finally:
        release_first.touch()

    first_stdout, first_stderr = first_process.communicate(timeout=5)
    assert first_process.returncode == 0, f"{first_stdout}\n{first_stderr}"
    assert second_process is not None
    second_stdout, second_stderr = second_process.communicate(timeout=5)
    assert second_process.returncode == 0, f"{second_stdout}\n{second_stderr}"
    assert first_result.read_text(encoding="utf-8") == "success"
    assert second_result.read_text(encoding="utf-8") == "conflict"
    assert second_read.exists()


def test_invite_repository_releases_lock_after_write_failure(
    data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = InviteRepository(data_dir)
    second = InviteRepository(data_dir)
    invite = Invite(code="write-failure", created_at=datetime.now(UTC))
    first.create(invite)

    def fail_save(_invite: Invite) -> None:
        raise OSError("disk full")

    with monkeypatch.context() as patcher:
        patcher.setattr(first, "_save_unlocked", fail_save)
        with pytest.raises(OSError, match="disk full"):
            first.mark_used(
                invite.code, user_id="user-first", used_at=datetime.now(UTC)
            )

    finished = threading.Event()
    failures: list[BaseException] = []

    def consume_after_failure() -> None:
        try:
            second.mark_used(
                invite.code, user_id="user-second", used_at=datetime.now(UTC)
            )
        except BaseException as exc:
            failures.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=consume_after_failure)
    worker.start()
    worker.join(timeout=5)

    assert finished.is_set()
    assert not worker.is_alive()
    assert not failures
    assert second.get(invite.code).used_by_user_id == "user-second"


@allure.epic("Authentication & Access")
@allure.feature("Identity storage")
@allure.story("023-FR-002: canonical session expiry preserves other sessions")
def test_session_repository_removes_expired_sessions_and_ignores_missing_delete(
    data_dir,
) -> None:
    repository = SessionRepository(data_dir)
    now = datetime.now(UTC)
    UserRepository(data_dir, repository.store).create(
        User(id="user", email="owner@example.com", password_hash="hash", created_at=now)
    )
    expired = Session(
        token_hash="expired",
        user_id="user",
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    repository.create(expired)
    valid = expired.model_copy(
        update={"token_hash": "valid", "expires_at": now + timedelta(hours=1)}
    )
    repository.create(valid)
    with repository.store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 2

    assert repository.get(expired.token_hash) is None
    with repository.store.connection() as connection:
        assert (
            connection.execute("SELECT token_hash FROM sessions").fetchall()[0][0]
            == valid.token_hash
        )
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    repository.delete("already-missing")
    assert repository.get(valid.token_hash) == valid


@allure.epic("Authentication & Access")
@allure.feature("Identity storage")
@allure.story("023-FR-002: legacy email normalization survives reopening")
def test_user_repository_normalizes_canonical_sqlite_record_and_payload(
    data_dir,
) -> None:
    repository = UserRepository(data_dir)
    now = datetime.now(UTC)
    user = User(
        id="user_1",
        email="  USER@EXAMPLE.COM ",
        password_hash="hash",
        created_at=now,
    )

    assert repository.get_by_id("missing") is None
    created = repository.create(user)

    assert created.email == "user@example.com"
    assert repository.get_by_email("USER@example.com") == created
    with repository.store.connection() as connection:
        row = connection.execute(
            "SELECT email,payload_json FROM users WHERE id=?", (created.id,)
        ).fetchone()
    assert row["email"] == "user@example.com"
    assert json.loads(row["payload_json"])["email"] == row["email"]
    assert UserRepository(data_dir).get_by_email(" USER@example.com ") == created
    with pytest.raises(ConflictError):
        repository.create(user)


def test_version_repository_rejects_missing_snapshot_and_deletes_existing_one(
    tree_service, version_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Version repository"), owner_id="owner"
    )
    version = version_service.create_version(
        tree.id, VersionCreateRequest(label="before delete")
    )
    repository = version_service.version_repo

    with pytest.raises(NotFoundError):
        repository.load(tree.id, "missing")

    repository.delete(tree.id, version.id)

    with pytest.raises(NotFoundError):
        repository.delete(tree.id, version.id)
