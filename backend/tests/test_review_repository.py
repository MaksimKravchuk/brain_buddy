"""Spec 020: the review tables in ``tasks.sqlite3`` (data-model E1 – E9).

The eight review tables live in the Tasks module's own SQLite file, beside the
tasks they refer to, are created idempotently with a ``review-v1`` ledger row,
filter every read by owner, and are erased first by ``delete_all_for_owner``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.modules.tasks import TaskRepository
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import TaskDocument

NOW = datetime(2026, 10, 9, 14, 2, tzinfo=UTC)
OWNER = "user_owner_a"
OTHER = "user_owner_b"
REVIEW_TABLES = {
    "review_settings",
    "review_sessions",
    "review_decisions",
    "review_receipts",
    "review_park_acks",
    "review_bulk_releases",
    "navigator_consents",
    "navigator_usage",
}


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {row[0] for row in rows}


def _ledger(db_path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(db_path) as conn:
        return list(
            conn.execute(
                "SELECT id, payload FROM migration_ledger WHERE id = 'review-v1'"
            )
        )


def _task(owner_id: str, task_id: str = "task_000000000001") -> TaskDocument:
    return TaskDocument(
        id=task_id,
        owner_id=owner_id,
        title="Renovate the bathroom",
        state="next",
        order_key=0,
        created_at=NOW,
        updated_at=NOW,
        formulation_id="form_000000000001",
        formulation_started_at=NOW,
    )


def _seed_everything(repo: TaskRepository, owner_id: str) -> None:
    task = _task(owner_id)
    repo.save(task)
    repo.save_review_settings(rd.ReviewSettingsDocument(owner_id=owner_id))
    repo.save_review_session(
        rd.ReviewSessionDocument(
            id="review_000000000001",
            owner_id=owner_id,
            mode="quick",
            entry="list",
            origin="web",
            status="open",
            started_at=NOW,
            last_activity_at=NOW,
        )
    )
    repo.save_review_decision(
        rd.ReviewDecisionDocument(
            id="decision_000000000001",
            owner_id=owner_id,
            task_id=task.id,
            decided_at=NOW,
            type="extend",
            reason_text="Waiting for the quote",
            formulation_id=task.formulation_id,
            task_revision_before=1,
            task_revision_after=2,
            review_counts_as="extended",
            undo=rd.DecisionUndoDocument(task_before=task),
        )
    )
    repo.save_review_receipt(
        rd.ReviewReceiptDocument(
            owner_id=owner_id,
            task_id=task.id,
            kind="waiting",
            task_revision=1,
            reviewed_at=NOW,
            hidden_until=NOW + timedelta(days=7),
            source="keep",
            decision_id="decision_000000000001",
        )
    )
    repo.save_park_ack(
        rd.ReviewParkAckDocument(
            owner_id=owner_id,
            task_id=task.id,
            formulation_id="form_000000000001",
            parked_at=NOW,
            from_revision=1,
            source="sweep",
        )
    )
    repo.save_bulk_release(
        rd.ReviewBulkReleaseDocument(
            id="bulk_000000000001",
            owner_id=owner_id,
            kind="restart",
            created_at=NOW,
        )
    )
    repo.save_navigator_consent(
        rd.NavigatorConsentDocument(
            owner_id=owner_id,
            provider="openai",
            granted_at=NOW,
            consent_text_version=1,
        )
    )
    repo.save_navigator_usage(
        rd.NavigatorUsageDocument(owner_id=owner_id, day=date(2026, 10, 9), calls=1)
    )


def _counts(db_path: Path, owner_id: str) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE owner_id = ?", (owner_id,)
            ).fetchone()[0]
            for table in sorted(REVIEW_TABLES)
        }


def test_020_FR_043_review_tables_exist_with_the_review_v1_ledger_row(
    tmp_path: Path,
) -> None:
    """Initialisation creates the eight tables and records ``review-v1`` once."""

    repo = TaskRepository(tmp_path)
    assert _tables(repo.db_path) >= REVIEW_TABLES
    ledger = _ledger(repo.db_path)
    assert [row[0] for row in ledger] == ["review-v1"]
    assert set(json.loads(ledger[0][1])["tables"]) == REVIEW_TABLES

    TaskRepository(tmp_path)
    assert len(_ledger(repo.db_path)) == 1


def test_020_FR_043_every_review_read_filters_by_owner(tmp_path: Path) -> None:
    """Another owner's record reads as absent, never as a leak."""

    repo = TaskRepository(tmp_path)
    _seed_everything(repo, OWNER)

    assert repo.get_review_settings(OWNER) is not None
    assert repo.get_review_settings(OTHER) is None
    assert repo.get_review_session(OTHER, "review_000000000001") is None
    assert repo.get_review_decision(OTHER, "decision_000000000001") is None
    assert repo.get_review_receipt(OTHER, "task_000000000001", "waiting") is None
    assert repo.get_park_ack(OTHER, "task_000000000001", "form_000000000001") is None
    assert repo.get_bulk_release(OTHER, "bulk_000000000001") is None
    assert repo.list_review_sessions(OTHER) == []
    assert repo.list_review_decisions(OTHER) == []
    assert repo.list_review_receipts(OTHER) == []
    assert repo.list_park_acks(OTHER) == []
    assert repo.list_bulk_releases(OTHER) == []
    assert repo.list_navigator_consents(OTHER) == []
    assert repo.list_navigator_usage(OTHER) == []
    assert repo.list_next_tasks(OTHER) == []
    assert [task.id for task in repo.list_next_tasks(OWNER)] == ["task_000000000001"]
    assert repo.review_owner_ids() == {OWNER}

    decision = repo.get_review_decision(OWNER, "decision_000000000001")
    assert decision is not None and decision.reason_text == "Waiting for the quote"
    assert decision.undo is not None
    assert decision.undo.task_before.formulation_id == "form_000000000001"


def test_020_FR_043_delete_all_for_owner_erases_review_tables_first_and_is_idempotent(
    tmp_path: Path,
) -> None:
    """Purge removes every review row of the owner, leaves others, runs twice."""

    repo = TaskRepository(tmp_path)
    _seed_everything(repo, OWNER)
    _seed_everything(repo, OTHER)

    repo.delete_all_for_owner(owner_id=OWNER)
    assert set(_counts(repo.db_path, OWNER).values()) == {0}
    assert set(_counts(repo.db_path, OTHER).values()) == {1}

    repo.delete_all_for_owner(owner_id=OWNER)
    assert set(_counts(repo.db_path, OWNER).values()) == {0}


def test_020_FR_043_purge_holds_the_command_lock_over_the_review_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review deletes run first, inside the owner lock, before the task rows."""

    repo = TaskRepository(tmp_path)
    _seed_everything(repo, OWNER)
    order: list[str] = []
    original = repo._delete_review_rows

    def tracking(conn: sqlite3.Connection, owner_id: str) -> None:
        order.append(f"review:{getattr(repo._thread_state, 'conn', None) is conn}")
        original(conn, owner_id)

    monkeypatch.setattr(repo, "_delete_review_rows", tracking)
    repo.delete_all_for_owner(owner_id=OWNER)
    assert order == ["review:True"]


def test_020_FR_043_task_clock_fields_round_trip_and_legacy_payloads_load(
    tmp_path: Path,
) -> None:
    """E1 fields are optional: an old payload loads, a new one round-trips."""

    legacy: dict[str, Any] = {
        "id": "task_legacy00001",
        "owner_id": OWNER,
        "title": "Call Bob",
        "state": "next",
        "order_key": 0,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }
    old = TaskDocument.model_validate(legacy)
    assert old.formulation_id is None and old.parked is None
    assert old.consecutive_stalled_formulations == 0

    parked = TaskDocument.model_validate(
        {
            **legacy,
            "state": "someday",
            "consecutive_stalled_formulations": 1,
            "parked": {
                "at": NOW.isoformat(),
                "formulation_id": "form_000000000001",
                "from_revision": 3,
                "clock_before": {
                    "started_at": (NOW - timedelta(days=21)).isoformat(),
                    "extended_at": None,
                    "extension_reason": None,
                    "park_floor_at": None,
                    "stalled_before": 0,
                },
            },
        }
    )
    repo = TaskRepository(tmp_path)
    repo.save(parked)
    loaded = repo.get_for_owner(parked.id, owner_id=OWNER)
    assert loaded.parked == parked.parked
    assert loaded.consecutive_stalled_formulations == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("threshold_days", 10),
        ("review_weekday", 8),
        ("review_time", "25:00"),
        ("revision", 0),
    ],
)
def test_020_FR_043_review_settings_constraints_are_enforced(
    field: str, value: object
) -> None:
    """E2 constraints: threshold 7/14/21/28, weekday 1..7, HH:MM, revision ≥ 1."""

    with pytest.raises(ValueError):
        rd.ReviewSettingsDocument.model_validate({"owner_id": OWNER, field: value})


def test_020_FR_043_review_settings_defaults_match_the_data_model() -> None:
    """E2 defaults: 14 days, Friday, 16:00, UTC, not activated, revision 1."""

    settings = rd.ReviewSettingsDocument(owner_id=OWNER)
    assert settings.threshold_days == 14
    assert settings.review_weekday == 5
    assert settings.review_time == "16:00"
    assert settings.time_zone == "UTC"
    assert settings.activated_at is None
    assert settings.revision == 1


def test_020_FR_043_extension_reason_is_bounded_to_500_characters() -> None:
    """E1/E4: an extension reason is 1..500 characters on task and decision."""

    with pytest.raises(ValueError):
        _task(OWNER).model_copy(update={}).model_validate(
            {**_task(OWNER).model_dump(), "formulation_extension_reason": "x" * 501}
        )
    with pytest.raises(ValueError):
        rd.ReviewDecisionDocument(
            id="decision_000000000002",
            owner_id=OWNER,
            task_id="task_000000000001",
            decided_at=NOW,
            type="extend",
            reason_text="",
            task_revision_before=1,
            task_revision_after=2,
            review_counts_as="extended",
        )
