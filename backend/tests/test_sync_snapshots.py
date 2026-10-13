"""026-FR-006/010/011/013/016/022 and SC-002: stable sync v1 snapshots (PR-33).

A snapshot is one owner-scoped base at one watermark: every public aggregate
record (tasks, projects, tags, subtasks, comments, the public Review
projections) plus final deletion versions, paged immutably as the same
canonical-byte chunks and digests as transaction transfers. These tests drive
the real routers with the production authority and container, over an app
whose writers publish through the receipt boundary (``Synced``).
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from time import perf_counter_ns
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.api.sync_delta import router as delta_router
from app.api.sync_snapshots import router as snapshot_router
from app.modules.tasks.sync import delta, snapshots
from app.modules.tasks.sync.command_handler import LegacyTagCommandHandler
from app.modules.tasks.sync.receipts import CommandRequest
from app.modules.tasks.sync.review_projection import PUBLIC_REVIEW_ENTITY_TYPES
from app.modules.tasks.sync.transfers import canonical_json
from tests.allure_evidence import attach_json, check_equal

from .conftest import FrozenClock
from .test_sync_delta import tombstone, upsert
from .test_sync_review_projection import Synced, run_journey

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Sync snapshots"),
    allure.story("A snapshot is one consistent base at one watermark"),
]

MIB = 1024 * 1024
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
    "fingerprint",
    "usage",
}
Base = dict[tuple[str, str], dict[str, Any]]


@pytest.fixture(autouse=True)
def _measure_fast_allure_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    # Allure stores millisecond timestamps; a real, sub-ms step can otherwise be
    # misclassified as an empty step by the taxonomy validator.
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


class Snap:
    """The snapshot and delta routes of one signed-in, rust-core-sync owner."""

    def __init__(self, synced: Synced) -> None:
        self.synced = synced
        self.client: TestClient = synced.api.client
        self.owner = synced.owner
        self.clock: FrozenClock = synced.clock
        # PR-63 mounts the routers in the application; the test mounts the real ones.
        app = self.client.app
        app.include_router(snapshot_router, prefix="/api")  # type: ignore[attr-defined]
        app.include_router(delta_router, prefix="/api")  # type: ignore[attr-defined]
        # The first sync request builds the production gateway (authority, units).
        capabilities = self.client.get(
            "/api/sync/v1/capabilities", params={"scope_id": self.owner}
        )
        assert capabilities.status_code == 200, capabilities.text

    def create(self, **override: Any) -> Any:
        body = {
            "scope_id": self.owner,
            "projection_schema_version": "1",
            **override,
        }
        return self.client.post("/api/sync/v1/snapshots", json=body)

    def manifest(self) -> dict[str, Any]:
        response = self.create()
        assert response.status_code == 200, response.text
        return dict(response.json())

    def page(self, snapshot_id: str, token: str, scope: str | None = None) -> Any:
        return self.client.get(
            f"/api/sync/v1/snapshots/{snapshot_id}",
            params={"scope_id": scope or self.owner, "page_token": token},
        )

    def download(self, manifest: dict[str, Any]) -> tuple[bytes, list[dict[str, Any]]]:
        """The verified decoded stream and the page envelopes, in index order."""
        token, pages, parts = manifest["first_page_token"], [], []
        while token:
            response = self.page(manifest["snapshot_id"], token)
            assert response.status_code == 200, response.text
            page = response.json()
            decoded = base64.b64decode(page["payload_base64"])
            assert page["page_index"] == len(parts)
            assert page["watermark"] == manifest["watermark"]
            assert page["page_sha256"] == hashlib.sha256(decoded).hexdigest()
            assert len(response.content) <= 4 * MIB
            assert (page["next_page_token"] is None) is (not page["has_more"])
            parts.append(decoded)
            pages.append(page)
            token = page["next_page_token"]
        stream = b"".join(parts)
        assert len(pages) == manifest["page_count"]
        assert len(stream) == manifest["total_bytes"]
        assert hashlib.sha256(stream).hexdigest() == manifest["sha256"]
        return stream, pages

    def changes(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        stream, _ = self.download(manifest)
        changes = json.loads(stream)
        assert len(changes) == manifest["record_count"]
        return list(changes)

    def delta(self, cursor: str) -> list[dict[str, Any]]:
        """Every transaction after ``cursor``, page by page."""
        transactions: list[dict[str, Any]] = []
        while True:
            response = self.client.get(
                "/api/sync/v1/changes",
                params={"scope_id": self.owner, "cursor": cursor},
            )
            assert response.status_code == 200, response.text
            page = response.json()
            assert "transaction_manifest" not in page
            transactions.extend(page["transactions"])
            if not page["has_more"]:
                return transactions
            cursor = page["next_cursor"]

    def sql(self, statement: str, *args: Any) -> list[sqlite3.Row]:
        with sqlite3.connect(self.synced.repo.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(statement, args).fetchall()

    def publish(self, key: str, changes: list[dict[str, Any]]) -> str:
        gateway = self.client.app.state.sync_gateway  # type: ignore[attr-defined]
        request = CommandRequest.legacy(self.owner, key, "task.create", {"title": key})
        with gateway.receipts.command(
            gateway.units, request, gateway.authority, now=gateway.clock()
        ) as command:
            receipt = command.accept(changes)
        return str(receipt["commit_seq"])


def fold(base: Base, changes: list[dict[str, Any]]) -> Base:
    """Apply Change objects in order, the way a client builds its confirmed base."""
    base = dict(base)
    for change in changes:
        key = (change["entity_type"], json.dumps(change["record_key"]))
        if change["operation"] == "tombstone":
            base.pop(key, None)
        else:
            base[key] = change["value"]
    return base


def same(label: str, actual: Base, expected: Base) -> None:
    """``check_equal`` for bases (their tuple keys are not JSON)."""

    def flat(base: Base) -> dict[str, Any]:
        return {f"{kind} {key}": value for (kind, key), value in base.items()}

    check_equal(label, flat(actual), flat(expected))


def fold_transactions(base: Base, transactions: list[dict[str, Any]]) -> Base:
    for transaction in transactions:
        base = fold(base, transaction["changes"])
    return base


def keys_of(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {*value, *(k for v in value.values() for k in keys_of(v))}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
    return set()


def ids(changes: list[dict[str, Any]]) -> set[str]:
    """First key component of each change (singleton records have none)."""
    return {c["record_key"][0] for c in changes if c["record_key"]}


def error_code(response: Any) -> str:
    body = response.json()
    assert set(body) == {"error", "correlation_id"}, body
    return str(body["error"]["code"])


@pytest.fixture
def snap(api_client: TestClient, frozen_clock: FrozenClock) -> Snap:
    container = api_client.app.state.container  # type: ignore[attr-defined]
    handler = container.task_service._legacy_tag_handler  # noqa: SLF001
    synced = Synced(api_client, frozen_clock)
    # ``Synced`` isolates the Review journey from Task writers; a snapshot suite
    # needs every writer to publish, as the production container does.
    container.task_service._legacy_tag_handler = handler  # noqa: SLF001
    return Snap(synced)


@pytest.fixture
def seeded(snap: Snap) -> dict[str, Any]:
    """Tasks, a project, a tag, children and the whole Review journey."""
    api = snap.synced.api
    client = snap.client
    run_journey(snap.synced)
    project = client.post(
        "/api/projects", json={"name": "Home"}, headers=api.key()
    ).json()
    tag = client.post("/api/tags", json={"name": "calls"}, headers=api.key()).json()
    task = api.create("tagged card", state="inbox")
    subtask = client.post(
        f"/api/tasks/{task['id']}/subtasks", json={"title": "Dial"}, headers=api.key()
    )
    comment = client.post(
        f"/api/tasks/{task['id']}/comments", json={"body": "Ann"}, headers=api.key()
    )
    assert subtask.status_code == comment.status_code == 201
    return {"project": project, "tag": tag, "task": task}


def test_026_FR_006_a_snapshot_holds_every_public_aggregate_record(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    """Tasks, projects, tags, subtasks, comments and each public Review type are
    in one canonical stream whose digests verify; the cursor names the watermark."""
    manifest = snap.manifest()
    with allure.step("the manifest names the committed watermark and cursor"):
        newest = snap.sql(
            "SELECT max(CAST(commit_seq AS INTEGER)) AS n FROM sync_change_transactions"
        )[0]["n"]
        assert manifest["watermark"] == str(newest)
        cursor = delta.decode_cursor(manifest["cursor"])
        assert (cursor.owner_id, cursor.commit_seq) == (snap.owner, str(newest))
        assert manifest["first_page_token"]
        attach_json("manifest", manifest)
    changes = snap.changes(manifest)
    with allure.step("every aggregate record type is present"):
        types = {c["entity_type"] for c in changes}
        assert types >= {"task", "project", "tag", "subtask", "comment"}
        assert types >= set(PUBLIC_REVIEW_ENTITY_TYPES) - {"review_park_ack"}
        assert {c["record_key"][0] for c in changes if c["entity_type"] == "tag"} == {
            seeded["tag"]["id"]
        }
    with allure.step("records are deterministic, versioned public upserts"):
        order = [(c["entity_type"], json.dumps(c["record_key"])) for c in changes]
        assert order == sorted(order) and len(set(order)) == len(order)
        for change in changes:
            assert change["record_version"].isdecimal()
            assert (change["operation"] == "upsert") is (change["value"] is not None)
        assert PRIVATE_KEYS & keys_of([c["value"] for c in changes]) == set()
    with allure.step("the base equals the folded feed and carries its versions"):
        base = fold({}, changes)
        same("snapshot == folded feed", base, snap.synced.folded())
        latest: dict[tuple[str, str], str] = {}
        for transaction in snap.synced.transactions():
            for change in transaction["changes"]:
                latest[(change["entity_type"], json.dumps(change["record_key"]))] = (
                    change["record_version"]
                )
        for change in changes:
            key = (change["entity_type"], json.dumps(change["record_key"]))
            assert change["record_version"] == latest[key], key


def test_026_FR_013_the_snapshot_is_identical_across_repeated_reads(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    """Pages are immutable: reading a page again returns the same bytes and the
    stream does not depend on how the client chunked its requests."""
    manifest = snap.manifest()
    first, _ = snap.download(manifest)
    again, _ = snap.download(manifest)
    check_equal("immutable", first.decode(), again.decode())
    second = snap.manifest()
    assert second["snapshot_id"] != manifest["snapshot_id"]
    assert second["watermark"] == manifest["watermark"]
    assert second["sha256"] == manifest["sha256"]


def test_026_FR_013_pages_are_canonical_byte_chunks_that_may_split_a_record(
    snap: Snap, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshots, "TRANSFER_PAGE_BYTES", 700)
    manifest = snap.manifest()
    stream, pages = snap.download(manifest)
    with allure.step("many pages, each no larger than the chunk size"):
        assert manifest["page_count"] > 5 and len(pages) == manifest["page_count"]
        sizes = [len(base64.b64decode(p["payload_base64"])) for p in pages]
        assert max(sizes) <= 700 and sum(sizes) == manifest["total_bytes"]
        assert [p["has_more"] for p in pages] == [True] * (len(pages) - 1) + [False]
        assert pages[-1]["next_page_token"] is None
    with allure.step("a chunk is not independently parseable; the stream is"):
        broken = 0
        for page in pages:
            try:
                json.loads(base64.b64decode(page["payload_base64"]))
            except ValueError:
                broken += 1
        assert broken > 0
        assert len(json.loads(stream)) == manifest["record_count"]
    with allure.step("the stream is RFC 8785 canonical JSON"):
        assert canonical_json(json.loads(stream)).encode() == stream


def test_026_SC_002_a_writer_during_materialization_is_wholly_in_or_wholly_out(
    snap: Snap, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writer that starts while the base is read waits for the owner lock: it
    is not in the base, and the delta from the watermark delivers it whole."""
    api = snap.synced.api
    before = snap.synced.folded()
    started, outcome = threading.Event(), {}
    original = snapshots.SnapshotStore._public_records

    def writer() -> None:
        started.set()
        outcome["response"] = snap.client.post(
            "/api/tasks", json={"title": "late writer"}, headers=api.key()
        )

    def racing(self: snapshots.SnapshotStore, owner: str) -> list[dict[str, Any]]:
        thread = threading.Thread(target=writer)
        thread.start()
        assert started.wait(5)
        thread.join(0.5)  # the writer is blocked on the owner lock we hold
        outcome["thread"] = thread
        return original(self, owner)

    monkeypatch.setattr(snapshots.SnapshotStore, "_public_records", racing)
    manifest = snap.manifest()
    outcome["thread"].join(10)
    assert outcome["response"].status_code == 201
    late = outcome["response"].json()
    changes = snap.changes(manifest)
    with allure.step("the late writer is wholly out of the base"):
        assert late["id"] not in ids(changes)
        same("base == feed before the writer", fold({}, changes), before)
    with allure.step("the delta from the watermark picks it up whole"):
        transactions = snap.delta(manifest["cursor"])
        assert len(transactions) == 1
        assert int(transactions[0]["commit_seq"]) == int(manifest["watermark"]) + 1
        assert ids(transactions[0]["changes"]) == {late["id"]}
    same(
        "snapshot + delta == feed",
        fold_transactions(fold({}, changes), transactions),
        snap.synced.folded(),
    )


def test_026_SC_002_a_writer_that_committed_first_is_wholly_in_the_base(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    api = snap.synced.api
    early = api.create("early writer", state="inbox")
    manifest = snap.manifest()
    changes = snap.changes(manifest)
    assert early["id"] in ids(changes)
    assert snap.delta(manifest["cursor"]) == []


def test_026_FR_006_snapshot_plus_delta_equals_the_live_public_state(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    """Fold the delta onto the base: it equals a fresh snapshot of the live state
    after further tasks, updates, children and Review writes."""
    api, client = snap.synced.api, snap.client
    manifest = snap.manifest()
    base = fold({}, snap.changes(manifest))
    with allure.step("more writes happen after the watermark"):
        created = api.create("after watermark", state="inbox")
        client.post(
            f"/api/tasks/{created['id']}/comments",
            json={"body": "later"},
            headers=api.key(),
        )
        client.post("/api/tags", json={"name": "errands"}, headers=api.key())
        snap.synced.post("/api/review/explainer/acknowledge", {"time_zone": "UTC"})
    transactions = snap.delta(manifest["cursor"])
    assert transactions
    caught_up = fold_transactions(base, transactions)
    with allure.step("a fresh snapshot of the live state equals base + delta"):
        fresh = snap.manifest()
        assert fresh["watermark"] == transactions[-1]["commit_seq"]
        same("snapshot ∪ delta == live", caught_up, fold({}, snap.changes(fresh)))
        same("and the feed", caught_up, snap.synced.folded())


def test_026_FR_010_expired_and_interrupted_snapshots_fail_closed(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    manifest = snap.manifest()
    with allure.step("the contract TTL is 30 minutes"):
        created = snap.clock()
        assert manifest["expires_at"] == (created + timedelta(minutes=30)).isoformat(
            timespec="microseconds"
        )
    with allure.step("a page just before expiry is served"):
        snap.clock.advance(minutes=29, seconds=59)
        assert (
            snap.page(manifest["snapshot_id"], manifest["first_page_token"]).status_code
            == 200
        )
    with allure.step("a continuation at the deadline is RESET_REQUIRED, not partial"):
        snap.clock.advance(seconds=1)
        response = snap.page(manifest["snapshot_id"], manifest["first_page_token"])
        assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")
        details = response.json()["error"]["details"]
        assert details["reset_reason"] == "snapshot_expired"
    with allure.step("a new snapshot starts again and expired content is gone"):
        again = snap.manifest()
        assert again["snapshot_id"] != manifest["snapshot_id"]
        assert (
            snap.page(again["snapshot_id"], again["first_page_token"]).status_code
            == 200
        )
        left = snap.sql(
            "SELECT count(*) AS n FROM sync_snapshot_pages WHERE snapshot_id = ?",
            manifest["snapshot_id"],
        )
        assert left[0]["n"] == 0


def test_026_FR_010_expiry_between_pages_never_yields_a_shorter_stream(
    snap: Snap, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshots, "TRANSFER_PAGE_BYTES", 900)
    manifest = snap.manifest()
    first = snap.page(manifest["snapshot_id"], manifest["first_page_token"]).json()
    assert first["has_more"]
    snap.clock.advance(minutes=31)
    response = snap.page(manifest["snapshot_id"], first["next_page_token"])
    assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")


def test_026_FR_011_deletion_invalidates_snapshots_holding_the_content(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    snap.publish("make-task", [upsert(1)])
    manifest = snap.manifest()
    with allure.step("a committed deletion redacts the retained snapshot pages"):
        snap.publish("delete-task", [tombstone(1)])
        response = snap.page(manifest["snapshot_id"], manifest["first_page_token"])
        assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")
        assert response.json()["error"]["details"]["reset_reason"] == "feed_changed"
        left = snap.sql("SELECT count(*) AS n FROM sync_snapshot_pages")
        assert left[0]["n"] == 0
    with allure.step("the next snapshot carries the final deletion version only"):
        fresh = snap.manifest()
        changes = snap.changes(fresh)
        gone = [c for c in changes if c["record_key"] == ["task_00001"]]
        assert len(gone) == 1
        assert gone[0]["operation"] == "tombstone" and gone[0]["value"] is None
        assert gone[0]["record_version"] == "2" and "edit_revision" not in gone[0]
        assert "task_00001" not in json.dumps([c["value"] for c in changes])
        assert fresh["cursor"] != manifest["cursor"]


def test_026_FR_011_a_continuation_cannot_outlive_a_feed_or_access_generation(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    for column, reason in (
        ("feed_generation", "feed_changed"),
        ("access_generation", "snapshot_expired"),
    ):
        manifest = snap.manifest()
        with sqlite3.connect(snap.synced.repo.db_path) as conn:
            conn.execute(
                f"UPDATE sync_scopes SET {column} = 'rotated-' || {column}"  # noqa: S608
            )
        response = snap.page(manifest["snapshot_id"], manifest["first_page_token"])
        assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")
        assert response.json()["error"]["details"]["reset_reason"] == reason


def test_026_FR_013_a_corrupt_stored_page_is_reset_not_served(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    manifest = snap.manifest()
    with sqlite3.connect(snap.synced.repo.db_path) as conn:
        conn.execute("UPDATE sync_snapshot_pages SET payload = x'00'")
    response = snap.page(manifest["snapshot_id"], manifest["first_page_token"])
    assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")


def test_026_FR_016_review_content_expiry_bounds_the_snapshot_lifetime(
    snap: Snap,
) -> None:
    """A decision's advisory Undo deadline is its seven-day source expiry: the
    snapshot never outlives it, so a page read across the deadline resets."""
    api, clock = snap.synced.api, snap.clock
    snap.synced.grants_enabled()
    waiting = api.create("waiting card", state="waiting", waiting_for="Ann")
    clock.advance(days=40)
    session = snap.synced.api.start_raw().json()["id"]
    api.progress_raw(session, snapshot_decision_queue=True, current_step="decisions")
    waiting = api.task(waiting["id"])
    decided = api.decide_raw(
        waiting, "follow_up", title="Call Ann", session_id=session
    ).json()
    clock.advance(days=6, hours=23, minutes=50)
    manifest = snap.manifest()
    changes = snap.changes(manifest)
    decision = next(c for c in changes if c["entity_type"] == "review_decision")
    deadline = decision["value"]["undo_available_until"]
    assert decision["record_key"] == [decided["decision"]["id"]]
    with allure.step("the snapshot expires at the source deadline, before the TTL"):
        assert manifest["expires_at"][:19] == deadline[:19]
        assert manifest["expires_at"] < (clock() + timedelta(minutes=30)).isoformat()
    with allure.step("a read across the deadline is RESET_REQUIRED"):
        clock.advance(minutes=11)
        response = snap.page(manifest["snapshot_id"], manifest["first_page_token"])
        assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")
    with allure.step(
        "the decision record survives the Undo window in a fresh snapshot"
    ):
        fresh = snap.changes(snap.manifest())
        assert any(c["entity_type"] == "review_decision" for c in fresh)


def test_026_FR_011_authorization_is_rechecked_for_every_page(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    manifest = snap.manifest()
    token = manifest["first_page_token"]
    with allure.step("sync turned off for the scope stops continuation"):
        snap.synced.rust("off")
        response = snap.page(manifest["snapshot_id"], token)
        assert (response.status_code, error_code(response)) == (403, "ACCESS_DENIED")
        assert snap.create().status_code == 403
        snap.synced.rust("on")
    with allure.step("the same token works again once authority is current"):
        assert snap.page(manifest["snapshot_id"], token).status_code == 200
    with allure.step("a closed session cannot read any page"):
        anonymous = TestClient(snap.client.app)
        response = anonymous.get(
            f"/api/sync/v1/snapshots/{manifest['snapshot_id']}",
            params={"scope_id": snap.owner, "page_token": token},
        )
        assert (response.status_code, error_code(response)) == (401, "AUTH_REQUIRED")
        assert anonymous.post("/api/sync/v1/snapshots", json={}).status_code == 401


def test_026_FR_011_foreign_and_unknown_snapshots_read_the_same(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    manifest = snap.manifest()
    with sqlite3.connect(snap.synced.repo.db_path) as conn:
        conn.execute(
            "INSERT INTO sync_snapshots SELECT 'user_someone_else', 'foreign-id', "
            "watermark, feed_generation, access_generation, page_count, record_count, "
            "total_bytes, sha256, created_at, expires_at FROM sync_snapshots LIMIT 1"
        )
    token = manifest["first_page_token"]
    bodies = []
    for snapshot_id in ("foreign-id", "never-existed"):
        response = snap.page(snapshot_id, token)
        assert (response.status_code, error_code(response)) == (
            404,
            "RESOURCE_NOT_FOUND",
        )
        body = response.json()
        body.pop("correlation_id")
        bodies.append(body)
    check_equal("same body", bodies[0], bodies[1])
    with allure.step("a foreign scope reads as unknown for page and create"):
        foreign = snap.page(manifest["snapshot_id"], token, scope="user_someone_else")
        assert (foreign.status_code, error_code(foreign)) == (404, "RESOURCE_NOT_FOUND")
        created = snap.create(scope_id="user_someone_else")
        assert (created.status_code, error_code(created)) == (404, "RESOURCE_NOT_FOUND")
        assert "user_someone_else" not in created.text + foreign.text


def test_026_FR_011_requests_and_tokens_are_validated(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    manifest = snap.manifest()
    other = snap.manifest()
    with allure.step("a malformed or unknown-field body is INVALID_REQUEST"):
        for body in (
            {"scope_id": snap.owner},
            {"scope_id": snap.owner, "projection_schema_version": "1", "x": 1},
            {"scope_id": "", "projection_schema_version": "1"},
            {"scope_id": snap.owner, "projection_schema_version": None},
        ):
            response = snap.client.post("/api/sync/v1/snapshots", json=body)
            assert error_code(response) == "INVALID_REQUEST", body
        raw = snap.client.post("/api/sync/v1/snapshots", content=b"{not json")
        assert (raw.status_code, error_code(raw)) == (400, "INVALID_REQUEST")
    with allure.step("an unsupported projection schema is UPGRADE_REQUIRED"):
        response = snap.create(projection_schema_version="2")
        assert (response.status_code, error_code(response)) == (426, "UPGRADE_REQUIRED")
        assert snap.create(projection_schema_version=1).status_code == 200
        assert error_code(snap.create(projection_schema_version=True)) in {
            "INVALID_REQUEST",
            "UPGRADE_REQUIRED",
        }
    with allure.step("a token of another snapshot or past the end is refused"):
        response = snap.page(manifest["snapshot_id"], other["first_page_token"])
        assert error_code(response) == "INVALID_REQUEST"
        bad = base64.urlsafe_b64encode(
            json.dumps({"v": 1, "t": manifest["snapshot_id"], "i": 99}).encode()
        ).decode()
        assert error_code(snap.page(manifest["snapshot_id"], bad)) == "INVALID_REQUEST"
        assert error_code(snap.page(manifest["snapshot_id"], "junk")) == (
            "INVALID_REQUEST"
        )
    with allure.step("an oversized body is refused before it is read"):
        response = snap.client.post(
            "/api/sync/v1/snapshots", content=b" " * (64 * 1024 + 1)
        )
        assert (response.status_code, error_code(response)) == (
            413,
            "COMMAND_TOO_LARGE",
        )


def test_026_FR_013_records_written_before_versions_were_kept_start_at_one(
    snap: Snap,
) -> None:
    """A row that predates the feed gets version 1 in the base, and the next
    committed change to it continues from there instead of reusing it."""
    api = snap.synced.api
    old = api.seed("inbox", "predates sync")
    manifest = snap.manifest()
    changes = snap.changes(manifest)
    entry = next(c for c in changes if c["record_key"] == [old.id])
    assert entry["record_version"] == "1"
    stored = snap.sql(
        "SELECT record_version FROM sync_record_versions WHERE record_key = ?",
        json.dumps([old.id]),
    )
    assert [r["record_version"] for r in stored] == ["1"]
    again = snap.changes(snap.manifest())
    assert (
        next(c for c in again if c["record_key"] == [old.id])["record_version"] == "1"
    )
    updated = snap.client.patch(
        f"/api/tasks/{old.id}",
        json={"details": "now synced", "expected_revision": old.revision},
        headers=api.key(),
    )
    assert updated.status_code == 200, updated.text
    later = snap.delta(manifest["cursor"])
    versions = [
        c["record_version"]
        for t in later
        for c in t["changes"]
        if c["record_key"] == [old.id]
    ]
    assert versions == ["2"]


def test_026_FR_013_only_the_newest_snapshots_keep_their_pages(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    manifests = [snap.manifest() for _ in range(snapshots.MAX_LIVE_SNAPSHOTS + 1)]
    oldest = snap.page(manifests[0]["snapshot_id"], manifests[0]["first_page_token"])
    assert (oldest.status_code, error_code(oldest)) == (409, "RESET_REQUIRED")
    newest = manifests[-1]
    assert (
        snap.page(newest["snapshot_id"], newest["first_page_token"]).status_code == 200
    )


def test_026_SC_002_a_changed_watermark_during_materialization_fails_closed(
    snap: Snap, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defense in depth: if the scope counter moved while the base was read, the
    attempt is refused and nothing is stored -- never a base of unknown watermark."""
    calls = iter(range(1, 100))
    monkeypatch.setattr(
        snapshots.SnapshotStore,
        "_watermark",
        staticmethod(lambda c, o: str(next(calls))),
    )
    response = snap.create()
    assert (response.status_code, error_code(response)) == (
        503,
        "TEMPORARILY_UNAVAILABLE",
    )
    assert snap.sql("SELECT 1 FROM sync_snapshots") == []
    assert snap.sql("SELECT 1 FROM sync_snapshot_pages") == []


def test_026_FR_022_capabilities_advertise_snapshot_support(snap: Snap) -> None:
    caps = snap.client.get(
        "/api/sync/v1/capabilities", params={"scope_id": snap.owner}
    ).json()
    assert caps["recovery"]["snapshot_supported"] is True
    assert caps["limits"]["snapshot_ttl_seconds"] == 1800


def test_026_FR_006_child_rows_match_the_feed_writer_shapes(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    """The snapshot's subtask/comment encoders are the feed's own shapes."""
    repo = snap.synced.repo
    task_id = seeded["task"]["id"]
    for sub in repo.list_subtasks(owner_id=snap.owner, task_id=task_id):
        assert snapshots.encode_subtask(sub) == LegacyTagCommandHandler._child_public(
            sub
        )  # noqa: SLF001
    for comment in repo.list_comments(owner_id=snap.owner, task_id=task_id):
        assert snapshots.encode_comment(
            comment
        ) == LegacyTagCommandHandler._child_public(
            comment
        )  # noqa: SLF001
        edited = comment.model_copy(update={"edited_at": comment.created_at})
        assert snapshots.encode_comment(
            edited
        ) == LegacyTagCommandHandler._child_public(
            edited
        )  # noqa: SLF001


def test_026_FR_011_a_partly_dropped_snapshot_is_reset_not_served(
    snap: Snap, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshots, "TRANSFER_PAGE_BYTES", 900)
    manifest = snap.manifest()
    with sqlite3.connect(snap.synced.repo.db_path) as conn:
        conn.execute("DELETE FROM sync_snapshot_pages WHERE page_index = 3")
    response = snap.page(manifest["snapshot_id"], manifest["first_page_token"])
    assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")


def test_026_FR_016_a_record_past_its_source_retention_voids_the_snapshot(
    snap: Snap, seeded: dict[str, Any]
) -> None:
    """The deadline is read from the feed on every fetch: a record whose current
    copy is past its absolute expiry makes the page RESET_REQUIRED
    content_expired, and a later superseding change clears it."""
    snap.publish("expiring", [upsert(5)])
    manifest = snap.manifest()
    assert (
        snap.page(manifest["snapshot_id"], manifest["first_page_token"]).status_code
        == 200
    )
    soon = (snap.clock() + timedelta(minutes=5)).isoformat()
    with sqlite3.connect(snap.synced.repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_change_records SET source_expires_at = ? "
            "WHERE record_key = ?",
            (soon, json.dumps(["task_00005"], separators=(",", ":"))),
        )
    assert (
        snap.page(manifest["snapshot_id"], manifest["first_page_token"]).status_code
        == 200
    )
    snap.clock.advance(minutes=6)
    response = snap.page(manifest["snapshot_id"], manifest["first_page_token"])
    assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")
    assert response.json()["error"]["details"]["reset_reason"] == "content_expired"
    with allure.step("a snapshot of the still-expired copy is void as well"):
        stale = snap.manifest()
        assert (
            snap.page(stale["snapshot_id"], stale["first_page_token"]).status_code
            == 409
        )
    with allure.step("a superseding change clears it for the next snapshot"):
        snap.publish("replaced", [upsert(5, "redacted")])
        clean = snap.manifest()
        assert (
            snap.page(clean["snapshot_id"], clean["first_page_token"]).status_code
            == 200
        )
