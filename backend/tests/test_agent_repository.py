"""Owner-scoped persistence for the external-agent relay module.

Covers the storage guarantees the service layer relies on: per-owner isolation,
atomic replay-identifier consumption, monotonic run versions, bounded retention,
and complete erasure under the account-purge contract (FR-015, AC-021).
"""

from __future__ import annotations

import gc
import hashlib
import json
import sqlite3
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from app.exceptions import ConflictError, NotFoundError, RepositoryError
from app.modules.agents.domain import (
    AgentAuditEntryDocument,
    AgentCapabilities,
    AgentConnectionDocument,
    AgentIdempotencyRecord,
    AgentRunCommandDocument,
    AgentRunDocument,
    AgentRunEventDocument,
)
from app.modules.agents.repository import EVENT_ID_RETENTION, AgentRepository
from app.modules.agents.secrets import SealedSecret

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def fingerprint(key_id: str, label: str) -> str:
    """A canonically shaped stored fingerprint: ``<key_id>:<64 hex MAC>``.

    The digest here is unkeyed because nothing in this layer verifies it; what
    matters to storage is the *shape* ``SecretBox.fingerprint`` writes, which is
    the only shape a stored row may be read back under.
    """

    return f"{key_id}:{hashlib.sha256(label.encode('utf-8')).hexdigest()}"


MAC = hashlib.sha256(b"k1").hexdigest()


@pytest.fixture
def repo(tmp_path: Path) -> AgentRepository:
    return AgentRepository(tmp_path)


def make_connection(
    *, owner_id: str = "user_a", connection_id: str = "agentconn_1", **overrides: object
) -> AgentConnectionDocument:
    payload: dict[str, object] = {
        "id": connection_id,
        "owner_id": owner_id,
        "name": "Hermes",
        "endpoint_url": "https://agent.example.com/hooks",
        "capabilities": AgentCapabilities(progress=True, reply=True, cancel=False),
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return AgentConnectionDocument.model_validate(payload)


QUERY_SECRET = "sk-live-smuggled-query-secret"  # noqa: S105 - fixture constant
SMUGGLED_ENDPOINT = f"https://agent.example.com/hooks?token={QUERY_SECRET}"
SMUGGLED_USERINFO_ENDPOINT = f"https://user:{QUERY_SECRET}@agent.example.com/hooks"
SMUGGLED_FRAGMENT_ENDPOINT = f"https://agent.example.com/hooks#{QUERY_SECRET}"
SMUGGLED_INVALID_ENDPOINT = f"https://[{QUERY_SECRET}/hooks"

INVALID_ENDPOINT_GRAMMAR = [
    "agent.example.com/hooks",
    "ftp://agent.example.com/hooks",
    "https:///hooks",
    "https://agent.example.com:0/hooks",
    "https://agent.example.com:65536/hooks",
    "https://agent.example.com:not-a-port/hooks",
    "https://user:secret@agent.example.com/hooks",
    "https://agent.example.com/hooks?",
    "https://agent.example.com/hooks#",
    "https://agent.example.com/ho\noks",
    "https://agent.example.com/ho\roks",
    "https://agent.example.com/ho\toks",
    "https://[broken/hooks",
]
ASCII_URL_CONTROLS = [*(chr(codepoint) for codepoint in range(0x20)), "\x7f"]


def bypass_endpoint_validation(
    connection: AgentConnectionDocument, endpoint_url: str, *, how: str
) -> AgentConnectionDocument:
    """Build a document the field validators would have refused.

    Both routes are ones ordinary service code reaches for: ``model_copy`` to
    apply an update, ``model_construct`` to skip validation on a value believed
    to be trusted already. Neither re-runs ``_reject_endpoint_query``.
    """

    if how == "model_copy":
        return connection.model_copy(update={"endpoint_url": endpoint_url})
    return AgentConnectionDocument.model_construct(
        **{**dict(connection), "endpoint_url": endpoint_url}
    )


def raw_connection_payloads(db_path: Path) -> dict[tuple[str, str], str]:
    """Every stored connection row, read past the model layer."""

    with closing(sqlite3.connect(db_path)) as conn:
        return {
            (str(row[0]), str(row[1])): str(row[2])
            for row in conn.execute(
                "SELECT owner_id, id, payload FROM agent_connections"
            )
        }


def database_bytes(db_path: Path) -> bytes:
    """The database and its write-ahead sidecars, so nothing hides in the WAL."""

    return b"".join(
        path.read_bytes() for path in sorted(db_path.parent.glob(f"{db_path.name}*"))
    )


def make_run(
    *,
    owner_id: str = "user_a",
    run_id: str = "agentrun_1",
    connection_id: str = "agentconn_1",
    task_id: str = "task_1",
    **overrides: object,
) -> AgentRunDocument:
    payload: dict[str, object] = {
        "id": run_id,
        "owner_id": owner_id,
        "connection_id": connection_id,
        "task_id": task_id,
        "agent_name": "Hermes",
        "content_expires_at": NOW + timedelta(days=30),
        "dispatched_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return AgentRunDocument.model_validate(payload)


class RepairBeforeBeginConnection:
    """Inject a concurrent repair immediately before the migration's write lock."""

    def __init__(self, connection: sqlite3.Connection, repository: RepairingRepository):
        self._connection = connection
        self._repository = repository

    def execute(
        self, sql: str, parameters: Any = (), /
    ) -> sqlite3.Cursor:  # pragma: no branch - one exact migration statement
        if sql.strip() == "BEGIN IMMEDIATE":
            self._repository.repair_if_armed()
        return self._connection.execute(sql, parameters)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()


class RepairingRepository(AgentRepository):
    """A startup racing a repair at the lock acquisition boundary.

    The wrapped connection applies the repair immediately before the migration
    takes its write lock. The real implementation locks before discovery and
    therefore reads the repaired row. A SELECT-before-BEGIN mutant first holds
    a stale row snapshot, then triggers the repair, and overwrites it.
    """

    def __init__(self, root: Path, *, replacement: AgentConnectionDocument) -> None:
        self._replacement = replacement
        self._replaced = False
        self._repair_armed = False
        super().__init__(root)

    def _migrate_legacy_invalid_connections(self, conn: sqlite3.Connection) -> None:
        wrapped = RepairBeforeBeginConnection(conn, self)
        super()._migrate_legacy_invalid_connections(cast(sqlite3.Connection, wrapped))

    def _migration_boundary(self, stage: str) -> None:
        if stage == "before_transaction":
            self._repair_armed = True

    def repair_if_armed(self) -> None:
        if not self._repair_armed or self._replaced:
            return
        self._repair_armed = False
        self._replaced = True
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE agent_connections SET status = ?, payload = ? "
                "WHERE owner_id = ? AND id = ?",
                (
                    self._replacement.status,
                    json.dumps(
                        self._replacement.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    self._replacement.owner_id,
                    self._replacement.id,
                ),
            )
            conn.commit()


class FailingMigrationRepository(AgentRepository):
    """A startup that dies after quarantining its first row."""

    def _migration_boundary(self, stage: str) -> None:
        if stage == "quarantined":
            raise RuntimeError("startup interrupted mid-quarantine")


def seed_malformed_connection(
    db_path: Path, *, owner_id: str, connection_id: str, payload: str
) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO agent_connections "
            "(owner_id, id, status, created_at, payload) VALUES (?, ?, ?, ?, ?)",
            (owner_id, connection_id, "ready", NOW.isoformat(), payload),
        )
        conn.commit()


class TestConnections:
    def test_repository_reports_whether_any_relay_records_exist(
        self, repo: AgentRepository
    ) -> None:
        """Startup can distinguish an empty schema from encrypted relay data."""

        assert repo.has_any_relay_data() is False
        repo.create_connection(make_connection())
        assert repo.has_any_relay_data() is True

    def test_repository_detects_relay_data_outside_the_connection_table(
        self, repo: AgentRepository
    ) -> None:
        """Bootstrap key checks also see durable audit data when no connection remains."""

        repo.append_audit(
            AgentAuditEntryDocument(
                id="audit_1",
                owner_id="user_a",
                action="connection_disconnected",
                outcome="confirmed",
                connection_id="agentconn_deleted",
                created_at=NOW,
            )
        )

        assert repo.list_connections(owner_id="user_a") == []
        assert repo.has_any_relay_data() is True

    def test_a_saved_connection_reads_back_for_its_owner(
        self, repo: AgentRepository
    ) -> None:
        """A created connection is retrievable by its owner."""

        repo.create_connection(make_connection())

        stored = repo.get_connection("agentconn_1", owner_id="user_a")
        assert stored.name == "Hermes"
        assert stored.capabilities.reply is True

    def test_another_owner_cannot_read_the_connection(
        self, repo: AgentRepository
    ) -> None:
        """Owner scoping is enforced in storage, not only in the service."""

        repo.create_connection(make_connection())

        with pytest.raises(NotFoundError):
            repo.get_connection("agentconn_1", owner_id="user_b")

    def test_creating_the_same_connection_id_twice_conflicts(
        self, repo: AgentRepository
    ) -> None:
        """A duplicate identifier is a conflict, never a silent overwrite."""

        repo.create_connection(make_connection())

        with pytest.raises(ConflictError):
            repo.create_connection(make_connection())

    def test_listing_returns_only_the_callers_connections(
        self, repo: AgentRepository
    ) -> None:
        """Listing never leaks another owner's agents."""

        repo.create_connection(make_connection())
        repo.create_connection(
            make_connection(owner_id="user_b", connection_id="agentconn_2")
        )

        listed = repo.list_connections(owner_id="user_a")
        assert [item.id for item in listed] == ["agentconn_1"]

    def test_saving_a_connection_persists_the_update(
        self, repo: AgentRepository
    ) -> None:
        """Updates round-trip through storage."""

        repo.create_connection(make_connection())
        stored = repo.get_connection("agentconn_1", owner_id="user_a")

        repo.save_connection(
            stored.model_copy(update={"status": "ready", "revision": 2})
        )

        assert repo.get_connection("agentconn_1", owner_id="user_a").status == "ready"

    @pytest.mark.parametrize(
        "endpoint_url",
        [
            "https://agent.example.com/hooks?token=secret",
            "https://agent.example.com/hooks?X-Amz-Signature=signed-secret",
            "https://agent.example.com/hooks?",
        ],
    )
    def test_query_string_endpoints_cannot_enter_persistence(
        self, repo: AgentRepository, endpoint_url: str
    ) -> None:
        """The storage model rejects endpoint queries before a row can be written."""

        with pytest.raises(ValueError):
            repo.create_connection(make_connection(endpoint_url=endpoint_url))

        assert repo.list_connections(owner_id="user_a") == []

    @pytest.mark.parametrize("endpoint_url", INVALID_ENDPOINT_GRAMMAR)
    def test_endpoint_grammar_is_rejected_before_persistence_and_export(
        self, repo: AgentRepository, endpoint_url: str
    ) -> None:
        """Only absolute HTTP(S) endpoints with a host and valid port are stored."""

        smuggled = bypass_endpoint_validation(
            make_connection(), endpoint_url, how="model_copy"
        )

        with pytest.raises(RepositoryError) as excinfo:
            repo.create_connection(smuggled)

        assert str(excinfo.value) == "Agent connection is not persistable."
        assert excinfo.value.__cause__ is None
        assert excinfo.value.__context__ is None
        assert raw_connection_payloads(repo.db_path) == {}
        assert repo.export_owner_data(owner_id="user_a", now=NOW)["connections"] == []

    @pytest.mark.parametrize("control", ASCII_URL_CONTROLS)
    @pytest.mark.parametrize("position", ["leading", "embedded", "trailing"])
    def test_every_literal_ascii_control_is_rejected_by_the_domain_model(
        self, control: str, position: str
    ) -> None:
        """C0 and DEL are invalid, rather than silently stripped or normalized."""

        endpoint_parts = {
            "leading": (control, "https://agent.example.com/hooks"),
            "embedded": ("https://agent.example.com/ho", control, "oks"),
            "trailing": ("https://agent.example.com/hooks", control),
        }

        with pytest.raises(ValueError) as excinfo:
            make_connection(endpoint_url="".join(endpoint_parts[position]))

        assert "agent endpoint is not a valid URL" in str(excinfo.value)

    def test_domain_validation_error_hides_the_rejected_endpoint_value(self) -> None:
        """Pydantic diagnostics preserve the constant reason, not a secret URL token."""

        secret = "domain" + "-port-secret"
        with pytest.raises(ValueError) as excinfo:
            make_connection(endpoint_url=f"https://agent.example.com:{secret}/hooks")

        assert "agent endpoint is not a valid URL" in str(excinfo.value)
        assert secret not in str(excinfo.value)
        assert secret not in repr(excinfo.value)

    @pytest.mark.parametrize("how", ["model_copy", "model_construct"])
    @pytest.mark.parametrize(
        "endpoint_url",
        [
            SMUGGLED_ENDPOINT,
            SMUGGLED_USERINFO_ENDPOINT,
            SMUGGLED_FRAGMENT_ENDPOINT,
            SMUGGLED_INVALID_ENDPOINT,
        ],
    )
    def test_create_refuses_a_connection_that_skipped_endpoint_validation(
        self, repo: AgentRepository, how: str, endpoint_url: str
    ) -> None:
        """Persistence re-validates; it does not trust the document it is handed."""

        smuggled = bypass_endpoint_validation(make_connection(), endpoint_url, how=how)
        assert smuggled.endpoint_url == endpoint_url

        with pytest.raises(RepositoryError) as excinfo:
            repo.create_connection(smuggled)

        assert raw_connection_payloads(repo.db_path) == {}
        assert repo.list_connections(owner_id="user_a") == []
        assert QUERY_SECRET not in database_bytes(repo.db_path).decode("latin-1")
        # The pydantic failure quotes the rejected URL, so it must not be
        # chained onto an error that is allowed to reach a log line.
        assert QUERY_SECRET not in str(excinfo.value)
        assert excinfo.value.__cause__ is None
        assert excinfo.value.__context__ is None

    @pytest.mark.parametrize("how", ["model_copy", "model_construct"])
    @pytest.mark.parametrize(
        "endpoint_url",
        [
            SMUGGLED_ENDPOINT,
            SMUGGLED_USERINFO_ENDPOINT,
            SMUGGLED_FRAGMENT_ENDPOINT,
            SMUGGLED_INVALID_ENDPOINT,
        ],
    )
    def test_update_with_a_smuggled_endpoint_leaves_the_row_untouched(
        self, repo: AgentRepository, how: str, endpoint_url: str
    ) -> None:
        """A rejected update is a no-op, not a partially applied one."""

        repo.create_connection(make_connection())
        before = raw_connection_payloads(repo.db_path)
        stored = repo.get_connection("agentconn_1", owner_id="user_a")
        smuggled = bypass_endpoint_validation(stored, endpoint_url, how=how)

        with pytest.raises(RepositoryError):
            repo.save_connection(smuggled.model_copy(update={"status": "ready"}))

        assert raw_connection_payloads(repo.db_path) == before
        assert repo.get_connection("agentconn_1", owner_id="user_a") == stored
        assert QUERY_SECRET not in database_bytes(repo.db_path).decode("latin-1")
        assert QUERY_SECRET not in json.dumps(
            repo.export_owner_data(owner_id="user_a", now=NOW)
        )

    @pytest.mark.parametrize("revision", ["not-a-number", None])
    def test_startup_repairs_invalid_legacy_header_with_safe_revision(
        self, tmp_path: Path, revision: object
    ) -> None:
        """Header-only legacy corruption is repaired even with a bad revision."""

        initial = AgentRepository(tmp_path)
        legacy = make_connection().model_dump(mode="json")
        legacy.update(auth_header_name="Host", revision=revision)
        with sqlite3.connect(initial.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_connections "
                "(owner_id, id, status, created_at, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    "user_a",
                    "agentconn_legacy",
                    "ready",
                    NOW.isoformat(),
                    json.dumps(legacy),
                ),
            )

        repaired = AgentRepository(tmp_path).get_connection(
            "agentconn_legacy", owner_id="user_a"
        )

        assert repaired.auth_header_name == "X-Agent-Key"
        assert repaired.revision == 2
        assert repaired.status == "untested"
        assert repaired.last_test_error_code == (
            "legacy_invalid_auth_header_requires_reconfiguration"
        )
        assert repaired.credential is None

    def test_startup_quarantines_malformed_connections_without_hiding_healthy_rows(
        self, tmp_path: Path
    ) -> None:
        """Every legacy row remains readable without reviving untrusted fields."""

        initial = AgentRepository(tmp_path)
        healthy_a = make_connection(connection_id="agentconn_healthy_a")
        healthy_b = make_connection(
            owner_id="user_b", connection_id="agentconn_healthy_b", name="Other agent"
        )
        initial.create_connection(healthy_a)
        initial.create_connection(healthy_b)
        malformed = {
            "agentconn_json": "not-json bearer-json-secret",
            "agentconn_array": json.dumps(["bearer-array-secret"]),
            "agentconn_fields": json.dumps(
                {
                    "id": "attacker-controlled-id",
                    "owner_id": "user_b",
                    "name": 123,
                    "endpoint_url": "https://agent.example.com/hooks?token=query-secret",
                    "auth_header_name": "Authorization\r\nX-Evil: yes",
                    "credential": "bearer-field-secret",
                    "inbound_secret": "inbound-field-secret",
                }
            ),
        }
        with sqlite3.connect(initial.db_path) as conn:
            for connection_id, payload in malformed.items():
                conn.execute(
                    "INSERT INTO agent_connections "
                    "(owner_id, id, status, created_at, payload) VALUES (?, ?, ?, ?, ?)",
                    ("user_a", connection_id, "ready", NOW.isoformat(), payload),
                )

        reopened = AgentRepository(tmp_path)
        listed_a = reopened.list_connections(owner_id="user_a")
        assert [connection.id for connection in listed_a] == [
            "agentconn_array",
            "agentconn_fields",
            "agentconn_healthy_a",
            "agentconn_json",
        ]
        assert reopened.list_connections(owner_id="user_b") == [healthy_b]
        assert (
            reopened.get_connection("agentconn_healthy_a", owner_id="user_a")
            == healthy_a
        )

        quarantined = [item for item in listed_a if item.id != healthy_a.id]
        assert {item.owner_id for item in quarantined} == {"user_a"}
        assert {item.status for item in quarantined} == {"untested"}
        assert {item.endpoint_url for item in quarantined} == {
            "https://reconfigure.invalid/"
        }
        assert {item.last_test_error_code for item in quarantined} == {
            "legacy_invalid_connection_requires_reconfiguration"
        }
        assert all(item.credential is None for item in quarantined)
        assert all(item.inbound_secret is None for item in quarantined)
        assert all(
            not any(item.capabilities.model_dump().values()) for item in quarantined
        )
        assert reopened.find_connection_anywhere(
            "agentconn_fields"
        ) == reopened.get_connection("agentconn_fields", owner_id="user_a")
        assert [
            item["id"]
            for item in reopened.export_owner_data(owner_id="user_a", now=NOW)[
                "connections"
            ]
        ] == [
            "agentconn_array",
            "agentconn_fields",
            "agentconn_healthy_a",
            "agentconn_json",
        ]

        first_reopen = [item.model_dump(mode="json") for item in listed_a]
        second_reopen = AgentRepository(tmp_path)
        assert [
            item.model_dump(mode="json")
            for item in second_reopen.list_connections(owner_id="user_a")
        ] == first_reopen
        with sqlite3.connect(second_reopen.db_path) as conn:
            stored_payloads = " ".join(
                row[0] for row in conn.execute("SELECT payload FROM agent_connections")
            )
        for secret in (
            "bearer-json-secret",
            "bearer-array-secret",
            "query-secret",
            "bearer-field-secret",
            "inbound-field-secret",
        ):
            assert secret not in stored_payloads

    def test_a_concurrent_repair_is_not_overwritten_by_a_stale_quarantine(
        self, tmp_path: Path
    ) -> None:
        """The scan's verdict is formed under the same lock that applies it."""

        initial = AgentRepository(tmp_path)
        healthy_a = make_connection(connection_id="agentconn_healthy_a")
        healthy_b = make_connection(
            owner_id="user_b", connection_id="agentconn_healthy_b", name="Other agent"
        )
        initial.create_connection(healthy_a)
        initial.create_connection(healthy_b)
        seed_malformed_connection(
            initial.db_path,
            owner_id="user_a",
            connection_id="agentconn_repaired",
            payload="not-json bearer-stale-secret",
        )
        seed_malformed_connection(
            initial.db_path,
            owner_id="user_b",
            connection_id="agentconn_still_broken",
            payload=json.dumps({"credential": "bearer-untouched-secret"}),
        )
        repaired = make_connection(
            connection_id="agentconn_repaired",
            name="Repaired by the other startup",
            endpoint_url="https://repaired.example.com/hooks",
            status="ready",
        )

        reopened = RepairingRepository(tmp_path, replacement=repaired)

        assert reopened.get_connection("agentconn_repaired", owner_id="user_a") == (
            repaired
        )
        assert (
            reopened.get_connection("agentconn_healthy_a", owner_id="user_a")
            == healthy_a
        )
        # The row that really is still broken is quarantined in the same pass,
        # and only for its own owner.
        quarantined = reopened.get_connection(
            "agentconn_still_broken", owner_id="user_b"
        )
        assert quarantined.owner_id == "user_b"
        assert quarantined.status == "untested"
        assert quarantined.endpoint_url == "https://reconfigure.invalid/"
        assert (
            quarantined.last_test_error_code
            == "legacy_invalid_connection_requires_reconfiguration"
        )
        assert [item.id for item in reopened.list_connections(owner_id="user_a")] == [
            "agentconn_healthy_a",
            "agentconn_repaired",
        ]
        assert [item.id for item in reopened.list_connections(owner_id="user_b")] == [
            "agentconn_healthy_b",
            "agentconn_still_broken",
        ]
        stored = " ".join(raw_connection_payloads(reopened.db_path).values())
        assert "bearer-stale-secret" not in stored
        assert "bearer-untouched-secret" not in stored

    def test_an_interrupted_migration_leaves_no_partial_quarantine(
        self, tmp_path: Path
    ) -> None:
        """Failure rolls the whole scan back, and the next startup redoes it."""

        initial = AgentRepository(tmp_path)
        initial.create_connection(make_connection(connection_id="agentconn_healthy_a"))
        for connection_id in ("agentconn_broken_1", "agentconn_broken_2"):
            seed_malformed_connection(
                initial.db_path,
                owner_id="user_a",
                connection_id=connection_id,
                payload=f"not-json {connection_id}",
            )
        before = raw_connection_payloads(initial.db_path)

        with pytest.raises(RuntimeError):
            FailingMigrationRepository(tmp_path)

        assert raw_connection_payloads(initial.db_path) == before

        retried = AgentRepository(tmp_path)
        assert {
            item.id: item.last_test_error_code
            for item in retried.list_connections(owner_id="user_a")
        } == {
            "agentconn_broken_1": (
                "legacy_invalid_connection_requires_reconfiguration"
            ),
            "agentconn_broken_2": (
                "legacy_invalid_connection_requires_reconfiguration"
            ),
            "agentconn_healthy_a": None,
        }


class TestRuns:
    def test_saving_a_run_persists_a_lifecycle_transition(
        self, repo: AgentRepository
    ) -> None:
        """A reserved run can be updated without replacing its reviewed identity."""

        repo.create_connection(make_connection())
        reserved = make_run()
        repo.create_run(reserved)
        dispatched = reserved.model_copy(
            update={
                "status": "working",
                "dispatched_at": NOW + timedelta(seconds=1),
                "updated_at": NOW + timedelta(seconds=1),
                "revision": reserved.revision + 1,
            }
        )

        repo.save_run(dispatched)

        assert repo.get_run(dispatched.id, owner_id=dispatched.owner_id) == dispatched

    def test_runs_are_listed_for_a_task_newest_first(
        self, repo: AgentRepository
    ) -> None:
        """Task detail shows every run, most recent first."""

        repo.create_connection(make_connection())
        repo.create_run(make_run(run_id="agentrun_1"))
        repo.create_run(
            make_run(run_id="agentrun_2", created_at=NOW + timedelta(minutes=5))
        )

        runs = repo.list_runs_for_task("task_1", owner_id="user_a")
        assert [run.id for run in runs] == ["agentrun_2", "agentrun_1"]

    def test_a_run_is_invisible_to_another_owner(self, repo: AgentRepository) -> None:
        """Cross-owner run reads fail closed."""

        repo.create_connection(make_connection())
        repo.create_run(make_run())

        with pytest.raises(NotFoundError):
            repo.get_run("agentrun_1", owner_id="user_b")
        assert repo.list_runs_for_task("task_1", owner_id="user_b") == []

    def test_creating_the_same_run_id_twice_conflicts(
        self, repo: AgentRepository
    ) -> None:
        """A duplicate run reservation cannot silently replace reviewed content."""

        repo.create_connection(make_connection())
        repo.create_run(make_run())

        with pytest.raises(ConflictError):
            repo.create_run(make_run())

    def test_listing_runs_for_an_owner_spans_every_task(
        self, repo: AgentRepository
    ) -> None:
        """The purge and retention sweeps need every run an owner holds."""

        repo.create_connection(make_connection())
        repo.create_run(make_run(run_id="agentrun_1", task_id="task_1"))
        repo.create_run(make_run(run_id="agentrun_2", task_id="task_2"))

        assert len(repo.list_runs_for_owner(owner_id="user_a")) == 2

    def test_latest_run_for_a_task_is_the_newest_one(
        self, repo: AgentRepository
    ) -> None:
        """The compact Task surface shows only the latest run."""

        repo.create_connection(make_connection())
        repo.create_run(make_run(run_id="agentrun_1"))
        repo.create_run(
            make_run(run_id="agentrun_2", created_at=NOW + timedelta(minutes=5))
        )

        latest = repo.latest_runs_by_task(owner_id="user_a", task_ids=["task_1"])
        assert latest["task_1"].id == "agentrun_2"

    def test_latest_runs_lookup_ignores_tasks_without_runs(
        self, repo: AgentRepository
    ) -> None:
        """A task with no hand-off simply has no entry."""

        assert repo.latest_runs_by_task(owner_id="user_a", task_ids=["task_9"]) == {}

    def test_latest_runs_lookup_accepts_an_empty_batch(
        self, repo: AgentRepository
    ) -> None:
        """Callers may skip a compact-summary query when no task IDs are visible."""

        assert repo.latest_runs_by_task(owner_id="user_a", task_ids=[]) == {}

    def test_an_undispatched_reservation_is_not_a_visible_run(
        self, repo: AgentRepository
    ) -> None:
        """Reviewing without confirming must not surface on the Task (AC-007)."""

        repo.create_connection(make_connection())
        repo.create_run(make_run(dispatched_at=None))

        assert repo.latest_runs_by_task(owner_id="user_a", task_ids=["task_1"]) == {}

    def test_abandoned_reservations_are_prunable(self, repo: AgentRepository) -> None:
        """Previews the user walked away from do not accumulate forever."""

        repo.create_connection(make_connection())
        repo.create_run(make_run(run_id="agentrun_kept"))
        repo.create_run(make_run(run_id="agentrun_abandoned", dispatched_at=None))

        assert repo.prune_undispatched_runs(before=NOW + timedelta(hours=1)) == 1
        assert [run.id for run in repo.list_runs_for_owner(owner_id="user_a")] == [
            "agentrun_kept"
        ]

    def test_a_reservation_never_expires_as_content(
        self, repo: AgentRepository
    ) -> None:
        """Retention counts real runs, not abandoned reviews."""

        repo.create_connection(make_connection())
        repo.create_run(
            make_run(dispatched_at=None, content_expires_at=NOW - timedelta(days=1))
        )

        assert repo.expire_due_content(now=NOW) == 0

    def test_a_run_is_findable_by_the_manifest_token_it_reserved(
        self, repo: AgentRepository
    ) -> None:
        """Confirmation resolves the exact reservation the review produced."""

        from app.modules.agents.domain import AgentReportingContract, AgentRunManifest

        manifest = AgentRunManifest(
            token="a" * 64,
            run_id="agentrun_1",
            task_id="task_1",
            connection_id="agentconn_1",
            agent_name="Hermes",
            title="Draft the plan",
            reporting=AgentReportingContract(
                callback_url="https://brainbuddy.example/api/agent-events",
                connection_id="agentconn_1",
            ),
            reporting_instructions="Report to the callback URL.",
        )
        repo.create_connection(make_connection())
        repo.create_run(make_run(manifest=manifest, dispatched_at=None))

        found = repo.find_run_by_manifest_token("a" * 64, owner_id="user_a")
        assert found is not None and found.id == "agentrun_1"
        assert repo.find_run_by_manifest_token("b" * 64, owner_id="user_a") is None
        assert repo.find_run_by_manifest_token("a" * 64, owner_id="user_b") is None

    def test_ownerless_connection_lookup_fails_closed_when_id_is_ambiguous(
        self, repo: AgentRepository
    ) -> None:
        """Inbound routing never chooses an arbitrary owner's signing secret."""

        repo.create_connection(
            make_connection(owner_id="user_a", connection_id="shared")
        )
        repo.create_connection(
            make_connection(owner_id="user_b", connection_id="shared")
        )

        assert repo.find_connection_anywhere("shared") is None

    def test_a_connection_is_resolvable_without_an_owner_for_inbound_events(
        self, repo: AgentRepository
    ) -> None:
        """Inbound events identify their owner through the connection."""

        repo.create_connection(make_connection())

        found = repo.find_connection_anywhere("agentconn_1")
        assert found is not None and found.owner_id == "user_a"
        assert repo.find_connection_anywhere("agentconn_missing") is None


class TestEventReplayConsumption:
    def test_expired_event_ids_are_purged(self, repo: AgentRepository) -> None:
        repo.create_connection(make_connection())
        repo.consume_event_id(
            owner_id="user_a",
            connection_id="agentconn_1",
            event_id="evt_old",
            now=NOW - EVENT_ID_RETENTION - timedelta(seconds=1),
        )

        assert repo.purge_expired_event_ids(now=NOW) == 1

    def test_a_fresh_event_id_is_consumed_once(self, repo: AgentRepository) -> None:
        """The first sighting of an event ID wins."""

        repo.create_connection(make_connection())

        assert (
            repo.consume_event_id(
                owner_id="user_a",
                connection_id="agentconn_1",
                event_id="evt_1",
                now=NOW,
            )
            is True
        )

    def test_a_replayed_event_id_is_refused(self, repo: AgentRepository) -> None:
        """A duplicate delivery is rejected atomically, before any mutation."""

        repo.create_connection(make_connection())
        repo.consume_event_id(
            owner_id="user_a", connection_id="agentconn_1", event_id="evt_1", now=NOW
        )

        assert (
            repo.consume_event_id(
                owner_id="user_a",
                connection_id="agentconn_1",
                event_id="evt_1",
                now=NOW,
            )
            is False
        )

    def test_the_same_event_id_on_a_different_connection_is_independent(
        self, repo: AgentRepository
    ) -> None:
        """Replay identifiers are scoped to the connection that signed them."""

        repo.create_connection(make_connection())
        repo.create_connection(make_connection(connection_id="agentconn_2"))
        repo.consume_event_id(
            owner_id="user_a", connection_id="agentconn_1", event_id="evt_1", now=NOW
        )

        assert (
            repo.consume_event_id(
                owner_id="user_a",
                connection_id="agentconn_2",
                event_id="evt_1",
                now=NOW,
            )
            is True
        )

    def test_appended_events_come_back_in_chronological_order(
        self, repo: AgentRepository
    ) -> None:
        """The run timeline is ordered by the connector's authoritative version."""

        repo.create_connection(make_connection())
        repo.create_run(make_run())
        for version, event_id in ((2, "evt_b"), (1, "evt_a"), (3, "evt_c")):
            repo.append_event(
                AgentRunEventDocument(
                    id=event_id,
                    owner_id="user_a",
                    run_id="agentrun_1",
                    connection_id="agentconn_1",
                    type="running",
                    run_version=version,
                    received_at=NOW,
                )
            )

        events = repo.list_events("agentrun_1", owner_id="user_a")
        assert [event.id for event in events] == ["evt_a", "evt_b", "evt_c"]


class TestCommandsAndAudit:
    def test_commands_round_trip_and_are_owner_scoped(
        self, repo: AgentRepository
    ) -> None:
        """A reply/cancel command is retrievable and confirmable."""

        repo.create_connection(make_connection())
        repo.create_run(make_run())
        repo.save_command(
            AgentRunCommandDocument(
                id="agentcmd_1",
                owner_id="user_a",
                run_id="agentrun_1",
                kind="reply",
                body="Use the staging database.",
                created_at=NOW,
            )
        )

        commands = repo.list_commands("agentrun_1", owner_id="user_a")
        assert [command.id for command in commands] == ["agentcmd_1"]
        assert repo.get_command("agentcmd_1", owner_id="user_a") == commands[0]
        assert repo.get_command("agentcmd_missing", owner_id="user_a") is None
        assert repo.list_commands("agentrun_1", owner_id="user_b") == []

    def test_audit_entries_are_listed_newest_first(self, repo: AgentRepository) -> None:
        """The audit trail reads as a timeline."""

        for index, action in enumerate(("connection_created", "run_dispatched")):
            repo.append_audit(
                AgentAuditEntryDocument(
                    id=f"agentaudit_{index}",
                    owner_id="user_a",
                    action=action,
                    outcome="ok",
                    created_at=NOW + timedelta(minutes=index),
                )
            )

        entries = repo.list_audit(owner_id="user_a")
        assert [entry.action for entry in entries] == [
            "run_dispatched",
            "connection_created",
        ]


class _FailingRetentionRepository(AgentRepository):
    def __init__(self, root: Path, *, fail_after: str) -> None:
        self.fail_after = fail_after
        super().__init__(root)

    def _retention_mutation_boundary(self, boundary: str) -> None:
        if boundary == self.fail_after:
            raise RuntimeError(f"injected retention failure: {boundary}")


class _PausedRetentionRepository(AgentRepository):
    def __init__(self, root: Path) -> None:
        self.run_redacted = threading.Event()
        self.release_retention = threading.Event()
        super().__init__(root)

    def _retention_mutation_boundary(self, boundary: str) -> None:
        if boundary == "run":
            self.run_redacted.set()
            assert self.release_retention.wait(timeout=5)


class TestRetentionAndPurge:
    def test_content_insert_reuses_the_outer_rollback_boundary(
        self, repo: AgentRepository
    ) -> None:
        """A nested child insert rolls back with its surrounding service command."""

        repo.create_connection(make_connection())
        repo.create_run(make_run(content_expired=True))

        with (
            pytest.raises(RuntimeError, match="cancel service failed"),
            repo.command_lock("user_a"),
        ):
            repo.append_event(
                AgentRunEventDocument(
                    id="evt_rolled_back",
                    owner_id="user_a",
                    run_id="agentrun_1",
                    connection_id="agentconn_1",
                    type="cancelled",
                    run_version=3,
                    received_at=NOW,
                    summary="must redact",
                )
            )
            raise RuntimeError("cancel service failed")

        assert repo.list_events("agentrun_1", owner_id="user_a") == []

    def test_failed_standalone_content_insert_rolls_back(
        self, repo: AgentRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A serialization failure cannot leave a transaction or partial child row open."""

        repo.create_connection(make_connection())
        repo.create_run(make_run())
        event = AgentRunEventDocument(
            id="evt_failed_insert",
            owner_id="user_a",
            run_id="agentrun_1",
            connection_id="agentconn_1",
            type="running",
            run_version=2,
            received_at=NOW,
            summary="sensitive summary",
        )
        original_payload = repo._payload

        def fail_payload(document: object) -> str:
            raise RuntimeError("serialization failed")

        monkeypatch.setattr(repo, "_payload", fail_payload)
        with pytest.raises(RuntimeError, match="serialization failed"):
            repo.append_event(event)

        monkeypatch.setattr(repo, "_payload", original_payload)
        assert repo.list_events("agentrun_1", owner_id="user_a") == []
        repo.append_event(event)
        assert [
            item.id for item in repo.list_events("agentrun_1", owner_id="user_a")
        ] == ["evt_failed_insert"]

    def test_content_insert_reuses_an_open_command_transaction(
        self, repo: AgentRepository
    ) -> None:
        """Service transactions keep event/version and cancellation writes atomic."""

        repo.create_connection(make_connection())
        repo.create_run(make_run(content_expired=True))
        with repo.command_lock("user_a"):
            repo.append_event(
                AgentRunEventDocument(
                    id="evt_transaction",
                    owner_id="user_a",
                    run_id="agentrun_1",
                    connection_id="agentconn_1",
                    type="cancelled",
                    run_version=3,
                    received_at=NOW,
                    summary="must redact",
                )
            )
            repo.save_command(
                AgentRunCommandDocument(
                    id="agentcmd_transaction",
                    owner_id="user_a",
                    run_id="agentrun_1",
                    kind="cancel",
                    body="must redact",
                    created_at=NOW,
                )
            )

        assert repo.list_events("agentrun_1", owner_id="user_a")[0].summary is None
        command = repo.get_command("agentcmd_transaction", owner_id="user_a")
        assert command is not None
        assert command.body is None

    @pytest.mark.parametrize("record_kind", ["event", "command"])
    def test_late_content_racing_expiry_is_atomically_redacted(
        self, tmp_path: Path, record_kind: str
    ) -> None:
        """An insert waiting behind expiry observes the committed expired state."""

        repo = _PausedRetentionRepository(tmp_path)
        repo.create_connection(make_connection())
        repo.create_run(make_run(content_expires_at=NOW - timedelta(seconds=1)))

        with ThreadPoolExecutor(max_workers=2) as pool:
            expiry = pool.submit(repo.expire_due_content, now=NOW)
            assert repo.run_redacted.wait(timeout=5)
            if record_kind == "event":
                insertion = pool.submit(
                    repo.append_event,
                    AgentRunEventDocument(
                        id="evt_racing",
                        owner_id="user_a",
                        run_id="agentrun_1",
                        connection_id="agentconn_1",
                        type="running",
                        run_version=2,
                        received_at=NOW,
                        summary="racing sensitive summary",
                    ),
                )
            else:
                insertion = pool.submit(
                    repo.save_command,
                    AgentRunCommandDocument(
                        id="agentcmd_racing",
                        owner_id="user_a",
                        run_id="agentrun_1",
                        kind="cancel",
                        body="racing sensitive command",
                        created_at=NOW,
                    ),
                )
            assert not insertion.done()
            repo.release_retention.set()
            assert expiry.result(timeout=5) == 1
            insertion.result(timeout=5)

        if record_kind == "event":
            assert repo.list_events("agentrun_1", owner_id="user_a")[0].summary is None
        else:
            command = repo.get_command("agentcmd_racing", owner_id="user_a")
            assert command is not None
            assert command.body is None

    @pytest.mark.parametrize("record_kind", ["event", "command"])
    def test_late_content_is_redacted_when_the_run_is_already_expired(
        self, repo: AgentRepository, record_kind: str
    ) -> None:
        """Direct repository callers cannot reintroduce content after expiry."""

        repo.create_connection(make_connection())
        repo.create_run(make_run(content_expired=True, result_text=None))
        if record_kind == "event":
            repo.append_event(
                AgentRunEventDocument(
                    id="evt_late",
                    owner_id="user_a",
                    run_id="agentrun_1",
                    connection_id="agentconn_1",
                    type="running",
                    run_version=2,
                    received_at=NOW,
                    summary="late sensitive summary",
                )
            )
            stored_content = repo.list_events("agentrun_1", owner_id="user_a")[
                0
            ].summary
        else:
            repo.save_command(
                AgentRunCommandDocument(
                    id="agentcmd_late",
                    owner_id="user_a",
                    run_id="agentrun_1",
                    kind="cancel",
                    body="late sensitive command",
                    created_at=NOW,
                )
            )
            stored = repo.get_command("agentcmd_late", owner_id="user_a")
            assert stored is not None
            stored_content = stored.body

        assert stored_content is None

    @pytest.mark.parametrize("boundary", ["run", "event", "command"])
    def test_expiry_rolls_back_every_sensitive_mutation_after_failure(
        self, tmp_path: Path, boundary: str
    ) -> None:
        """A crash at any mutation boundary leaves every content row untouched."""

        repo = _FailingRetentionRepository(tmp_path, fail_after=boundary)
        repo.create_connection(make_connection())
        repo.create_run(
            make_run(
                result_text="sensitive result",
                content_expires_at=NOW - timedelta(seconds=1),
            )
        )
        repo.append_event(
            AgentRunEventDocument(
                id="evt_1",
                owner_id="user_a",
                run_id="agentrun_1",
                connection_id="agentconn_1",
                type="running",
                run_version=1,
                received_at=NOW,
                summary="sensitive event",
            )
        )
        repo.save_command(
            AgentRunCommandDocument(
                id="agentcmd_1",
                owner_id="user_a",
                run_id="agentrun_1",
                kind="reply",
                body="sensitive reply",
                created_at=NOW,
            )
        )

        with pytest.raises(RuntimeError, match=f"failure: {boundary}"):
            repo.expire_due_content(now=NOW)

        reopened = AgentRepository(tmp_path)
        assert (
            reopened.get_run("agentrun_1", owner_id="user_a").result_text
            == "sensitive result"
        )
        assert (
            reopened.list_events("agentrun_1", owner_id="user_a")[0].summary
            == "sensitive event"
        )
        assert (
            reopened.list_commands("agentrun_1", owner_id="user_a")[0].body
            == "sensitive reply"
        )

    def test_expired_content_is_redacted_but_the_run_survives(
        self, repo: AgentRepository
    ) -> None:
        """After 30 days the relayed content goes; the run stays understandable."""

        repo.create_connection(make_connection())
        repo.create_run(
            make_run(
                progress_text="Reading the repo",
                result_text="Here is the answer",
                question_text="Which environment?",
                reported_state="running",
                content_expires_at=NOW - timedelta(seconds=1),
            )
        )

        expired = repo.expire_due_content(now=NOW)

        assert expired == 1
        run = repo.get_run("agentrun_1", owner_id="user_a")
        assert run.content_expired is True
        assert run.progress_text is None
        assert run.result_text is None
        assert run.question_text is None
        assert run.reported_state == "running"  # projection untouched

    def test_content_within_retention_is_left_alone(
        self, repo: AgentRepository
    ) -> None:
        """Nothing expires early."""

        repo.create_connection(make_connection())
        repo.create_run(make_run(result_text="Still fresh"))

        assert repo.expire_due_content(now=NOW) == 0
        assert (
            repo.get_run("agentrun_1", owner_id="user_a").result_text == "Still fresh"
        )

    def test_expiring_content_is_idempotent(self, repo: AgentRepository) -> None:
        """A second sweep does not re-report already-expired runs."""

        repo.create_connection(make_connection())
        repo.create_run(
            make_run(result_text="Gone", content_expires_at=NOW - timedelta(days=1))
        )
        repo.expire_due_content(now=NOW)

        assert repo.expire_due_content(now=NOW) == 0

    def test_expired_event_summaries_are_redacted_too(
        self, repo: AgentRepository
    ) -> None:
        """Timeline entries cannot outlive the content they quote."""

        repo.create_connection(make_connection())
        repo.create_run(make_run(content_expires_at=NOW - timedelta(days=1)))
        repo.append_event(
            AgentRunEventDocument(
                id="evt_1",
                owner_id="user_a",
                run_id="agentrun_1",
                connection_id="agentconn_1",
                type="running",
                run_version=1,
                received_at=NOW,
                summary="Cloning the repository",
            )
        )

        repo.expire_due_content(now=NOW)

        assert repo.list_events("agentrun_1", owner_id="user_a")[0].summary is None

    def test_expiry_leaves_already_content_free_events_unchanged(
        self, repo: AgentRepository
    ) -> None:
        """Retention handles status-only events without manufacturing content."""

        repo.create_connection(make_connection())
        repo.create_run(make_run(content_expires_at=NOW - timedelta(days=1)))
        event = AgentRunEventDocument(
            id="evt_status_only",
            owner_id="user_a",
            run_id="agentrun_1",
            connection_id="agentconn_1",
            type="accepted",
            run_version=1,
            received_at=NOW,
            summary=None,
        )
        repo.append_event(event)

        assert repo.expire_due_content(now=NOW) == 1
        assert repo.list_events("agentrun_1", owner_id="user_a") == [event]

    def test_audit_entries_are_purged_after_ninety_days(
        self, repo: AgentRepository
    ) -> None:
        """Audit metadata is bounded at 90 days."""

        repo.append_audit(
            AgentAuditEntryDocument(
                id="agentaudit_old",
                owner_id="user_a",
                action="connection_created",
                outcome="ok",
                created_at=NOW - timedelta(days=91),
            )
        )
        repo.append_audit(
            AgentAuditEntryDocument(
                id="agentaudit_new",
                owner_id="user_a",
                action="run_dispatched",
                outcome="ok",
                created_at=NOW - timedelta(days=89),
            )
        )

        assert repo.purge_expired_audit(now=NOW) == 1
        assert [entry.id for entry in repo.list_audit(owner_id="user_a")] == [
            "agentaudit_new"
        ]

    def test_export_projection_is_owner_scoped_redacted_and_excludes_receipts(
        self, repo: AgentRepository
    ) -> None:
        """GDPR export support exposes relay facts, never secrets or replay ledgers."""

        repo.create_connection(
            make_connection(
                credential={"key_id": "k1", "ciphertext": "credential-secret"},
                inbound_secret={"key_id": "k1", "ciphertext": "signing-secret"},
            )
        )
        from app.modules.agents.domain import AgentReportingContract, AgentRunManifest

        manifest = AgentRunManifest(
            token="a" * 64,
            run_id="agentrun_1",
            task_id="task_1",
            connection_id="agentconn_1",
            agent_name="Hermes",
            title="private task title",
            details="private task details",
            reporting=AgentReportingContract(
                callback_url="https://brainbuddy.example/api/agent-events",
                connection_id="agentconn_1",
            ),
            reporting_instructions="private reporting instructions",
        )
        repo.create_run(
            make_run(
                manifest=manifest,
                progress_text="private progress",
                question_text="private question",
                result_text="private result",
                result_link="https://agent.example.com/private-result",
                failure_reason="private failure",
            )
        )
        repo.append_event(
            AgentRunEventDocument(
                id="evt_1",
                owner_id="user_a",
                run_id="agentrun_1",
                connection_id="agentconn_1",
                type="running",
                run_version=1,
                received_at=NOW,
                summary="private event",
            )
        )
        repo.save_command(
            AgentRunCommandDocument(
                id="agentcmd_1",
                owner_id="user_a",
                run_id="agentrun_1",
                kind="reply",
                body="private reply",
                created_at=NOW,
            )
        )
        repo.save_idempotency(owner_id="user_a", record=make_idempotency())
        repo.create_connection(
            make_connection(owner_id="user_b", connection_id="other")
        )

        exported = repo.export_owner_data(owner_id="user_a", now=NOW)
        encoded = json.dumps(exported, sort_keys=True)

        assert [item["id"] for item in exported["connections"]] == ["agentconn_1"]
        assert [item["id"] for item in exported["runs"]] == ["agentrun_1"]
        assert [item["id"] for item in exported["events"]] == ["evt_1"]
        assert [item["id"] for item in exported["commands"]] == ["agentcmd_1"]
        assert "credential" not in exported["connections"][0]
        assert "inbound_secret" not in exported["connections"][0]
        run = exported["runs"][0]
        assert run["manifest"]["title"] == "private task title"
        assert run["manifest"]["details"] == "private task details"
        assert run["manifest"]["reporting_instructions"] == (
            "private reporting instructions"
        )
        assert run["progress_text"] == "private progress"
        assert run["question_text"] == "private question"
        assert run["result_text"] == "private result"
        assert run["result_link"] == "https://agent.example.com/private-result"
        assert run["failure_reason"] == "private failure"
        assert exported["events"][0]["summary"] == "private event"
        assert exported["commands"][0]["body"] == "private reply"
        assert "idempotency" not in exported
        for sensitive in (
            "credential-secret",
            "signing-secret",
            fingerprint("kid-1", "k1"),
            "other",
        ):
            assert sensitive not in encoded

    def test_export_redacts_due_unswept_content_without_mutating_storage(
        self, repo: AgentRepository
    ) -> None:
        from app.modules.agents.domain import AgentReportingContract, AgentRunManifest

        repo.create_connection(make_connection())
        manifest = AgentRunManifest(
            token="a" * 64,
            run_id="agentrun_1",
            task_id="task_1",
            connection_id="agentconn_1",
            agent_name="Hermes",
            title="expired title",
            details="expired details",
            reporting=AgentReportingContract(
                callback_url="https://brainbuddy.example/api/agent-events",
                connection_id="agentconn_1",
            ),
            reporting_instructions="expired reporting instructions",
        )
        repo.create_run(
            make_run(
                manifest=manifest,
                progress_text="expired progress",
                question_text="expired question",
                result_text="expired result",
                result_link="https://agent.example.com/expired-result",
                failure_reason="expired failure",
                content_expires_at=NOW,
            )
        )
        repo.append_event(
            AgentRunEventDocument(
                id="evt_expired",
                owner_id="user_a",
                run_id="agentrun_1",
                connection_id="agentconn_1",
                type="running",
                run_version=1,
                received_at=NOW - timedelta(days=31),
                summary="expired event",
            )
        )
        repo.save_command(
            AgentRunCommandDocument(
                id="agentcmd_expired",
                owner_id="user_a",
                run_id="agentrun_1",
                kind="reply",
                body="expired reply",
                created_at=NOW - timedelta(days=31),
            )
        )
        exported = repo.export_owner_data(owner_id="user_a", now=NOW)
        serialized = json.dumps(exported, sort_keys=True)

        assert exported["runs"][0]["content_expired"] is True
        for field in (
            "manifest",
            "progress_text",
            "question_text",
            "result_text",
            "result_link",
            "failure_reason",
        ):
            assert exported["runs"][0][field] is None
        assert exported["events"][0]["summary"] is None
        assert exported["commands"][0]["body"] is None
        for sensitive in (
            "expired title",
            "expired details",
            "expired reporting instructions",
            "expired progress",
            "expired question",
            "expired result",
            "expired-result",
            "expired failure",
            "expired event",
            "expired reply",
        ):
            assert sensitive not in serialized

        stored = repo.get_run("agentrun_1", owner_id="user_a")
        assert stored.content_expired is False
        assert stored.manifest == manifest
        assert stored.progress_text == "expired progress"
        assert repo.list_events("agentrun_1", owner_id="user_a")[0].summary == (
            "expired event"
        )
        assert repo.list_commands("agentrun_1", owner_id="user_a")[0].body == (
            "expired reply"
        )

    def test_export_redacts_only_due_runs_for_the_requested_owner(
        self, repo: AgentRepository
    ) -> None:
        repo.create_connection(make_connection())
        repo.create_connection(
            make_connection(owner_id="user_b", connection_id="agentconn_b")
        )
        repo.create_run(
            make_run(
                run_id="agentrun_due",
                result_text="due owner-a result",
                content_expires_at=NOW - timedelta(microseconds=1),
            )
        )
        repo.create_run(
            make_run(
                run_id="agentrun_fresh",
                result_text="fresh owner-a result",
                content_expires_at=NOW + timedelta(microseconds=1),
            )
        )
        repo.create_run(
            make_run(
                run_id="agentrun_already_expired",
                result_text="must not be resurrected",
                content_expired=True,
                content_expires_at=NOW + timedelta(days=1),
            )
        )
        repo.create_run(
            make_run(
                owner_id="user_b",
                run_id="agentrun_other_due",
                connection_id="agentconn_b",
                result_text="due owner-b result",
                content_expires_at=NOW,
            )
        )

        exported = repo.export_owner_data(owner_id="user_a", now=NOW)

        assert [run["id"] for run in exported["runs"]] == [
            "agentrun_already_expired",
            "agentrun_due",
            "agentrun_fresh",
        ]
        assert exported["runs"][0]["content_expired"] is True
        assert exported["runs"][0]["result_text"] is None
        assert exported["runs"][1]["content_expired"] is True
        assert exported["runs"][1]["result_text"] is None
        assert exported["runs"][2]["content_expired"] is False
        assert exported["runs"][2]["result_text"] == "fresh owner-a result"
        assert "must not be resurrected" not in json.dumps(exported, sort_keys=True)
        assert "due owner-b result" not in json.dumps(exported, sort_keys=True)

    def test_export_projects_audit_retention_at_the_authoritative_now(
        self, repo: AgentRepository
    ) -> None:
        """Due-but-unswept audit is inaccessible without mutating the ledger."""

        for audit_id, created_at in (
            ("audit_due", NOW - timedelta(days=90)),
            ("audit_fresh", NOW - timedelta(days=90) + timedelta(microseconds=1)),
        ):
            repo.append_audit(
                AgentAuditEntryDocument(
                    id=audit_id,
                    owner_id="user_a",
                    action="run_dispatched",
                    outcome="ok",
                    created_at=created_at,
                )
            )
        repo.append_audit(
            AgentAuditEntryDocument(
                id="audit_other",
                owner_id="user_b",
                action="run_dispatched",
                outcome="ok",
                created_at=NOW,
            )
        )

        exported = repo.export_owner_data(owner_id="user_a", now=NOW)

        assert [entry["id"] for entry in exported["audit"]] == ["audit_fresh"]
        assert [entry.id for entry in repo.list_audit(owner_id="user_a")] == [
            "audit_fresh",
            "audit_due",
        ]

    def test_purging_an_owner_removes_every_record(self, repo: AgentRepository) -> None:
        """The account-purge contract leaves nothing behind (AC-021)."""

        repo.create_connection(make_connection())
        repo.create_run(make_run())
        repo.append_event(
            AgentRunEventDocument(
                id="evt_1",
                owner_id="user_a",
                run_id="agentrun_1",
                connection_id="agentconn_1",
                type="accepted",
                run_version=1,
                received_at=NOW,
            )
        )
        repo.save_command(
            AgentRunCommandDocument(
                id="agentcmd_1",
                owner_id="user_a",
                run_id="agentrun_1",
                kind="start",
                created_at=NOW,
            )
        )
        repo.append_audit(
            AgentAuditEntryDocument(
                id="agentaudit_1",
                owner_id="user_a",
                action="run_dispatched",
                outcome="ok",
                created_at=NOW,
            )
        )
        repo.consume_event_id(
            owner_id="user_a", connection_id="agentconn_1", event_id="evt_1", now=NOW
        )
        repo.create_connection(
            make_connection(owner_id="user_b", connection_id="agentconn_9")
        )

        repo.delete_all_for_owner(owner_id="user_a")

        assert repo.list_connections(owner_id="user_a") == []
        assert repo.list_runs_for_owner(owner_id="user_a") == []
        assert repo.list_audit(owner_id="user_a") == []
        assert repo.list_events("agentrun_1", owner_id="user_a") == []
        assert repo.list_commands("agentrun_1", owner_id="user_a") == []
        # The other owner is untouched.
        assert len(repo.list_connections(owner_id="user_b")) == 1

    def test_purge_is_safe_to_repeat(self, repo: AgentRepository) -> None:
        """An interrupted purge can simply run again."""

        repo.create_connection(make_connection())
        repo.delete_all_for_owner(owner_id="user_a")
        repo.delete_all_for_owner(owner_id="user_a")

        assert repo.list_connections(owner_id="user_a") == []


def make_idempotency(
    *,
    key_hash: str = fingerprint("kid-1", "k1"),
    command: str = "dispatch_run",
    request_hash: str = fingerprint("kid-1", "request-1"),
    resource_id: str = "agentrun_1",
    created_at: datetime = NOW,
    **overrides: object,
) -> AgentIdempotencyRecord:
    payload: dict[str, object] = {
        "key_hash": key_hash,
        "command": command,
        "request_hash": request_hash,
        "resource_id": resource_id,
        "response_body": {"id": resource_id},
        "created_at": created_at,
    }
    payload.update(overrides)
    return AgentIdempotencyRecord.model_validate(payload)


class TestIdempotency:
    def test_an_unseen_key_has_no_record(self, repo: AgentRepository) -> None:
        """A first-time command finds nothing to replay."""

        assert (
            repo.get_idempotency(
                owner_id="user_a", key_hashes=[fingerprint("kid-1", "k1")]
            )
            is None
        )

    def test_no_candidate_hashes_find_nothing(self, repo: AgentRepository) -> None:
        """An empty candidate set is a miss, never an unbounded query."""

        repo.save_idempotency(owner_id="user_a", record=make_idempotency())

        assert repo.get_idempotency(owner_id="user_a", key_hashes=[]) is None

    def test_a_stored_key_replays_its_original_result(
        self, repo: AgentRepository
    ) -> None:
        """A replayed command returns the original outcome, for that owner only."""

        repo.save_idempotency(owner_id="user_a", record=make_idempotency())

        record = repo.get_idempotency(
            owner_id="user_a", key_hashes=[fingerprint("kid-1", "k1")]
        )
        assert record is not None
        assert record.resource_id == "agentrun_1"
        assert record.completed is True
        assert (
            repo.get_idempotency(
                owner_id="user_b", key_hashes=[fingerprint("kid-1", "k1")]
            )
            is None
        )

    def test_storage_has_nowhere_to_put_a_raw_key(self, repo: AgentRepository) -> None:
        """The record cannot carry the key itself, so no writer can leak it."""

        assert "key" not in AgentIdempotencyRecord.model_fields

        record = make_idempotency(key="k1-raw-idempotency-key")
        repo.save_idempotency(owner_id="user_a", record=record)

        assert not hasattr(record, "key")
        assert b"k1-raw-idempotency-key" not in repo.db_path.read_bytes()

    def test_a_record_written_under_a_retired_key_is_still_found(
        self, repo: AgentRepository
    ) -> None:
        """Rotation keeps yesterday's row comparable while its key is configured."""

        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(key_hash=fingerprint("kid-0", "k1")),
        )

        record = repo.get_idempotency(
            owner_id="user_a",
            key_hashes=[fingerprint("kid-1", "k1"), fingerprint("kid-0", "k1")],
        )
        assert record is not None
        assert record.key_hash == fingerprint("kid-0", "k1")

    def test_live_sealed_references_report_connection_and_receipt_key_ids(
        self, repo: AgentRepository
    ) -> None:
        sealed_v1 = SealedSecret(key_id="kid-0", ciphertext="sealed")
        repo.create_connection(
            make_connection(credential=sealed_v1, inbound_secret=sealed_v1)
        )
        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(
                key_hash=fingerprint("kid-1", "k1"),
                response_body={
                    "sealed_signing_secret": sealed_v1.model_dump(mode="json")
                },
            ),
        )

        live = repo.live_sealed_key_ids(owner_id="user_a", now=NOW)

        assert live.key_ids == {"kid-0", "kid-1"}
        assert live.unreadable == 0

    def test_expired_receipt_releases_only_its_sealed_reference(
        self, repo: AgentRepository
    ) -> None:
        sealed_v1 = SealedSecret(key_id="kid-0", ciphertext="sealed")
        repo.create_connection(make_connection(credential=sealed_v1))
        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(
                key_hash=fingerprint("kid-1", "k1"),
                response_body={
                    "sealed_signing_secret": sealed_v1.model_dump(mode="json")
                },
                created_at=NOW - timedelta(hours=25),
            ),
        )

        live = repo.live_sealed_key_ids(owner_id="user_a", now=NOW)

        assert live.key_ids == {"kid-0"}
        assert live.unreadable == 0

    @pytest.mark.parametrize(
        ("table", "payload"),
        [
            ("agent_connections", {"credential": {"key_id": "bad key"}}),
            (
                "agent_idempotency",
                {"sealed_signing_secret": {"key_id": "bad key"}},
            ),
        ],
    )
    def test_malformed_sealed_key_ids_fail_closed_without_being_returned(
        self, repo: AgentRepository, table: str, payload: dict[str, object]
    ) -> None:
        with sqlite3.connect(repo.db_path) as database:
            if table == "agent_connections":
                database.execute(
                    "INSERT INTO agent_connections "
                    "(owner_id, id, status, created_at, payload) VALUES (?, ?, ?, ?, ?)",
                    ("user_a", "broken", "ready", NOW.isoformat(), json.dumps(payload)),
                )
            else:
                database.execute(
                    "INSERT INTO agent_idempotency "
                    "(owner_id, key_hash, command, request_hash, resource_id, "
                    "command_id, delivery_attempted, completed, response_body, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "user_a",
                        fingerprint("kid-1", "broken"),
                        "rotate_signing_secret",
                        fingerprint("kid-1", "request"),
                        "broken",
                        None,
                        0,
                        1,
                        json.dumps(payload),
                        NOW.isoformat(),
                    ),
                )

        live = repo.live_sealed_key_ids(owner_id="user_a", now=NOW)

        assert live.key_ids <= {"kid-1"}
        assert "bad key" not in live.key_ids
        assert live.unreadable == 1

    def test_sealed_reference_query_supports_global_multi_owner_guard(
        self, repo: AgentRepository
    ) -> None:
        repo.create_connection(
            make_connection(
                owner_id="user_b",
                credential=SealedSecret(key_id="kid-9", ciphertext="sealed"),
            )
        )

        assert repo.live_sealed_key_ids(owner_id="user_a", now=NOW).key_ids == set()
        assert repo.live_sealed_key_ids(owner_id="user_b", now=NOW).key_ids == {"kid-9"}
        assert repo.live_sealed_key_ids(now=NOW).key_ids == {"kid-9"}

    def test_live_records_report_the_key_ids_they_are_stored_under(
        self, repo: AgentRepository
    ) -> None:
        """Which keys still owe records is what makes a retirement checkable."""

        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(key_hash=fingerprint("kid-0", "k1")),
        )
        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(key_hash=fingerprint("kid-1", "k2")),
        )
        repo.save_idempotency(
            owner_id="user_b",
            record=make_idempotency(key_hash=fingerprint("kid-9", "k3")),
        )

        live = repo.live_idempotency_key_ids(owner_id="user_a", now=NOW)
        assert live.key_ids == {"kid-0", "kid-1"}
        assert live.unreadable == 0

    def test_an_expired_record_no_longer_holds_its_key_id_open(
        self, repo: AgentRepository
    ) -> None:
        """Retention is the whole precondition: past it, the key owes nothing."""

        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(
                key_hash=fingerprint("kid-0", "k1"),
                created_at=NOW - timedelta(hours=25),
            ),
        )
        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(key_hash=fingerprint("kid-1", "k2")),
        )

        live = repo.live_idempotency_key_ids(owner_id="user_a", now=NOW)
        assert live.key_ids == {"kid-1"}
        assert live.unreadable == 0

    def test_an_owner_with_no_records_holds_no_key_open(
        self, repo: AgentRepository
    ) -> None:
        """A quiet owner must never block a rotation on someone else's rows."""

        repo.save_idempotency(owner_id="user_b", record=make_idempotency())

        live = repo.live_idempotency_key_ids(owner_id="user_a", now=NOW)
        assert live.key_ids == frozenset()
        assert live.unreadable == 0

    @pytest.mark.parametrize(
        "key_hash",
        [
            "",
            "kid-1",
            "kid-1:",
            f":{MAC}",
            f"kid-1:{MAC[:-1]}",
            f"kid-1:{MAC}f",
            f"kid-1:{'z' * 64}",
            f"kid-1:{MAC.upper()}",
            f"kid-1:kid-2:{MAC}",
            f"kid-1:{MAC}:kid-2",
            f"kid-1: {MAC[:-1]}",
            f"kid 1:{MAC}",
            f"kid,1:{MAC}",
            f"kid\t1:{MAC}",
            f"clé:{MAC}",
            f"{'a' * 65}:{MAC}",
        ],
    )
    def test_a_malformed_live_fingerprint_is_reported_not_parsed(
        self, repo: AgentRepository, key_hash: str
    ) -> None:
        """A row that is not a fingerprint yields no key id, only a count.

        Taking the text before the first colon would turn ``v2`` or ``v2:`` into
        the key id ``v2`` — a configured one — and the caller would conclude the
        ring is intact when the row is in fact unreadable.
        """

        repo.save_idempotency(
            owner_id="user_a", record=make_idempotency(key_hash=key_hash)
        )

        live = repo.live_idempotency_key_ids(owner_id="user_a", now=NOW)
        assert live.key_ids == frozenset()
        assert live.unreadable == 1

    def test_a_malformed_row_does_not_hide_behind_a_well_formed_one(
        self, repo: AgentRepository
    ) -> None:
        """One readable row must not vouch for the rest of the owner's records."""

        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(key_hash=fingerprint("kid-1", "k1")),
        )
        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(key_hash="kid-1", resource_id="agentrun_2"),
        )

        live = repo.live_idempotency_key_ids(owner_id="user_a", now=NOW)
        assert live.key_ids == {"kid-1"}
        assert live.unreadable == 1

    def test_another_owners_malformed_row_is_not_this_owners_problem(
        self, repo: AgentRepository
    ) -> None:
        """Fail-closed is per owner: one corrupt row cannot stop the whole fleet."""

        repo.save_idempotency(
            owner_id="user_b", record=make_idempotency(key_hash=f"kid-1:{MAC[:10]}")
        )
        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(key_hash=fingerprint("kid-1", "k1")),
        )

        assert repo.live_idempotency_key_ids(owner_id="user_a", now=NOW).unreadable == 0
        assert repo.live_idempotency_key_ids(owner_id="user_b", now=NOW).unreadable == 1

    def test_an_expired_malformed_row_no_longer_blocks_anything(
        self, repo: AgentRepository
    ) -> None:
        """Retention decides here too: past it, an unreadable row is not live."""

        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(
                key_hash="kid-1:not-a-mac", created_at=NOW - timedelta(hours=25)
            ),
        )

        live = repo.live_idempotency_key_ids(owner_id="user_a", now=NOW)
        assert live.key_ids == frozenset()
        assert live.unreadable == 0

    def test_a_malformed_row_is_purged_like_any_other_expired_row(
        self, repo: AgentRepository
    ) -> None:
        """Retention cleanup reads no fingerprint, so nothing can get stuck."""

        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(
                key_hash="kid-1:not-a-mac", created_at=NOW - timedelta(hours=25)
            ),
        )

        assert repo.purge_expired_idempotency(owner_id="user_a", now=NOW) == 1
        assert repo.live_idempotency_key_ids(owner_id="user_a", now=NOW).unreadable == 0

    def test_a_reservation_keeps_its_command_id(self, repo: AgentRepository) -> None:
        """An uncompleted reservation survives to give a retry the same ID."""

        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(command_id="agentcmd_1", completed=False),
        )

        record = repo.get_idempotency(
            owner_id="user_a", key_hashes=[fingerprint("kid-1", "k1")]
        )
        assert record is not None
        assert record.command_id == "agentcmd_1"
        assert record.completed is False

    def test_expired_records_are_purged_for_every_owner(
        self, repo: AgentRepository
    ) -> None:
        """Retention is a promise about the rows, not about who is still active."""

        stale = NOW - timedelta(hours=25)
        repo.save_idempotency(
            owner_id="user_a", record=make_idempotency(created_at=stale)
        )
        repo.save_idempotency(
            owner_id="user_b",
            record=make_idempotency(
                key_hash=fingerprint("kid-1", "k2"), created_at=stale
            ),
        )
        repo.save_idempotency(
            owner_id="user_b",
            record=make_idempotency(key_hash=fingerprint("kid-1", "k3")),
        )

        assert repo.purge_all_expired_idempotency(now=NOW) == 2
        assert (
            repo.get_idempotency(
                owner_id="user_a", key_hashes=[fingerprint("kid-1", "k1")]
            )
            is None
        )
        assert (
            repo.get_idempotency(
                owner_id="user_b", key_hashes=[fingerprint("kid-1", "k3")]
            )
            is not None
        )

    def test_one_owners_expired_records_are_purged_alone(
        self, repo: AgentRepository
    ) -> None:
        """The per-owner sweep never reaches across the owner boundary."""

        stale = NOW - timedelta(hours=25)
        repo.save_idempotency(
            owner_id="user_a", record=make_idempotency(created_at=stale)
        )
        repo.save_idempotency(
            owner_id="user_b", record=make_idempotency(created_at=stale)
        )

        assert repo.purge_expired_idempotency(owner_id="user_a", now=NOW) == 1
        assert (
            repo.get_idempotency(
                owner_id="user_b", key_hashes=[fingerprint("kid-1", "k1")]
            )
            is not None
        )


class TestOperationSerialization:
    """007-FR-006: one idempotent intent runs alone, without a database writer.

    ``operation_lock`` is the seam that keeps a retried dispatch from starting
    the same work twice, so its first-insertion, reuse and mutual-exclusion
    behaviour is a durability guarantee rather than an implementation detail.
    """

    @staticmethod
    def _coordinate(
        repo: AgentRepository, owner_id: str, fingerprint: str
    ) -> tuple[str, str, str]:
        return (str(repo.db_path), owner_id, fingerprint)

    def test_007_FR_006_the_first_lock_for_an_intent_is_created_then_reused(
        self, repo: AgentRepository
    ) -> None:
        """A repeat of the same intent contends on the same lock object."""

        coordinate = self._coordinate(repo, "user_a", "fingerprint_a")
        assert coordinate not in AgentRepository._operation_locks

        with repo.operation_lock("user_a", "fingerprint_a"):
            created = AgentRepository._operation_locks[coordinate]

        # `created` is the only strong reference; the weak map must still find it.
        with repo.operation_lock("user_a", "fingerprint_a"):
            assert AgentRepository._operation_locks[coordinate] is created

    def test_007_FR_006_a_reentrant_lock_is_storable_and_renestable(
        self, repo: AgentRepository
    ) -> None:
        """The supported runtimes hold a re-entrant lock in the weak map."""

        # Registering the lock at all proves it is weak-referenceable here; if
        # threading.RLock stopped being so, this raises TypeError rather than
        # silently degrading.
        with repo.operation_lock("user_a", "fingerprint_a"):
            stored = AgentRepository._operation_locks[
                self._coordinate(repo, "user_a", "fingerprint_a")
            ]
            # Re-entering must not self-deadlock: one owner's nested call on the
            # same intent has to pass straight through. Acquired with a timeout
            # so a non-reentrant lock fails the test instead of hanging it.
            reentered = stored.acquire(timeout=0.5)
            if reentered:
                stored.release()

        assert reentered is True

        # The map is weak on purpose. Once the last strong reference to a lock
        # goes, its entry has to go with it, or a long-lived process keeps one
        # dead lock per intent it has ever served. Asserting the referent is
        # still reachable while `stored` holds it would prove nothing, so drop
        # the reference and watch the entry disappear instead.
        coordinate = self._coordinate(repo, "user_a", "fingerprint_a")
        observer = weakref.ref(stored)
        del stored
        gc.collect()

        assert observer() is None
        assert coordinate not in AgentRepository._operation_locks

    def test_007_FR_006_a_different_owner_or_intent_gets_its_own_lock(
        self, repo: AgentRepository
    ) -> None:
        """Owner and fingerprint both narrow the coordinate, so neither is noise."""

        with repo.operation_lock("user_a", "fingerprint_a"):
            mine = AgentRepository._operation_locks[
                self._coordinate(repo, "user_a", "fingerprint_a")
            ]
        with repo.operation_lock("user_a", "fingerprint_b"):
            other_intent = AgentRepository._operation_locks[
                self._coordinate(repo, "user_a", "fingerprint_b")
            ]
        with repo.operation_lock("user_b", "fingerprint_a"):
            other_owner = AgentRepository._operation_locks[
                self._coordinate(repo, "user_b", "fingerprint_a")
            ]

        assert mine is not other_intent
        assert mine is not other_owner
        assert other_intent is not other_owner

    def test_007_FR_006_one_intent_in_two_databases_is_not_serialized(
        self, tmp_path: Path
    ) -> None:
        """The lock map is process-wide, so the database has to narrow it too.

        Owner ids and fingerprints are only unique *within* a database. The map
        holding the locks is a class attribute shared by every repository in the
        process, so two databases that happen to mint the same pair — a test
        run, a per-tenant root, a restore staged beside the live file — would
        contend on one lock if the coordinate did not carry the database. That
        is silent: the work still completes, just one caller at a time, for
        intents that have nothing to do with each other.
        """

        first = AgentRepository(tmp_path / "first")
        second = AgentRepository(tmp_path / "second")
        assert first.db_path != second.db_path

        # Same owner, same fingerprint, different databases: the two critical
        # sections must be able to meet. A shared lock makes the rendezvous
        # unreachable, so the barrier times out and both sides report the miss
        # rather than the test hanging.
        rendezvous = threading.Barrier(2)

        def contend(repository: AgentRepository) -> tuple[object | None, bool]:
            with repository.operation_lock("user_a", "fingerprint_a"):
                observed = AgentRepository._operation_locks.get(
                    self._coordinate(repository, "user_a", "fingerprint_a")
                )
                try:
                    rendezvous.wait(timeout=5)
                except threading.BrokenBarrierError:
                    return observed, False
                return observed, True

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(contend, repository) for repository in (first, second)
            ]
            results = [future.result(timeout=10) for future in futures]

        assert [met for _lock, met in results] == [True, True]

        # Each database registered its own lock under its own coordinate. Held
        # from inside the critical sections, so the weak map cannot have dropped
        # them before the comparison.
        (mine, _), (theirs, _) = results
        assert mine is not None
        assert theirs is not None
        assert mine is not theirs

    def test_007_FR_006_two_threads_on_one_intent_never_overlap(
        self, repo: AgentRepository
    ) -> None:
        """A second thread waits outside, so a replay cannot double-dispatch."""

        # Each thread tries to meet the other *inside* the critical section.
        # Under real mutual exclusion the rendezvous can never happen, so both
        # threads report being blocked; without it, both would pass straight
        # through the barrier.
        rendezvous = threading.Barrier(2)
        start = threading.Barrier(2)
        blocked: list[bool] = []
        overlap_guard = threading.Lock()
        inside = 0
        peak = 0

        def contend() -> None:
            nonlocal inside, peak
            start.wait(timeout=5)
            with repo.operation_lock("user_a", "fingerprint_a"):
                with overlap_guard:
                    inside += 1
                    peak = max(peak, inside)
                try:
                    rendezvous.wait(timeout=0.5)
                    blocked.append(False)
                except threading.BrokenBarrierError:
                    blocked.append(True)
                with overlap_guard:
                    inside -= 1

        threads = [threading.Thread(target=contend) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert [thread.is_alive() for thread in threads] == [False, False]
        assert blocked == [True, True]
        assert peak == 1

    def test_007_FR_006_unrelated_intents_are_not_serialized_against_each_other(
        self, repo: AgentRepository
    ) -> None:
        """Serialization is per intent, so unrelated work still runs together."""

        # The mirror image of the test above: two *different* coordinates must
        # be able to meet inside their critical sections. If the coordinate ever
        # collapsed to something coarser, this rendezvous would time out.
        rendezvous = threading.Barrier(2)
        met: list[bool] = []

        def contend(fingerprint: str) -> None:
            with repo.operation_lock("user_a", fingerprint):
                try:
                    rendezvous.wait(timeout=5)
                    met.append(True)
                except threading.BrokenBarrierError:
                    met.append(False)

        threads = [
            threading.Thread(target=contend, args=(fingerprint,))
            for fingerprint in ("fingerprint_a", "fingerprint_b")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert [thread.is_alive() for thread in threads] == [False, False]
        assert met == [True, True]


class TestCommandCheckpoint:
    """007-FR-006: what a checkpoint lands must outlive the command that fails."""

    def test_007_FR_006_a_checkpoint_survives_a_later_rollback(
        self, repo: AgentRepository
    ) -> None:
        """A reservation on disk before dispatch is not undone by the failure."""

        with pytest.raises(RuntimeError), repo.command_lock("user_a"):
            repo.create_connection(make_connection())
            repo.commit_checkpoint()
            repo.create_run(make_run())
            raise RuntimeError("dispatch failed after the reservation landed")

        assert repo.get_connection("agentconn_1", owner_id="user_a").name == "Hermes"
        # Everything written after the checkpoint reopened its transaction is
        # still rolled back, so the checkpoint is a boundary and not a switch
        # into autocommit.
        with pytest.raises(NotFoundError):
            repo.get_run("agentrun_1", owner_id="user_a")

    def test_007_FR_006_a_checkpoint_leaves_the_command_able_to_keep_writing(
        self, repo: AgentRepository
    ) -> None:
        """The reopened transaction still commits normally on the happy path."""

        with repo.command_lock("user_a"):
            repo.create_connection(make_connection())
            repo.commit_checkpoint()
            repo.create_run(make_run())

        assert repo.get_connection("agentconn_1", owner_id="user_a").name == "Hermes"
        assert repo.get_run("agentrun_1", owner_id="user_a").agent_name == "Hermes"

    def test_007_FR_006_a_checkpoint_outside_a_command_is_a_no_op(
        self, repo: AgentRepository
    ) -> None:
        """Nothing is open to land, so the call neither fails nor opens one."""

        repo.commit_checkpoint()

        with repo.command_lock("user_a"):
            repo.create_connection(make_connection())
        assert repo.get_connection("agentconn_1", owner_id="user_a").name == "Hermes"
