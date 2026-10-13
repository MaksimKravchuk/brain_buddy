"""T028 (PR-28): Review writers publish complete public projections.

026-FR-005/006/014/016/022 and 026-SC-002. With ``rust_core_sync`` effective each
Review writer and the Navigator consent grant/revoke is one receipt, one owner
unit and one feed commit. These tests drive the existing HTTP routes of an app
whose Review services were handed the shared receipt boundary, then read the
committed feed straight from the sync tables.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from time import perf_counter_ns
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import navigator_rate_limiter
from app.modules.tasks.jobs import JobRepository
from app.modules.tasks.review_domain import ReviewSettingsDocument
from app.modules.tasks.review_service import SNAPSHOT_RETENTION
from app.modules.tasks.sync.legacy_adapter import revoke_collision_key
from app.modules.tasks.sync.receipts import (
    ReceiptStore,
    ScopeAuthority,
    SyncCommandError,
)
from app.modules.tasks.sync.review_projection import (
    PUBLIC_REVIEW_ENTITY_TYPES,
    UNDO_AVAILABLE_FOR,
    ReviewCommandBoundary,
    ReviewProjection,
    dict_codec,
    model_codec,
)
from app.modules.tasks.sync.unit_of_work import TaskUnitOfWork, WriteRecord
from app.utils.idempotency import idempotency_key_digest

from .conftest import FrozenClock
from .test_review_auto_park import keep_alive
from .test_review_flow_api import FlowApi
from .test_review_navigator import (
    PROVIDER_ENV,
    Nav,
    SpyProvider,
)
from .test_review_navigator import (
    test_020_FR_024_a_colliding_revoke_retry_never_revokes_a_newer_grant as legacy_collision_retry,
)
from .test_review_navigator import (
    test_020_FR_024_late_grant_retry_after_a_revoke_replays_and_stays_revoked as legacy_late_grant,
)
from .test_review_navigator import (
    test_020_FR_024_late_revoke_retry_after_a_regrant_replays_and_stays_granted as legacy_late_revoke,
)

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Review sync projection"),
    allure.story("Review writers publish complete public projections"),
]

PRIVATE_KEYS = {
    "private",
    "applied_progress",
    "task_before",
    "clock_before",
    "previous_state",
    "history",
    "reserved_cost_usd",
    "last_effective_sweep_at",
    "threshold_changed_at",
    "from_revision",
}

Base = dict[tuple[str, str], dict[str, Any]]


@pytest.fixture(autouse=True)
def _measure_fast_allure_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    # Allure stores millisecond timestamps; a real, sub-ms projection step can
    # otherwise be misclassified as an empty step by the taxonomy validator.
    original_step = allure.step

    @contextmanager
    def measured_step(title: str) -> Iterator[None]:
        started = perf_counter_ns()
        with original_step(title):
            yield
            elapsed_ns = perf_counter_ns() - started
            if elapsed_ns < 2_000_000:
                allure.attach(str(elapsed_ns), name="Step elapsed nanoseconds")

    monkeypatch.setattr(allure, "step", measured_step)


@pytest.fixture(autouse=True)
def _hermetic_navigator(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(PROVIDER_ENV, "deterministic")
    navigator_rate_limiter.reset()
    yield
    navigator_rate_limiter.reset()


class Synced:
    """An app whose Review services run through the receipt boundary."""

    def __init__(self, client: TestClient, clock: FrozenClock) -> None:
        self.clock = clock
        self.api = FlowApi(client, clock)
        self.nav = Nav(client)
        container = self.api.container
        self.container = container
        self.repo = container.task_repo
        core = container.review_service._rust_facade._core  # type: ignore[union-attr]
        self.boundary = ReviewCommandBoundary(
            ReceiptStore(core),
            TaskUnitOfWork(self.repo, JobRepository(self.repo.db_path)),
            lambda unit: ScopeAuthority(
                unit.owner_id, "server-1", "feed-1", "access-1", "sqlite-1"
            ),
            self.repo,
            core,
        )
        container.review_service._boundary = self.boundary
        container.navigator_service._boundary = self.boundary
        self.rust("on")
        self.api.flag("on")

    @property
    def owner(self) -> str:
        return self.api.owner_id

    def rust(self, mode: str) -> None:
        self.container.feature_flag_service.set_mode(
            "rust_core_sync", mode, operator_id="test-operator"
        )

    def _rows(self, sql: str, *params: Any) -> list[sqlite3.Row]:
        with sqlite3.connect(self.repo.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(sql, params).fetchall()

    def transactions(self) -> list[dict[str, Any]]:
        """The owner's committed feed transactions, oldest first."""
        headers = self._rows(
            "SELECT commit_seq FROM sync_change_transactions WHERE owner_id=? "
            "ORDER BY length(commit_seq), commit_seq",
            self.owner,
        )
        result = []
        for header in headers:
            rows = self._rows(
                "SELECT * FROM sync_change_records WHERE owner_id=? AND commit_seq=?",
                self.owner,
                header["commit_seq"],
            )
            result.append(
                {
                    "seq": header["commit_seq"],
                    "changes": [
                        {
                            "entity_type": r["entity_type"],
                            "record_key": json.loads(r["record_key"]),
                            "record_version": r["record_version"],
                            "operation": r["operation"],
                            "value": json.loads(r["value"]) if r["value"] else None,
                        }
                        for r in rows
                    ],
                }
            )
        return result

    def folded(self) -> Base:
        """The feed applied in order: the base a client would hold."""
        state: Base = {}
        for transaction in self.transactions():
            for change in transaction["changes"]:
                key = (change["entity_type"], json.dumps(change["record_key"]))
                if change["operation"] == "tombstone":
                    state.pop(key, None)
                else:
                    state[key] = change["value"]
        return state

    def snapshot(self) -> Base:
        """The same base read straight from the stored documents."""
        projection = self.boundary.projection
        public = projection.public(projection.snapshot(self.owner))
        return {
            (c["entity_type"], json.dumps(c["record_key"])): c["value"] for c in public
        }

    def review_base(self) -> Base:
        return {
            k: v for k, v in self.folded().items() if k[0] in PUBLIC_REVIEW_ENTITY_TYPES
        }

    def receipts(self) -> int:
        return len(
            self._rows(
                "SELECT 1 FROM sync_command_receipts WHERE owner_id=?", self.owner
            )
        )

    def legacy_keys(self) -> set[str]:
        return {
            r["key_digest"]
            for r in self._rows(
                "SELECT key_digest FROM sync_legacy_keys WHERE owner_id=?", self.owner
            )
        }

    def post(self, path: str, body: dict[str, Any], key: str | None = None) -> Any:
        headers = {"Idempotency-Key": key} if key else self.api.key()
        return self.api.client.post(path, json=body, headers=headers)

    def grants_enabled(self) -> None:
        self.container.navigator_service.provider = SpyProvider()


@pytest.fixture
def synced(api_client: TestClient, frozen_clock: FrozenClock) -> Synced:
    return Synced(api_client, frozen_clock)


def _walk(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [*value, *(x for v in value.values() for x in _walk(v))]
    if isinstance(value, list):
        return [x for v in value for x in _walk(v)]
    return []


def _kinds(transaction: dict[str, Any]) -> set[tuple[str, str]]:
    return {(c["entity_type"], c["operation"]) for c in transaction["changes"]}


def _up(*types: str) -> set[tuple[str, str]]:
    return {(t, "upsert") for t in types}


GOLDEN_STEPS: list[tuple[str, set[tuple[str, str]] | None]] = [
    ("explainer_ack", _up("review_settings", "task")),
    ("settings", _up("review_settings")),
    ("session_start", _up("review_session", "review_decision_queue")),
    ("session_progress", _up("review_session", "review_decision_queue")),
    (
        "decide_follow_up",
        _up(
            "review_decision",
            "review_decision_queue",
            "review_receipt",
            "review_session",
            "task",
        ),
    ),
    (
        "undo_decision",
        {
            ("review_decision", "tombstone"),
            ("review_receipt", "tombstone"),
            ("task", "tombstone"),
            ("task", "upsert"),
            ("review_session", "upsert"),
            ("review_decision_queue", "upsert"),
        },
    ),
    ("bulk_release", _up("review_bulk_release", "review_receipt", "task")),
    (
        "bulk_undo",
        {
            ("review_bulk_release", "upsert"),
            ("review_receipt", "tombstone"),
            ("task", "upsert"),
        },
    ),
    ("session_finish", _up("review_session", "review_decision_queue")),
    ("auto_park", _up("review_settings")),
    ("parks_ack", None),
    ("consent_grant", _up("review_navigator_consent")),
    ("consent_revoke", _up("review_navigator_consent")),
]


def run_journey(s: Synced, after_step: Any = None) -> dict[str, Any]:
    """Every Review writer once; ``after_step(name)`` runs after each command."""

    api, clock = s.api, s.clock
    s.grants_enabled()
    nxt = api.create("next card", state="next")
    inbox = api.create("inbox card", state="inbox")
    waiting = api.create("waiting card", state="waiting", waiting_for="Ann")
    seen: dict[str, Any] = {}

    def step(name: str, response: Any, status: int = 200) -> Any:
        assert response.status_code == status, (name, response.text)
        seen[name] = response
        if after_step is not None:
            after_step(name)
        return response

    step(
        "explainer_ack",
        s.post("/api/review/explainer/acknowledge", {"time_zone": "UTC"}),
    )
    revision = api.state()["settings"]["revision"]
    step(
        "settings",
        api.client.put(
            "/api/review/settings",
            json={"threshold_days": 21, "expected_revision": revision},
            headers=api.key(),
        ),
    )
    clock.advance(days=40)
    session = step("session_start", api.start_raw(), 201).json()["id"]
    step(
        "session_progress",
        api.progress_raw(
            session, snapshot_decision_queue=True, current_step="decisions"
        ),
    )
    waiting = api.task(waiting["id"])
    decided = step(
        "decide_follow_up",
        api.decide_raw(waiting, "follow_up", title="Call Ann", session_id=session),
    ).json()
    step(
        "undo_decision",
        api.undo_raw(decided["decision"]["id"], decided["task"]["revision"]),
    )
    inbox = api.task(inbox["id"])
    released = step(
        "bulk_release",
        api.bulk_raw(
            "inbox_remainder",
            [{"task_id": inbox["id"], "expected_revision": inbox["revision"]}],
        ),
    ).json()
    step("bulk_undo", api.undo_bulk_raw(released["id"]))
    step("session_finish", api.finish_raw(session))
    nxt = api.task(nxt["id"])
    step(
        "auto_park",
        s.post(
            f"/api/tasks/{nxt['id']}/auto-park",
            {"formulation_id": nxt["formulation"]["id"]},
        ),
    )
    step(
        "parks_ack",
        s.post(
            "/api/review/parks/acknowledge",
            {
                "items": [
                    {
                        "task_id": nxt["id"],
                        "formulation_id": nxt["formulation"]["id"],
                    }
                ]
            },
        ),
        204,
    )
    step("consent_grant", s.nav.grant())
    step("consent_revoke", s.nav.revoke(), 204)
    return {"session": session, "decision": decided["decision"]["id"]}


def test_026_FR_006_every_review_writer_is_one_receipt_and_one_feed_commit(
    synced: Synced,
) -> None:
    """Each writer commits one receipt and, when it changed anything, one
    transaction holding every public record it touched; the feed folded in
    order is exactly the base read from the stored documents."""

    observed: list[tuple[str, int, int, bool]] = []

    def record(name: str) -> None:
        observed.append(
            (
                name,
                synced.receipts(),
                len(synced.transactions()),
                synced.review_base() == synced.snapshot(),
            )
        )

    with allure.step("run every Review writer through the boundary"):
        run_journey(synced, record)
    with allure.step("one receipt per command, one transaction per change set"):
        assert [name for name, *_ in observed] == [n for n, _ in GOLDEN_STEPS]
        receipts_seen = [receipts for _, receipts, _, _ in observed]
        assert receipts_seen == list(range(1, len(GOLDEN_STEPS) + 1))
        commits = [commit for _, _, commit, _ in observed]
        transactions = synced.transactions()
        for index, (name, golden) in enumerate(GOLDEN_STEPS):
            grew = commits[index] - (commits[index - 1] if index else 0)
            assert grew == (0 if golden is None else 1), name
        golden_kinds = [kinds for _, kinds in GOLDEN_STEPS if kinds is not None]
        assert [_kinds(t) for t in transactions] == golden_kinds
    with allure.step("the folded feed equals the stored base after every step"):
        assert all(consistent for *_, consistent in observed)
        assert synced.review_base() == synced.snapshot()
        assert {k[0] for k in synced.review_base()} >= {
            "review_settings",
            "review_session",
            "review_decision_queue",
            "review_bulk_release",
            "review_navigator_consent",
        }


def test_026_FR_022_no_private_member_reaches_the_feed_or_the_snapshot(
    synced: Synced,
) -> None:
    """Undo snapshots, progress fingerprints, sweep bookkeeping, consent history
    and clock-before content never appear, while public Undo availability does."""

    captured: dict[str, Any] = {}

    def capture(name: str) -> None:
        if name == "decide_follow_up":
            captured["decision"] = next(
                v for k, v in synced.folded().items() if k[0] == "review_decision"
            )

    run_journey(synced, capture)
    values = [
        change["value"]
        for transaction in synced.transactions()
        for change in transaction["changes"]
        if change["value"] is not None
    ]
    with allure.step("no private key at any depth, in the feed or the snapshot"):
        assert values
        assert PRIVATE_KEYS & {k for v in values for k in _walk(v)} == set()
        assert (
            PRIVATE_KEYS & {k for v in synced.snapshot().values() for k in _walk(v)}
            == set()
        )
    with allure.step("a decision publishes its advisory seven-day Undo deadline"):
        decision = captured["decision"]
        assert PRIVATE_KEYS & set(_walk(decision)) == set() and "undo" not in decision
        decided_at = datetime.fromisoformat(decision["decided_at"])
        assert datetime.fromisoformat(decision["undo_available_until"]) == (
            decided_at + timedelta(days=7)
        )
        assert decision["task_revision_before"] and decision["created_task_id"]
    assert UNDO_AVAILABLE_FOR == SNAPSHOT_RETENTION


def test_026_FR_014_captured_empty_queue_differs_from_an_uncaptured_one(
    synced: Synced,
) -> None:
    """The decision queue keeps ``null`` (not yet captured) apart from ``[]``."""

    api = synced.api
    session = api.start_raw().json()["id"]
    key = ("review_decision_queue", json.dumps([session]))
    with allure.step("a new run has not captured its queue"):
        assert synced.folded()[key]["task_ids"] is None
    with allure.step("capturing with nothing to decide is captured-empty"):
        assert (
            api.progress_raw(session, snapshot_decision_queue=True).status_code == 200
        )
        queue = synced.folded()[key]
        assert queue["task_ids"] == []
        assert queue["decided_task_ids"] == [] and queue["set_aside_task_ids"] == []
    assert synced.review_base() == synced.snapshot()


def test_026_FR_014_decided_and_set_aside_cards_derive_from_the_run_records(
    synced: Synced,
) -> None:
    """A decision republishes its run's queue with the decided ids."""

    api, clock = synced.api, synced.clock
    first = api.create("first", state="next")
    second = api.create("second", state="next")
    api.client.post(
        "/api/review/explainer/acknowledge", json={}, headers=api.key()
    ).raise_for_status()
    clock.advance(days=40)
    session = api.start_raw().json()["id"]
    api.progress_raw(session, snapshot_decision_queue=True).raise_for_status()
    first = api.task(first["id"])
    api.progress_raw(session, set_aside_task_id=api.task(second["id"])["id"])
    api.decide(first, "complete", session_id=session)
    queue = synced.folded()[("review_decision_queue", json.dumps([session]))]
    assert queue["decided_task_ids"] == [first["id"]]
    assert queue["set_aside_task_ids"] == [second["id"]]
    assert set(queue["task_ids"]) >= {first["id"], second["id"]}
    assert synced.review_base() == synced.snapshot()


def test_026_FR_006_replay_is_exact_and_writes_nothing(synced: Synced) -> None:
    """The same key and body answer the first response; no receipt, no commit."""

    api, clock = synced.api, synced.clock
    task = api.create("card", state="next")
    synced.post("/api/review/explainer/acknowledge", {}).raise_for_status()
    clock.advance(days=40)
    task = api.task(task["id"])
    body = {
        "type": "complete",
        "expected_revision": task["revision"],
        "formulation_id": task["formulation"]["id"],
    }
    path = f"/api/tasks/{task['id']}/decisions"
    first = synced.post(path, body, "decide-1")
    assert first.status_code == 200, first.text
    receipts, commits = synced.receipts(), len(synced.transactions())
    clock.advance(minutes=5)
    with allure.step("a retry is the original response"):
        again = synced.post(path, body, "decide-1")
    assert again.status_code == 200 and again.json() == first.json()
    assert (synced.receipts(), len(synced.transactions())) == (receipts, commits)
    with allure.step("the key is the identity: another body or target conflicts"):
        other = synced.post(path, {**body, "type": "cancel"}, "decide-1")
        assert other.status_code == 409
        assert other.json()["detail"] == {"reason": "idempotency_conflict"}
        elsewhere = synced.post("/api/review/explainer/acknowledge", {}, "decide-1")
        assert elsewhere.status_code == 409
    assert (synced.receipts(), len(synced.transactions())) == (receipts, commits)


def test_026_FR_005_matching_record_recovery_after_24_hours(synced: Synced) -> None:
    """Past the receipt's 24 hours a supplied id still answers from its stored
    record without writing; a command with no such record is unavailable."""

    api, clock = synced.api, synced.clock
    task = api.create("card", state="next")
    synced.post("/api/review/explainer/acknowledge", {}).raise_for_status()
    clock.advance(days=40)
    task = api.task(task["id"])
    decision_id = f"decision_{uuid.uuid4()}"
    session_id = f"review_{uuid.uuid4()}"
    decide_body = {
        "decision_id": decision_id,
        "type": "complete",
        "expected_revision": task["revision"],
        "formulation_id": task["formulation"]["id"],
    }
    start_body = {
        "id": session_id,
        "mode": "quick",
        "entry": "list",
        "origin": "ios",
        "replace_open": False,
    }
    progress_id = f"progress_{uuid.uuid4()}"
    first_start = synced.post("/api/review/sessions", start_body, "start-1")
    first_decide = synced.post(
        f"/api/tasks/{task['id']}/decisions", decide_body, "decide-1"
    )
    settings = synced.post("/api/review/explainer/acknowledge", {}, "ack-late")
    progress = api_progress = synced.api.client.patch(
        f"/api/review/sessions/{session_id}",
        json={"progress_id": progress_id, "current_step": "decisions"},
        headers={"Idempotency-Key": "progress-1"},
    )
    assert api_progress.status_code == 200
    for response in (first_start, first_decide, settings):
        assert response.status_code in (200, 201), response.text
    receipts, commits = synced.receipts(), len(synced.transactions())
    clock.advance(hours=25)
    with allure.step("a decision id and a run id recover their stored record"):
        decide_again = synced.post(
            f"/api/tasks/{task['id']}/decisions", decide_body, "decide-1"
        )
        assert decide_again.status_code == 200, decide_again.text
        assert decide_again.json()["decision"]["id"] == decision_id
        start_again = synced.post("/api/review/sessions", start_body, "start-1")
        assert start_again.status_code == 201, start_again.text
        assert start_again.json()["id"] == session_id
    with allure.step("progress is replay-safe by its id at any age"):
        retry = synced.api.client.patch(
            f"/api/review/sessions/{session_id}",
            json={"progress_id": progress_id, "current_step": "decisions"},
            headers={"Idempotency-Key": "progress-1"},
        )
        assert retry.status_code == 200 and retry.json()["id"] == session_id
    with allure.step("a command without a matching record cannot be rebuilt"):
        late = synced.post("/api/review/explainer/acknowledge", {}, "ack-late")
        assert late.status_code == 409
        assert late.json()["detail"] == {"reason": "idempotency_receipt_unavailable"}
    assert (synced.receipts(), len(synced.transactions())) == (receipts, commits)
    del progress


def test_026_FR_006_a_failed_feed_append_leaves_no_review_write(
    synced: Synced, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Receipt, feed and Review rows are one commit: when the feed cannot be
    written the decision, the task change and the receipt are all absent."""

    api, clock = synced.api, synced.clock
    task = api.create("card", state="next")
    synced.post("/api/review/explainer/acknowledge", {}).raise_for_status()
    clock.advance(days=40)
    task = api.task(task["id"])
    before = (synced.receipts(), len(synced.transactions()))

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("feed unavailable")

    monkeypatch.setattr(synced.boundary._receipts.change_log, "append", broken)
    body = {
        "type": "complete",
        "expected_revision": task["revision"],
        "formulation_id": task["formulation"]["id"],
    }
    with pytest.raises(RuntimeError, match="feed unavailable"):
        synced.post(f"/api/tasks/{task['id']}/decisions", body)
    monkeypatch.undo()
    assert (synced.receipts(), len(synced.transactions())) == before
    assert synced.repo.list_review_decisions(synced.owner) == []
    assert api.task(task["id"])["revision"] == task["revision"]


def test_026_FR_016_flag_off_keeps_the_legacy_record_but_known_keys_still_replay(
    synced: Synced,
) -> None:
    """OFF, a new key uses the idempotency record and publishes nothing; a key a
    receipt already owns still replays instead of running a second time."""

    api = synced.api
    on = synced.post("/api/review/explainer/acknowledge", {}, "ack-on")
    assert on.status_code == 200 and synced.receipts() == 1
    synced.rust("off")
    commits = len(synced.transactions())
    with allure.step("a new key is the legacy record, with no receipt or commit"):
        revision = api.state()["settings"]["revision"]
        off = api.client.put(
            "/api/review/settings",
            json={"threshold_days": 28, "expected_revision": revision},
            headers={"Idempotency-Key": "settings-off"},
        )
        assert off.status_code == 200
        assert (synced.receipts(), len(synced.transactions())) == (1, commits)
        assert (
            synced.repo.get_idempotency(owner_id=synced.owner, key="settings-off")
            is not None
        )
    with allure.step("a receipt-owned key replays while OFF"):
        replay = synced.post("/api/review/explainer/acknowledge", {}, "ack-on")
        assert replay.status_code == 200
        assert (synced.receipts(), len(synced.transactions())) == (1, commits)


def test_026_FR_014_state_is_derived_from_the_base_at_an_explicit_time(
    synced: Synced,
) -> None:
    """Counts and advisory instants are queries over the rows plus a time, never
    a record kind, and asking at another time writes nothing."""

    api, clock = synced.api, synced.clock
    api.create("card", state="next")
    synced.post("/api/review/explainer/acknowledge", {}).raise_for_status()
    service = synced.container.review_service
    before = (synced.receipts(), len(synced.transactions()), synced.snapshot())
    now = clock()
    soon = service.state(owner_id=synced.owner, now=now)
    later = service.state(owner_id=synced.owner, now=now + timedelta(days=60))
    assert soon.server_now == now
    assert later.server_now == now + timedelta(days=60)
    assert (soon.asks_for_decision, later.asks_for_decision) == (0, 1)
    assert later.next_review_at >= later.server_now or later.restart_mode
    assert service.state(owner_id=synced.owner).server_now == clock()
    assert (
        synced.receipts(),
        len(synced.transactions()),
        synced.snapshot(),
    ) == before
    kinds = {k[0] for k in synced.snapshot()} | {k[0] for k in synced.folded()}
    assert "review_state" not in kinds


def _consent_records(s: Synced) -> list[dict[str, Any]]:
    return [
        c["value"]
        for t in s.transactions()
        for c in t["changes"]
        if c["entity_type"] == "review_navigator_consent"
    ]


def test_026_FR_016_consent_publishes_status_without_history_or_usage(
    synced: Synced,
) -> None:
    """Grant, regrant and the owner-wide revoke publish the per-provider status,
    times and text version only."""

    synced.grants_enabled()
    nav, clock = synced.nav, synced.clock
    assert nav.grant(key="g1").status_code == 200
    clock.advance(minutes=1)
    assert nav.revoke(key="r1").status_code == 204
    clock.advance(minutes=1)
    assert nav.grant(key="g2").status_code == 200
    records = _consent_records(synced)
    assert [set(r) for r in records] == [{"provider", "consent"}] * 3
    assert [r["consent"]["revoked_at"] is not None for r in records] == [
        False,
        True,
        False,
    ]
    assert {k for r in records for k in r["consent"]} == {
        "granted_at",
        "revoked_at",
        "consent_text_version",
    }
    assert PRIVATE_KEYS.isdisjoint({k for v in records for k in _walk(v)})
    assert synced.review_base() == synced.snapshot()
    assert synced.receipts() == 3


def test_026_FR_016_a_grant_key_reused_by_a_revoke_keeps_the_grant_receipt(
    synced: Synced,
) -> None:
    """The legacy exception: the original receipt stays, the revoke records under
    its stable dedicated identity in one atomic receipt and feed effect, and a
    late retry of either never changes a newer grant."""

    synced.grants_enabled()
    nav, clock = synced.nav, synced.clock
    first = nav.grant(key="consent-k1")
    assert first.status_code == 200
    keys_after_grant = synced.legacy_keys()
    commits = len(synced.transactions())
    with allure.step("revoke reusing the grant's key records under its own identity"):
        clock.advance(minutes=1)
        assert nav.revoke(key="consent-k1").status_code == 204
        assert not nav.consent_current()
        added = synced.legacy_keys() - keys_after_grant
        assert added == {idempotency_key_digest(revoke_collision_key("consent-k1"))}
        assert idempotency_key_digest("consent-k1") in synced.legacy_keys()
        assert synced.receipts() == 2
        assert len(synced.transactions()) == commits + 1
        revoke_tx = synced.transactions()[-1]
        assert _kinds(revoke_tx) == _up("review_navigator_consent")
    with allure.step("the grant's receipt is intact and replays as revoked"):
        replay = nav.grant(key="consent-k1")
        assert replay.status_code == 200 and replay.json() == first.json()
        assert not nav.consent_current()
    with allure.step("a newer grant stands against a late colliding revoke retry"):
        clock.advance(minutes=1)
        assert nav.grant(key="consent-k3").status_code == 200
        receipts, commits = synced.receipts(), len(synced.transactions())
        late = nav.revoke(key="consent-k1")
        assert late.status_code == 204, late.text
        assert nav.consent_current()
        assert (synced.receipts(), len(synced.transactions())) == (receipts, commits)
    assert synced.review_base() == synced.snapshot()


def test_026_FR_016_revoke_is_not_gated_by_weekly_review_and_replays_as_noop(
    synced: Synced,
) -> None:
    """With ``weekly_review`` OFF the revoke still revokes, publishes and later
    replays without revoking a newer grant."""

    synced.grants_enabled()
    nav, clock = synced.nav, synced.clock
    assert nav.grant(key="g1").status_code == 200
    nav.flag("off")
    clock.advance(minutes=1)
    assert nav.revoke(key="consent-k2").status_code == 204
    assert not nav.consent_current()
    assert _consent_records(synced)[-1]["consent"]["revoked_at"] is not None
    nav.flag("on")
    clock.advance(minutes=1)
    assert nav.grant(key="g3").status_code == 200
    nav.flag("off")
    commits = len(synced.transactions())
    assert nav.revoke(key="consent-k2").status_code == 204
    assert nav.consent_current()
    assert len(synced.transactions()) == commits


def test_026_FR_016_consent_key_with_another_command_conflicts_but_revoke_never_does(
    synced: Synced,
) -> None:
    """A grant reusing a revoke key is a key reuse; the revoke reusing a grant
    key is the one accepted exception."""

    synced.grants_enabled()
    nav = synced.nav
    assert nav.revoke(key="consent-k2").status_code == 204
    reused = nav.grant(key="consent-k2")
    assert reused.status_code == 409, reused.text
    assert reused.json()["detail"] == {"reason": "idempotency_conflict"}
    assert nav.grant(key="consent-k5").status_code == 200
    assert nav.revoke(key="consent-k5").status_code == 204


@pytest.mark.parametrize(
    ("journey", "uses_clock"),
    [
        pytest.param(legacy_late_grant, True, id="late-grant-retry-after-revoke"),
        pytest.param(legacy_late_revoke, True, id="late-revoke-retry-after-regrant"),
        pytest.param(legacy_collision_retry, False, id="colliding-revoke-retry"),
    ],
)
def test_026_FR_016_existing_grant_revoke_replays_pass_through_the_migrated_adapter(
    synced: Synced, frozen_clock: FrozenClock, journey: Any, uses_clock: bool
) -> None:
    """The accepted 020 late-retry and key-collision journeys run unchanged over
    receipts instead of idempotency records."""

    with allure.step("run the accepted 020 journey against the boundary"):
        if uses_clock:
            journey(synced.nav, frozen_clock)
        else:
            journey(synced.nav)
    assert synced.receipts() > 0
    assert synced.repo.list_idempotency_for_owner(owner_id=synced.owner) == []
    assert synced.review_base() == synced.snapshot()


def test_026_FR_006_the_follow_up_undo_tombstones_commit_with_dependent_records(
    synced: Synced,
) -> None:
    """Undoing a follow-up deletes decision, receipt and created task and updates
    the run and its queue in one transaction; its own replay is then
    unavailable rather than rebuilt from deleted content."""

    api, clock = synced.api, synced.clock
    waiting = api.create("waiting card", state="waiting", waiting_for="Ann")
    synced.post("/api/review/explainer/acknowledge", {}).raise_for_status()
    clock.advance(days=40)
    session = api.start_raw().json()["id"]
    waiting = api.task(waiting["id"])
    decided = api.decide(waiting, "follow_up", title="Call Ann", session_id=session)
    created = decided["created_task"]["id"]
    commits = len(synced.transactions())
    path = f"/api/review/decisions/{decided['decision']['id']}/undo"
    body = {"expected_task_revision": decided["task"]["revision"]}
    undone = synced.post(path, body, "undo-1")
    assert undone.status_code == 200, undone.text
    assert len(synced.transactions()) == commits + 1
    changes = synced.transactions()[-1]["changes"]
    tombstones = {
        (c["entity_type"], tuple(c["record_key"]))
        for c in changes
        if c["operation"] == "tombstone"
    }
    assert tombstones >= {
        ("review_decision", (decided["decision"]["id"],)),
        ("task", (created,)),
    }
    assert (
        "review_decision",
        json.dumps([decided["decision"]["id"]]),
    ) not in synced.folded()
    retry = synced.post(path, body, "undo-1")
    assert retry.status_code == 409
    assert retry.json()["detail"] == {"reason": "idempotency_receipt_unavailable"}
    assert synced.review_base() == synced.snapshot()


def test_026_FR_014_an_applied_auto_park_publishes_the_marker_then_its_acknowledgement(
    synced: Synced,
) -> None:
    """The park marker, the parked task and the unseen-to-seen change are public
    records committed with the command that made them."""

    api, clock = synced.api, synced.clock
    task = api.create("Call Bob", state="next")
    synced.post("/api/review/explainer/acknowledge", {}).raise_for_status()
    clock.advance(days=21)
    keep_alive(synced.container)
    task = api.task(task["id"])
    formulation = task["formulation"]["id"]
    parked = synced.post(
        f"/api/tasks/{task['id']}/auto-park", {"formulation_id": formulation}
    )
    assert parked.json()["applied"] is True
    key = ("review_park_ack", json.dumps([task["id"], formulation]))
    marker = synced.folded()[key]
    assert marker["seen_at"] is None and marker["parked_at"]
    assert {"review_park_ack", "task"} <= {
        c["entity_type"] for c in synced.transactions()[-1]["changes"]
    }
    clock.advance(minutes=1)
    seen = synced.post(
        "/api/review/parks/acknowledge",
        {"items": [{"task_id": task["id"], "formulation_id": formulation}]},
    )
    assert seen.status_code == 204
    assert synced.folded()[key]["seen_at"] is not None
    assert PRIVATE_KEYS & set(_walk(synced.folded()[key])) == set()
    assert synced.review_base() == synced.snapshot()


def test_026_FR_022_the_projection_skips_foreign_duplicate_and_unpublished_writes(
    synced: Synced,
) -> None:
    """Only the owner's rows that have a public projection are published, once;
    a missing row is a tombstone only where the record can be deleted."""

    api = synced.api
    projection: ReviewProjection = synced.boundary.projection
    owner = synced.owner
    session = api.start_raw().json()["id"]
    decision = f"decision_{uuid.uuid4()}"
    writes = [
        WriteRecord("Review session", owner, session),
        WriteRecord("Review session", owner, session),
        WriteRecord("Review session", "someone-else", session),
        WriteRecord("Idempotency-Key", owner, "k"),
        WriteRecord("Navigator usage", owner, "2026-01-01"),
        WriteRecord("Review settings", owner, owner),
        WriteRecord("Review session", owner, "review_missing"),
        WriteRecord("Bulk release", owner, "bulk_missing"),
        WriteRecord("Park acknowledgement", owner, "task_x:form_y"),
        WriteRecord("Navigator consent", owner, "openai"),
        WriteRecord("Review receipt", owner, "task_x:waiting"),
        WriteRecord("Review decision", owner, decision),
    ]
    changes = projection.changes_for_writes(owner, writes)
    assert [(c["entity_type"], c["operation"]) for c in changes] == [
        ("review_session", "upsert"),
        ("review_decision_queue", "upsert"),
        ("review_receipt", "tombstone"),
        ("review_decision", "tombstone"),
    ]
    with allure.step("a stored decision republishes its run's queue by itself"):
        api.container.task_repo.save_review_settings(
            ReviewSettingsDocument(owner_id=owner)
        )
        again = projection.changes_for_writes(
            owner,
            [
                WriteRecord("Review settings", owner, owner),
                WriteRecord("Review decision", owner, decision),
            ],
        )
        assert [c["entity_type"] for c in again] == [
            "review_settings",
            "review_decision",
        ]
    with allure.step("the public codec needs a core"), pytest.raises(RuntimeError):
        ReviewProjection(synced.repo).public([])


def test_026_FR_005_a_recovery_that_would_write_is_unavailable_not_applied(
    synced: Synced,
) -> None:
    """Past 24 hours a start without a matching id would write a second run; the
    boundary refuses instead of running it again."""

    api, clock = synced.api, synced.clock
    body = {
        "mode": "quick",
        "entry": "list",
        "origin": "ios",
        "replace_open": True,
    }
    first = synced.post("/api/review/sessions", body, "start-late")
    assert first.status_code == 201
    receipts, commits = synced.receipts(), len(synced.transactions())
    clock.advance(hours=25)
    late = synced.post("/api/review/sessions", body, "start-late")
    assert late.status_code == 409
    assert late.json()["detail"] == {"reason": "idempotency_receipt_unavailable"}
    assert len(api.sessions()) == 1
    assert (synced.receipts(), len(synced.transactions())) == (receipts, commits)


def test_026_FR_005_a_receipt_that_cannot_be_read_back_fails_closed(
    synced: Synced,
) -> None:
    """A stored outcome the adapter cannot answer from is an integrity error, not
    a guess; the codecs refuse a missing result alike."""

    first = synced.post("/api/review/explainer/acknowledge", {}, "ack-1")
    assert first.status_code == 200
    with sqlite3.connect(synced.repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET metadata = "
            "json_set(metadata, '$.outcome', 'rejected') WHERE owner_id = ?",
            (synced.owner,),
        )
    broken = synced.post("/api/review/explainer/acknowledge", {}, "ack-1")
    assert broken.status_code == 400
    assert broken.json()["message"] == "COMMAND_INTEGRITY"
    for codec in (model_codec(ReviewSettingsDocument), dict_codec()):
        with pytest.raises(SyncCommandError):
            codec[1](None)


def test_026_FR_016_consent_keys_from_before_the_flag_adopt_or_collide_without_regrant(
    synced: Synced,
) -> None:
    """A legacy idempotency record written while OFF is adopted by the receipt
    boundary once ON: its own revoke replays, another command's key collides."""

    synced.grants_enabled()
    nav, clock = synced.nav, synced.clock
    synced.rust("off")
    first = nav.grant(key="old-grant")
    assert nav.revoke(key="old-revoke").status_code == 204
    assert synced.receipts() == 0
    synced.rust("on")
    clock.advance(minutes=1)
    assert nav.grant(key="new-grant").status_code == 200
    with allure.step("the revoke's own legacy key replays without revoking"):
        assert nav.revoke(key="old-revoke").status_code == 204
        assert nav.consent_current()
    with allure.step("a legacy grant key reused by a revoke collides, then replays"):
        assert nav.revoke(key="old-grant").status_code == 204
        assert not nav.consent_current()
        clock.advance(minutes=1)
        assert nav.grant(key="newer-grant").status_code == 200
        assert nav.revoke(key="old-grant").status_code == 204
        assert nav.consent_current()
    with allure.step("the legacy grant's own key still replays"):
        assert nav.grant(key="old-grant").json() == first.json()
    assert synced.review_base() == synced.snapshot()
    with allure.step("a new key while OFF keeps the legacy record"):
        synced.rust("off")
        assert nav.revoke(key="off-revoke").status_code == 204
        assert (
            synced.repo.get_idempotency(owner_id=synced.owner, key="off-revoke")
            is not None
        )


def test_026_FR_006_bulk_release_undo_and_run_commands_replay_their_first_answer(
    synced: Synced,
) -> None:
    """Every remaining legacy command answers a retry from its receipt, writing
    nothing, and a decision's queue republishes with only that decision written."""

    api, clock = synced.api, synced.clock
    inbox = api.create("inbox card", state="inbox")
    nxt = api.create("next card", state="next")
    synced.post("/api/review/explainer/acknowledge", {}).raise_for_status()
    clock.advance(days=40)
    session = api.start_raw().json()["id"]
    inbox, nxt = api.task(inbox["id"]), api.task(nxt["id"])
    item = {"task_id": inbox["id"], "expected_revision": inbox["revision"]}
    bulk = {"kind": "inbox_remainder", "items": [item]}
    released = synced.post("/api/review/bulk-releases", bulk, "bulk-1")
    assert released.status_code == 200, released.text
    before = (synced.receipts(), len(synced.transactions()))
    with allure.step("a release retry is the first response and writes nothing"):
        clock.advance(minutes=1)
        again = synced.post("/api/review/bulk-releases", bulk, "bulk-1")
        assert again.json() == released.json()
        assert (synced.receipts(), len(synced.transactions())) == before
    decided = synced.post(
        f"/api/tasks/{nxt['id']}/decisions",
        {
            "type": "complete",
            "expected_revision": nxt["revision"],
            "formulation_id": nxt["formulation"]["id"],
            "session_id": session,
        },
        "decide-1",
    )
    assert decided.status_code == 200, decided.text
    undo_path = f"/api/review/bulk-releases/{released.json()['id']}/undo"
    undone = synced.post(undo_path, {}, "bulk-undo-1")
    finish_path = f"/api/review/sessions/{session}/finish"
    finished = synced.post(finish_path, {}, "finish-1")
    assert undone.status_code == finished.status_code == 200
    before = (synced.receipts(), len(synced.transactions()))
    with allure.step("Undo and finish retries answer from their stored records"):
        clock.advance(minutes=1)
        assert synced.post(undo_path, {}, "bulk-undo-1").json() == undone.json()
        assert synced.post(finish_path, {}, "finish-1").json() == finished.json()
    assert (synced.receipts(), len(synced.transactions())) == before
    with allure.step("a stored decision alone republishes its run's queue"):
        decision = decided.json()["decision"]
        projection: ReviewProjection = synced.boundary.projection
        changes = projection.changes_for_writes(
            synced.owner,
            [WriteRecord("Review decision", synced.owner, decision["id"])],
        )
        assert [c["entity_type"] for c in changes] == [
            "review_decision",
            "review_decision_queue",
        ]


def test_026_FR_014_queue_projection_equals_the_queue_api_in_queue_order(
    synced: Synced,
) -> None:
    """Decided and set-aside ids follow the captured queue order, not decision
    time, and a set-aside card that is then decided is no longer set aside."""

    api, clock = synced.api, synced.clock
    for i in range(4):
        api.create(f"card {i}", state="next")
    synced.post("/api/review/explainer/acknowledge", {}).raise_for_status()
    clock.advance(days=40)
    session = api.start_raw().json()["id"]
    api.progress_raw(session, snapshot_decision_queue=True).raise_for_status()
    cards = api.queue("decisions", session)["items"]
    assert len(cards) == 4
    for card in (cards[1], cards[3]):
        api.progress_raw(session, set_aside_task_id=card["id"]).raise_for_status()
    with allure.step("decide out of queue order, one of them a set-aside card"):
        for card in (cards[3], cards[0]):
            api.decide(api.task(card["id"]), "complete", session_id=session)
    meta = api.queue("decisions", session)["meta"]
    queue = synced.folded()[("review_decision_queue", json.dumps([session]))]
    assert meta["decided_task_ids"] == [cards[0]["id"], cards[3]["id"]]
    assert meta["set_aside_task_ids"] == [cards[1]["id"]]
    assert queue["decided_task_ids"] == meta["decided_task_ids"]
    assert queue["set_aside_task_ids"] == meta["set_aside_task_ids"]
    assert synced.review_base() == synced.snapshot()


def test_026_FR_005_a_stale_recovery_after_undo_is_unavailable(
    synced: Synced,
) -> None:
    """Undo's tombstone redacts the decide receipt; retrying the original key
    would be stale, which recovery reports as unavailable, not as a conflict."""

    api = synced.api
    task = api.create("card", state="next")
    synced.post("/api/review/explainer/acknowledge", {}).raise_for_status()
    synced.clock.advance(days=40)
    task = api.task(task["id"])
    body = {
        "type": "complete",
        "expected_revision": task["revision"],
        "formulation_id": task["formulation"]["id"],
    }
    path = f"/api/tasks/{task['id']}/decisions"
    decided = synced.post(path, body, "decide-stale")
    assert decided.status_code == 200
    undone = api.undo_raw(
        decided.json()["decision"]["id"], decided.json()["task"]["revision"]
    )
    assert undone.status_code == 200
    before = (synced.receipts(), len(synced.transactions()))
    retry = synced.post(path, body, "decide-stale")
    assert retry.status_code == 409
    assert retry.json()["detail"] == {"reason": "idempotency_receipt_unavailable"}
    assert (synced.receipts(), len(synced.transactions())) == before
