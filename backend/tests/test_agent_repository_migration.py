"""The one-way migration off the bespoke relay wire (spec 014, FR-012, SC-010).

Feature 007 shipped a BrainBuddy-invented HTTP contract: the connector was
called at an endpoint of our choosing and reported back to `/agent-events` with
an HMAC signed by a shared inbound secret. Feature 014 replaces all of it with
A2A. A record configured against the old wire cannot be carried forward — its
credential is scoped to an endpoint this build will never call again, and its
inbound secret authorises a route that no longer exists.

So the migration does the only honest thing available to it. It does not leave
the connection looking usable, because a hand-off on it could not work; it does
not delete it, because the owner configured it and is entitled to see what
happened to it. It **disconnects** it with a reason that says why, destroys the
credentials that are now meaningless, and stamps the runs that were still in
flight so they stop claiming to be live.

That is irreversible, which is why the evidence here is deliberately blunt:
this suite is what `quickstart.md` §9 and `docs/external-agent-relay-release.md`
point at before the 014 image is allowed near production data.

Three assertions in this module describe the *end* of the removal (the bespoke
routes, the bespoke module, and the refusal reason the API surfaces). They are
marked `xfail(strict=True)`: they are red until tasks T110–T115 delete the old
wire, and strict is the point — the day the removal lands they go from expected
failure to unexpected pass and this suite turns red until they are un-marked.
"""

from __future__ import annotations

import json
import sqlite3
from collections import OrderedDict
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.exceptions import ValidationFailure
from app.modules.agents.repository import A2A_WIRE_MIGRATION, AgentRepository
from app.modules.agents.secrets import SecretBox
from app.modules.agents.service import AgentRelayService
from app.schemas.agents import AgentHandoffPreviewRequest

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
OWNER = "user_a"
CONNECTION = "agentconn_1"

#: The five columns feature 014 adds to `agent_runs`, and the index over the
#: schedule column. Named here so the rewind below undoes exactly what the
#: migration does and nothing else.
A2A_RUN_COLUMNS = (
    "agent_task_id",
    "context_id",
    "next_observation_at",
    "exchange_state",
    "identifiers_expire_at",
)
A2A_RUN_INDEX = "idx_agent_runs_observation"
#: Columns 014 adds to the migration ledger so a migration can record what it
#: actually did. The 007 ledger held nothing but a name.
A2A_LEDGER_COLUMNS = ("rewritten_rows", "applied_at")


def pre_014_database(root: Path) -> Path:
    """A database in the shape the 007 image left behind.

    Built by letting the 014 repository create the schema and then *rewinding*
    the 014 parts of it, rather than by transcribing the 007 DDL into this
    file. A hand-copied schema drifts the moment the real one changes, and the
    drift would be silent in the worst way: the migration would keep passing
    against a shape production no longer has.
    """

    AgentRepository(root)
    db_path = root / "agents.sqlite3"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(f"DROP INDEX IF EXISTS {A2A_RUN_INDEX}")
        for column in A2A_RUN_COLUMNS:
            conn.execute(f"ALTER TABLE agent_runs DROP COLUMN {column}")
        for column in A2A_LEDGER_COLUMNS:
            conn.execute(f"ALTER TABLE agent_schema_migrations DROP COLUMN {column}")
        conn.execute(
            "DELETE FROM agent_schema_migrations WHERE name = ?", (A2A_WIRE_MIGRATION,)
        )
        conn.commit()
    return db_path


def bespoke_connection(
    *, owner_id: str = OWNER, connection_id: str = CONNECTION, **overrides: Any
) -> dict[str, Any]:
    """A connection payload as feature 007 wrote it: no `wire` key at all.

    The absence of the key *is* the signal. A pre-014 row cannot be recognised
    by its contents — every field it carries is one 014 still uses — so the
    migration selects on the one thing only the new build writes.
    """

    payload: dict[str, Any] = {
        "id": connection_id,
        "owner_id": owner_id,
        "name": "Hermes",
        "endpoint_url": "https://agent.example.com/hooks",
        "auth_header_name": "X-Agent-Key",
        "credential": {"key_id": "v1", "ciphertext": "sealed-outbound"},
        "inbound_secret": {"key_id": "v1", "ciphertext": "sealed-inbound"},
        "capabilities": {"progress": True, "reply": True, "cancel": False},
        "status": "ready",
        "last_contact_at": NOW.isoformat(),
        "last_tested_at": NOW.isoformat(),
        "scope_verified_at": NOW.isoformat(),
        "first_dispatch_at": NOW.isoformat(),
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "schema_version": 1,
        "revision": 3,
    }
    payload.update(overrides)
    return payload


def bespoke_run(
    *,
    owner_id: str = OWNER,
    run_id: str = "agentrun_1",
    connection_id: str = CONNECTION,
    **overrides: Any,
) -> dict[str, Any]:
    """A run payload as 007 wrote it, dispatched and still moving."""

    payload: dict[str, Any] = {
        "id": run_id,
        "owner_id": owner_id,
        "connection_id": connection_id,
        "task_id": "task_1",
        "agent_name": "Hermes",
        "dispatched_at": NOW.isoformat(),
        "dispatch_state": "sent",
        "reported_state": "running",
        "run_version": 4,
        "progress_text": "Halfway through",
        "content_expires_at": (NOW + timedelta(days=30)).isoformat(),
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }
    payload.update(overrides)
    return payload


def seed(
    db_path: Path,
    *,
    connections: list[dict[str, Any]] | None = None,
    runs: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> None:
    """Write raw rows past the model layer, as another image would have."""

    with closing(sqlite3.connect(db_path)) as conn:
        for payload in connections or []:
            conn.execute(
                "INSERT INTO agent_connections"
                "(owner_id, id, status, created_at, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    payload["owner_id"],
                    payload["id"],
                    payload["status"],
                    payload["created_at"],
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )
        for payload in runs or []:
            conn.execute(
                "INSERT INTO agent_runs"
                "(owner_id, id, connection_id, task_id, created_at, dispatched_at,"
                " content_expires_at, content_expired, payload)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    payload["owner_id"],
                    payload["id"],
                    payload["connection_id"],
                    payload["task_id"],
                    payload["created_at"],
                    payload.get("dispatched_at"),
                    payload["content_expires_at"],
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )
        for payload in events or []:
            conn.execute(
                "INSERT INTO agent_run_events"
                "(owner_id, id, run_id, run_version, received_at, payload)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    payload["owner_id"],
                    payload["id"],
                    payload["run_id"],
                    payload["run_version"],
                    payload["received_at"],
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )
        conn.commit()


def stored_connection(db_path: Path, connection_id: str = CONNECTION) -> dict[str, Any]:
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT payload FROM agent_connections WHERE id = ?", (connection_id,)
        ).fetchone()
    assert row is not None, f"no stored connection {connection_id}"
    parsed: dict[str, Any] = json.loads(row[0])
    return parsed


def stored_run(db_path: Path, run_id: str = "agentrun_1") -> dict[str, Any]:
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT payload FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
    assert row is not None, f"no stored run {run_id}"
    parsed: dict[str, Any] = json.loads(row[0])
    return parsed


def audit_actions(db_path: Path) -> list[str]:
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute("SELECT payload FROM agent_audit").fetchall()
    return [json.loads(row[0])["action"] for row in rows]


def ledger_names(db_path: Path) -> set[str]:
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute("SELECT name FROM agent_schema_migrations").fetchall()
    return {str(row[0]) for row in rows}


def run_columns(db_path: Path) -> set[str]:
    with closing(sqlite3.connect(db_path)) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(agent_runs)")}


def seed_raw_connection(db_path: Path, *, connection_id: str, payload: str) -> None:
    """A connection row whose payload no model can read."""

    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO agent_connections"
            "(owner_id, id, status, created_at, payload) VALUES (?, ?, ?, ?, ?)",
            (OWNER, connection_id, "ready", NOW.isoformat(), payload),
        )
        conn.commit()


def seed_raw_run(db_path: Path, *, run_id: str, payload: str) -> None:
    """A run row whose payload no model can read."""

    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO agent_runs"
            "(owner_id, id, connection_id, task_id, created_at, dispatched_at,"
            " content_expires_at, content_expired, payload)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                OWNER,
                run_id,
                CONNECTION,
                "task_1",
                NOW.isoformat(),
                NOW.isoformat(),
                (NOW + timedelta(days=30)).isoformat(),
                payload,
            ),
        )
        conn.commit()


def raw_run_payload(db_path: Path, run_id: str) -> str:
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT payload FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
    assert row is not None, f"no stored run {run_id}"
    return str(row[0])


def refuse_snapshot(task_id: str, *, owner_id: str) -> Any:  # pragma: no cover - guard
    """A task snapshot port that fails the test if the refusal reads a Task.

    The refusal has to happen before any content is touched: a disconnected
    connection is not a reason to go and load the user's Task.
    """

    raise AssertionError("a refused hand-off must not read the Task")


def build_service(repo: AgentRepository) -> AgentRelayService:
    return AgentRelayService(
        repo,
        secret_box=SecretBox(OrderedDict({"v1": b"\x07" * 32})),
        task_snapshot=refuse_snapshot,
        now=lambda: NOW,
    )


class InterruptedMigrationRepository(AgentRepository):
    """A startup that dies after superseding its first connection.

    The seam is `_migration_boundary`, the failure-injection hook the 007
    quarantine migration already uses, so both migrations are proven atomic the
    same way rather than one of them being trusted.
    """

    def _migration_boundary(self, stage: str) -> None:
        if stage == "wire_superseded":
            raise RuntimeError("startup interrupted mid-migration")


def drop_ledger_row(db_path: Path) -> None:
    """Forget the migration ran, keeping the columns it added.

    The shape a partly-restored backup leaves behind, and the one case where
    the ledgered pass re-runs against a schema that already has its columns.
    """

    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "DELETE FROM agent_schema_migrations WHERE name = ?", (A2A_WIRE_MIGRATION,)
        )
        conn.commit()


class TestBespokeConnectionsAreSuperseded:
    """What the ledgered migration does to a record of the old wire.

    014-FR-012, 014-SC-010; AC-023.
    """

    def test_014_SC_010_a_bespoke_connection_row_is_disconnected_with_its_reason(
        self, tmp_path: Path
    ) -> None:
        """The connection survives as evidence, not as an offer.

        Leaving it `ready` would offer the owner a hand-off that cannot work;
        deleting it would erase something they configured and never explain
        where it went. Disconnected-with-a-reason is the only state that is both
        true and legible (D-01-S21 / M-01-S19).
        """

        db_path = pre_014_database(tmp_path)
        seed(db_path, connections=[bespoke_connection()])

        AgentRepository(tmp_path)

        payload = stored_connection(db_path)
        assert payload["status"] == "disconnected"
        assert payload["disconnect_reason"] == "superseded_wire_contract"
        assert payload["wire"] == "a2a", "the row is now readable by this build"
        assert payload["disconnected_at"] is not None
        assert payload["schema_version"] == 2, "written by the 014 image"

    def test_014_SC_010_the_migration_destroys_both_bespoke_secrets(
        self, tmp_path: Path
    ) -> None:
        """Neither secret has anything left to authorise.

        The outbound credential is scoped to an endpoint this build will never
        call again; the inbound secret signs a route that no longer exists.
        Keeping either would be retaining a live secret for no purpose, which is
        exactly what FR-016 forbids. `inbound_secret` is *dropped* rather than
        nulled — the key itself is 007's, and the field is gone from the model.
        """

        db_path = pre_014_database(tmp_path)
        seed(db_path, connections=[bespoke_connection()])

        AgentRepository(tmp_path)

        payload = stored_connection(db_path)
        assert payload["credential"] is None
        assert "inbound_secret" not in payload
        raw = json.dumps(payload)
        assert "sealed-outbound" not in raw
        assert "sealed-inbound" not in raw

    def test_014_SC_010_the_reauthentication_scope_is_reset_with_the_credential(
        self, tmp_path: Path
    ) -> None:
        """A destroyed credential cannot leave a verified scope behind it.

        `scope_verified_at` and `first_dispatch_at` describe a credential that
        no longer exists. Carrying them across would mean that if this
        connection were ever reconnected, the first content-bearing dispatch
        under a brand-new credential would skip re-authentication (FR-004).
        """

        db_path = pre_014_database(tmp_path)
        seed(db_path, connections=[bespoke_connection()])

        AgentRepository(tmp_path)

        payload = stored_connection(db_path)
        assert payload["scope_verified_at"] is None
        assert payload["first_dispatch_at"] is None
        assert payload["last_contact_at"] is None

    def test_014_SC_010_the_rewrite_is_counted_on_the_ledger_row(
        self, tmp_path: Path
    ) -> None:
        """`docs/external-agent-relay-release.md` asks for this number.

        The spec's assumption is that no production records exist. A count
        nobody wrote down is not evidence of that; the ledger row is. Two
        owners' rows are seeded so the count cannot be satisfied by a boolean
        pretending to be a number.
        """

        db_path = pre_014_database(tmp_path)
        seed(
            db_path,
            connections=[
                bespoke_connection(),
                bespoke_connection(owner_id="user_b", connection_id="agentconn_2"),
            ],
        )

        repo = AgentRepository(tmp_path)

        assert repo.migration_rewrite_count(A2A_WIRE_MIGRATION) == 2

    def test_014_SC_010_a_database_with_no_bespoke_rows_records_a_zero(
        self, tmp_path: Path
    ) -> None:
        """The expected production case, and it must be stated, not implied.

        `None` would mean "the migration never ran" and `0` means "it ran and
        found nothing"; the runbook's pre-deploy check needs to tell those two
        apart.
        """

        repo = AgentRepository(tmp_path)

        assert repo.migration_rewrite_count(A2A_WIRE_MIGRATION) == 0
        assert repo.migration_rewrite_count("never_ran") is None

    def test_014_SC_010_each_rewritten_connection_gets_one_wire_superseded_row(
        self, tmp_path: Path
    ) -> None:
        """One audit row per connection, so the count above is auditable.

        The ledger says how many; the audit rows say which. A destroyed
        credential is not something to record only in aggregate.
        """

        db_path = pre_014_database(tmp_path)
        seed(
            db_path,
            connections=[
                bespoke_connection(),
                bespoke_connection(owner_id="user_b", connection_id="agentconn_2"),
            ],
        )

        AgentRepository(tmp_path)

        assert audit_actions(db_path).count("wire_superseded") == 2

    def test_014_SC_010_an_a2a_connection_row_is_left_exactly_as_it_was(
        self, tmp_path: Path
    ) -> None:
        """The migration must not disconnect a connection this build created.

        Without this the selection predicate could be "rewrite everything" and
        every test above would still pass.
        """

        db_path = pre_014_database(tmp_path)
        seed(db_path, connections=[bespoke_connection(wire="a2a")])
        before = stored_connection(db_path)

        AgentRepository(tmp_path)

        assert stored_connection(db_path) == before

    def test_014_SC_010_a_second_startup_rewrites_nothing(self, tmp_path: Path) -> None:
        """Restarts are ordinary; a migration that is not idempotent is not.

        A second pass that rewrote the row again would bump its revision on
        every boot and write a second audit row for one event, so the byte
        comparison is the assertion rather than a spot check.
        """

        db_path = pre_014_database(tmp_path)
        seed(db_path, connections=[bespoke_connection()])
        repo = AgentRepository(tmp_path)
        after_first = stored_connection(db_path)

        AgentRepository(tmp_path)

        assert stored_connection(db_path) == after_first
        assert audit_actions(db_path).count("wire_superseded") == 1
        assert repo.migration_rewrite_count(A2A_WIRE_MIGRATION) == 1

    def test_014_FR_012_wire_less_rows_are_rewritten_on_every_startup(
        self, tmp_path: Path
    ) -> None:
        """The rewrite runs outside the ledger, on every boot.

        A rollback to the 007 image and back writes a wire-less row *between*
        two 014 startups, and the ledger row is already there by then. If the
        rewrite lived only under the ledger, that row would sit unreadable by
        the 014 `AgentConnectionDocument` until somebody noticed — so it runs
        every time, exactly as `_migrate_legacy_invalid_connections` already
        does.
        """

        db_path = pre_014_database(tmp_path)
        AgentRepository(tmp_path)
        seed(db_path, connections=[bespoke_connection(connection_id="agentconn_late")])

        repo = AgentRepository(tmp_path)

        payload = stored_connection(db_path, "agentconn_late")
        assert payload["status"] == "disconnected"
        assert payload["disconnect_reason"] == "superseded_wire_contract"
        # Outside the ledger means outside the count: the ledger row records
        # what the *first* pass found, and rewriting it later would destroy the
        # pre-deploy evidence it exists to hold.
        assert repo.migration_rewrite_count(A2A_WIRE_MIGRATION) == 0
        # It is still readable through the model, which is the whole point.
        assert repo.get_connection("agentconn_late", owner_id=OWNER).wire == "a2a"


class TestRunsOfASupersededConnection:
    """In-flight runs stop claiming to be live, and keep their history.

    014-FR-012, 014-SC-010; AC-023.
    """

    def test_014_SC_010_a_dispatched_non_terminal_run_is_stamped(
        self, tmp_path: Path
    ) -> None:
        """Otherwise it sits at "running" forever.

        Nothing will ever observe this run again — there is no credential left
        to ask with. Left alone it would keep rendering as in-progress, which is
        precisely the false claim the honesty rules exist to prevent.
        """

        db_path = pre_014_database(tmp_path)
        seed(db_path, connections=[bespoke_connection()], runs=[bespoke_run()])

        AgentRepository(tmp_path)

        payload = stored_run(db_path)
        assert payload["connection_disconnected_at"] is not None
        assert payload["next_observation_at"] is None

    def test_014_SC_010_the_stamped_run_keeps_its_bounded_history(
        self, tmp_path: Path
    ) -> None:
        """Disconnecting is not erasing.

        The user still gets the run they can see and the retention clock they
        were promised; what changes is the claim about its liveness, not the
        record of what happened.
        """

        db_path = pre_014_database(tmp_path)
        run = bespoke_run()
        seed(
            db_path,
            connections=[bespoke_connection()],
            runs=[run],
            events=[
                {
                    "id": "evt_1",
                    "owner_id": OWNER,
                    "run_id": run["id"],
                    "connection_id": CONNECTION,
                    "type": "running",
                    "run_version": 4,
                    "received_at": NOW.isoformat(),
                    "summary": "Halfway through",
                }
            ],
        )

        repo = AgentRepository(tmp_path)

        stored = stored_run(db_path)
        assert stored["reported_state"] == "running", "the last truth is preserved"
        assert stored["progress_text"] == "Halfway through"
        assert stored["content_expires_at"] == run["content_expires_at"]
        assert len(repo.list_events(run["id"], owner_id=OWNER)) == 1

    def test_014_SC_010_a_terminal_run_is_not_restamped(self, tmp_path: Path) -> None:
        """A finished run was never claiming to be live.

        Stamping it would add a "connection disconnected" line to a run the user
        already watched complete, which reads as something having gone wrong
        after the fact.
        """

        db_path = pre_014_database(tmp_path)
        seed(
            db_path,
            connections=[bespoke_connection()],
            runs=[bespoke_run(run_id="done", reported_state="completed")],
        )

        AgentRepository(tmp_path)

        assert stored_run(db_path, "done").get("connection_disconnected_at") is None

    def test_014_SC_010_an_undispatched_reservation_is_not_stamped(
        self, tmp_path: Path
    ) -> None:
        """A reservation that never left is not an interrupted run.

        Nothing was ever handed to the agent, so there is nothing to explain to
        the user about it; it is invisible until a dispatch is attempted.
        """

        db_path = pre_014_database(tmp_path)
        seed(
            db_path,
            connections=[bespoke_connection()],
            runs=[
                bespoke_run(
                    run_id="reserved",
                    dispatched_at=None,
                    dispatch_state="not_sent",
                    reported_state=None,
                )
            ],
        )

        AgentRepository(tmp_path)

        stamped = stored_run(db_path, "reserved").get("connection_disconnected_at")
        assert stamped is None

    def test_014_SC_010_an_already_stamped_run_keeps_its_original_timestamp(
        self, tmp_path: Path
    ) -> None:
        """Two disconnects are one disconnect for the run that saw the first.

        A run stamped by an owner disconnect and then met by the migration must
        keep the moment it actually stopped being observable, not the moment
        the upgrade happened to run.
        """

        earlier = (NOW - timedelta(days=2)).isoformat()
        db_path = pre_014_database(tmp_path)
        seed(
            db_path,
            connections=[bespoke_connection()],
            runs=[bespoke_run(connection_disconnected_at=earlier)],
        )

        AgentRepository(tmp_path)

        assert stored_run(db_path)["connection_disconnected_at"] == earlier

    def test_014_SC_010_an_unreadable_run_row_does_not_stop_the_others(
        self, tmp_path: Path
    ) -> None:
        """One corrupt row must not cost every other run its stamp.

        The alternative is worse than it sounds: the whole migration aborts,
        rolls back, and retries identically on the next boot — so a single
        unparseable row would keep every connection on the old wire alive
        forever, offering hand-offs that cannot work.
        """

        db_path = pre_014_database(tmp_path)
        seed(db_path, connections=[bespoke_connection()], runs=[bespoke_run()])
        seed_raw_run(db_path, run_id="corrupt", payload="{not json")

        AgentRepository(tmp_path)

        assert stored_run(db_path)["connection_disconnected_at"] is not None
        assert raw_run_payload(db_path, "corrupt") == "{not json", "left as found"


class TestTheMigrationIsAtomicAndRepeatable:
    """A startup can die anywhere; a backup can be restored halfway.

    Neither may leave a connection half-superseded — a row whose credential is
    destroyed but whose status still says `ready` would offer a hand-off that
    cannot possibly work, and there is no second copy of the credential to
    recover from.

    014-FR-012, 014-SC-010.
    """

    def test_014_SC_010_an_interrupted_ledgered_migration_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        """All of it, or none of it, and then retried on the next boot.

        The interruption is injected after the first connection is rewritten,
        which is the only interesting moment: one row done, one row not.
        """

        db_path = pre_014_database(tmp_path)
        seed(
            db_path,
            connections=[
                bespoke_connection(),
                bespoke_connection(owner_id="user_b", connection_id="agentconn_2"),
            ],
        )

        with pytest.raises(RuntimeError):
            InterruptedMigrationRepository(tmp_path)

        assert "wire" not in stored_connection(db_path)
        assert stored_connection(db_path)["credential"] is not None
        assert audit_actions(db_path) == []
        assert ledger_names(db_path).isdisjoint({A2A_WIRE_MIGRATION})

        # The next healthy startup finishes the job it left.
        repo = AgentRepository(tmp_path)
        assert repo.migration_rewrite_count(A2A_WIRE_MIGRATION) == 2

    def test_014_SC_010_an_interrupted_later_pass_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        """The same guarantee for the pass that runs outside the ledger.

        It has its own transaction precisely so that a crash during the boot
        that finds a wire-less row cannot leave that row half-rewritten.
        """

        db_path = pre_014_database(tmp_path)
        AgentRepository(tmp_path)
        seed(db_path, connections=[bespoke_connection()])
        before = stored_connection(db_path)

        with pytest.raises(RuntimeError):
            InterruptedMigrationRepository(tmp_path)

        assert stored_connection(db_path) == before

    def test_014_SC_010_the_migration_reruns_against_a_schema_it_already_altered(
        self, tmp_path: Path
    ) -> None:
        """The shape a partly-restored backup leaves: columns yes, ledger no.

        Every step has to be conditional on what is actually there rather than
        on the ledger's say-so, because the ledger is the thing that was lost.
        A bare `ALTER TABLE ADD COLUMN` here would raise and take the whole
        startup down.
        """

        db_path = pre_014_database(tmp_path)
        AgentRepository(tmp_path)
        drop_ledger_row(db_path)
        seed(db_path, connections=[bespoke_connection()])

        repo = AgentRepository(tmp_path)

        assert repo.migration_rewrite_count(A2A_WIRE_MIGRATION) == 1
        assert stored_connection(db_path)["status"] == "disconnected"
        assert run_columns(db_path) >= set(A2A_RUN_COLUMNS)

    def test_014_SC_010_an_unreadable_connection_row_is_left_to_quarantine(
        self, tmp_path: Path
    ) -> None:
        """Two migrations, one row, and only one of them may claim it.

        Superseding an unparseable row would destroy a credential *and* hand it
        to the quarantine migration in the same startup, and afterwards nobody
        could tell which of the two had actually happened to it. So this pass
        skips it and the quarantine record is the single explanation.
        """

        db_path = pre_014_database(tmp_path)
        seed(db_path, connections=[bespoke_connection()])
        seed_raw_connection(db_path, connection_id="corrupt", payload="{not json")

        repo = AgentRepository(tmp_path)

        assert repo.migration_rewrite_count(A2A_WIRE_MIGRATION) == 1
        assert stored_connection(db_path)["status"] == "disconnected"
        quarantined = repo.get_connection("corrupt", owner_id=OWNER)
        assert (
            quarantined.last_test_error_code
            == "legacy_invalid_connection_requires_reconfiguration"
        )
        assert audit_actions(db_path).count("wire_superseded") == 1


class TestHandOffOnASupersededConnection:
    """A superseded connection can be looked at, never handed work.

    014-FR-012, 014-SC-010.
    """

    def test_014_FR_012_a_hand_off_preview_on_a_superseded_connection_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The refusal comes before the Task is even read.

        `refuse_snapshot` fails the test if the service reaches for the user's
        content, so this proves the connection check is the first gate rather
        than one of several.

        The reason asserted here is today's. When T110-T115 surface
        `disconnect_reason`, it becomes `superseded_wire_contract` and this
        assertion must move with the xfail below it — deliberately, so the two
        cannot drift apart.
        """

        db_path = pre_014_database(tmp_path)
        seed(db_path, connections=[bespoke_connection()])
        service = build_service(AgentRepository(tmp_path))

        with pytest.raises(ValidationFailure) as raised:
            service.preview_handoff(
                "task_1",
                AgentHandoffPreviewRequest(connection_id=CONNECTION),
                owner_id=OWNER,
            )

        assert raised.value.detail == {"reason": "connection_disconnected"}

    @pytest.mark.xfail(
        strict=True,
        reason="the refusal names the superseded wire only once T110-T115 "
        "surface disconnect_reason; strict, so the removal must un-mark it",
    )
    def test_014_FR_012_the_refusal_names_the_superseded_wire_contract(
        self, tmp_path: Path
    ) -> None:
        """ "Disconnected" is true but useless here.

        The owner never disconnected this connection — an upgrade did — so a
        bare "you disconnected this" would be a lie about who acted. The reason
        has to travel with the refusal.
        """

        db_path = pre_014_database(tmp_path)
        seed(db_path, connections=[bespoke_connection()])
        service = build_service(AgentRepository(tmp_path))

        with pytest.raises(ValidationFailure) as raised:
            service.preview_handoff(
                "task_1",
                AgentHandoffPreviewRequest(connection_id=CONNECTION),
                owner_id=OWNER,
            )

        assert raised.value.detail == {"reason": "superseded_wire_contract"}


class TestTheBespokeWireIsGone:
    """The removal itself, asserted from outside.

    Both cases are live: T114 deleted the routes, so FastAPI answers 404 for
    them, and T115 deleted `connector.py`, so importing it raises. They stay
    here as the standing proof that neither can come back unnoticed.

    014-FR-012, 014-SC-010.
    """

    def test_014_SC_010_the_bespoke_event_and_signing_secret_routes_answer_404(
        self, api_client: TestClient
    ) -> None:
        """A route that still answers is a wire that still exists.

        `/agent-events` accepted the connector's signed reports and
        `signing-secret` minted the key that signed them. Neither has a caller
        in the A2A contract, and a live endpoint with no caller is an attack
        surface kept for sentiment.
        """

        assert api_client.post("/api/agent-events", json={}).status_code == 404
        rotated = api_client.post(
            f"/api/agent-connections/{CONNECTION}/signing-secret", json={}
        )
        assert rotated.status_code == 404

    def test_014_FR_012_the_bespoke_connector_module_no_longer_exists(self) -> None:
        """Deleted, not merely unused.

        A module left importable is a module something will import again. The
        assertion is import-absence because that is the only form the question
        has a true answer in.
        """

        with pytest.raises(ModuleNotFoundError):
            __import__("app.modules.agents.connector")
