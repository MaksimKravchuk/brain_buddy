"""Owner-scoped persistence for the external-agent relay module.

Covers the storage guarantees the service layer relies on: per-owner isolation,
atomic replay-identifier consumption, monotonic run versions, bounded retention,
and complete erasure under the account-purge contract (FR-015, AC-021).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.exceptions import ConflictError, NotFoundError
from app.modules.agents.domain import (
    AgentAuditEntryDocument,
    AgentCapabilities,
    AgentConnectionDocument,
    AgentIdempotencyRecord,
    AgentRunCommandDocument,
    AgentRunDocument,
    AgentRunEventDocument,
)
from app.modules.agents.repository import AgentRepository

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


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


class TestConnections:
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


class TestRuns:
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

    def test_a_connection_is_resolvable_without_an_owner_for_inbound_events(
        self, repo: AgentRepository
    ) -> None:
        """Inbound events identify their owner through the connection."""

        repo.create_connection(make_connection())

        found = repo.find_connection_anywhere("agentconn_1")
        assert found is not None and found.owner_id == "user_a"
        assert repo.find_connection_anywhere("agentconn_missing") is None


class TestEventReplayConsumption:
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


class TestRetentionAndPurge:
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
        assert run.reported_state == run.reported_state  # projection untouched

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
    key_hash: str = "kid-1:hash-of-k1",
    command: str = "dispatch_run",
    request_hash: str = "kid-1:hash-1",
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
            repo.get_idempotency(owner_id="user_a", key_hashes=["kid-1:hash-of-k1"])
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
            owner_id="user_a", key_hashes=["kid-1:hash-of-k1"]
        )
        assert record is not None
        assert record.resource_id == "agentrun_1"
        assert record.completed is True
        assert (
            repo.get_idempotency(owner_id="user_b", key_hashes=["kid-1:hash-of-k1"])
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
            owner_id="user_a", record=make_idempotency(key_hash="kid-0:hash-of-k1")
        )

        record = repo.get_idempotency(
            owner_id="user_a",
            key_hashes=["kid-1:hash-of-k1", "kid-0:hash-of-k1"],
        )
        assert record is not None
        assert record.key_hash == "kid-0:hash-of-k1"

    def test_a_reservation_keeps_its_command_id(self, repo: AgentRepository) -> None:
        """An uncompleted reservation survives to give a retry the same ID."""

        repo.save_idempotency(
            owner_id="user_a",
            record=make_idempotency(command_id="agentcmd_1", completed=False),
        )

        record = repo.get_idempotency(
            owner_id="user_a", key_hashes=["kid-1:hash-of-k1"]
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
            record=make_idempotency(key_hash="kid-1:hash-of-k2", created_at=stale),
        )
        repo.save_idempotency(
            owner_id="user_b",
            record=make_idempotency(key_hash="kid-1:hash-of-k3"),
        )

        assert repo.purge_all_expired_idempotency(now=NOW) == 2
        assert (
            repo.get_idempotency(owner_id="user_a", key_hashes=["kid-1:hash-of-k1"])
            is None
        )
        assert (
            repo.get_idempotency(owner_id="user_b", key_hashes=["kid-1:hash-of-k3"])
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
            repo.get_idempotency(owner_id="user_b", key_hashes=["kid-1:hash-of-k1"])
            is not None
        )
