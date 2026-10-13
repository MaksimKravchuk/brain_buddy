"""026-FR-004/006/008/010/011 and SC-002/004: the sync v1 delta feed and transfers."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.api.sync_delta import router as delta_router
from app.modules.tasks.domain import TaskDocument
from app.modules.tasks.rust_adapter import RustCore
from app.modules.tasks.rust_task_facade import encode_task
from app.modules.tasks.sync import delta, transfers
from app.modules.tasks.sync.receipts import CommandRequest, ScopeAuthority
from tests.allure_evidence import attach_json, check_equal
from tests.conftest import (
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    _build_authenticated_client,
)

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Sync delta feed"),
    allure.story("Pages carry whole commit-ordered transactions"),
]
FLAG = "rust_core_sync"
MIB = 1024 * 1024
NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
COMMON_KEYS = {"scope_id", "server_generation", "server_now", "correlation_id"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    client, _ = _build_authenticated_client(
        tmp_path,
        monkeypatch,
        subdir="sync-delta",
        email=TEST_USER_EMAIL,
        password=TEST_USER_PASSWORD,
    )
    # PR-63 mounts the router in the application; the test mounts the real one.
    client.app.include_router(delta_router, prefix="/api")  # type: ignore[attr-defined]
    client.app.state.container.feature_flag_service.set_mode(  # type: ignore[attr-defined]
        FLAG, "on", operator_id="sync-delta"
    )
    # The first sync request builds the production gateway (authority, units).
    owner = client.get("/api/auth/me").json()["id"]
    assert client.get(f"/api/sync/v1/capabilities?scope_id={owner}").status_code == 200
    yield client
    client.close()


@pytest.fixture()
def owner(client) -> str:
    return client.get("/api/auth/me").json()["id"]


@pytest.fixture()
def gateway(client):
    return client.app.state.sync_gateway  # type: ignore[attr-defined]


def task_value(index: int, details: str = "") -> dict[str, Any]:
    task = TaskDocument(
        id=f"task_{index:05d}",
        owner_id="x",
        title=f"Task {index}",
        state="inbox",
        order_key=index,
        created_at=NOW,
        updated_at=NOW,
        details=details or None,
    )
    return encode_task(task)


def upsert(index: int, details: str = "") -> dict[str, Any]:
    return {
        "operation": "upsert",
        "entity_type": "task",
        "value": task_value(index, details),
    }


def tombstone(index: int) -> dict[str, Any]:
    return {
        "operation": "tombstone",
        "entity_type": "task",
        "record_key": [f"task_{index:05d}"],
    }


def publish(gateway, owner: str, key: str, changes: list[dict[str, Any]]) -> str:
    """Commit ``changes`` through the receipt boundary; returns the commit_seq."""
    request = CommandRequest.legacy(owner, key, "task.create", {"title": key})
    with gateway.receipts.command(
        gateway.units, request, gateway.authority, now=gateway.clock()
    ) as command:
        receipt = command.accept(changes)
    return str(receipt["commit_seq"])


def cursor_at(gateway, owner: str, seq: str = "0") -> str:
    with gateway.units.begin(owner) as unit:
        current = gateway.receipts.admit(unit, gateway.authority)
    return delta.encode_cursor(current, seq)


def pull(client, owner: str, cursor: str, **query: Any):
    return client.get(
        "/api/sync/v1/changes",
        params={"scope_id": owner, "cursor": cursor, **query},
    )


def error_code(response) -> str:  # type: ignore[no-untyped-def]
    body = response.json()
    assert set(body) == {"error", "correlation_id"}, body
    return str(body["error"]["code"])


def sql(gateway, statement: str, *args: Any) -> list[sqlite3.Row]:
    with sqlite3.connect(gateway.units._repo.db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(statement, args).fetchall()


def walk(client, owner: str, cursor: str, **query: Any) -> list[dict[str, Any]]:
    """Every page from ``cursor`` until ``has_more`` is false."""
    pages = []
    while True:
        response = pull(client, owner, cursor, **query)
        assert response.status_code == 200, response.text
        page = response.json()
        pages.append(page)
        if not page["has_more"]:
            return pages
        assert page["next_cursor"] != cursor or page.get("transaction_manifest")
        cursor = page["next_cursor"]


def download(client, manifest: dict[str, Any]) -> tuple[bytes, list[bytes]]:
    token, parts = manifest["first_page_token"], []
    while token:
        response = client.get(
            f"/api/sync/v1/transactions/{manifest['transfer_id']}",
            params={"page_token": token},
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["page_index"] == len(parts)
        decoded = base64.b64decode(page["payload_base64"])
        assert page["page_sha256"] == hashlib.sha256(decoded).hexdigest()
        assert len(decoded) <= MIB
        assert len(response.content) <= 4 * MIB
        parts.append(decoded)
        token = page["next_page_token"]
        assert (token is None) is (not page["has_more"])
    return b"".join(parts), parts


def test_026_FR_011_unauthenticated_and_foreign_requests_get_the_protocol_error(
    client, owner, gateway
):
    anonymous = TestClient(client.app)
    cursor = cursor_at(gateway, owner)
    with allure.step("both routes answer 401 AUTH_REQUIRED without a session"):
        calls = {
            "changes": anonymous.get(
                "/api/sync/v1/changes", params={"scope_id": owner, "cursor": cursor}
            ),
            "transfer": anonymous.get(
                "/api/sync/v1/transactions/x", params={"page_token": "t"}
            ),
        }
        codes = {name: (r.status_code, error_code(r)) for name, r in calls.items()}
        attach_json("responses", codes)
        assert set(codes.values()) == {(401, "AUTH_REQUIRED")}
    with allure.step("a foreign and an unknown scope read as the same 404"):
        bodies = []
        for scope in ("user_someone_else", "scope-unknown"):
            response = pull(client, scope, cursor)
            assert (response.status_code, error_code(response)) == (
                404,
                "RESOURCE_NOT_FOUND",
            )
            assert scope not in response.text
            body = response.json()
            body.pop("correlation_id")
            bodies.append(body)
        check_equal("same body", bodies[0], bodies[1])
    with allure.step("a disabled scope is ACCESS_DENIED, not an empty page"):
        flags = client.app.state.container.feature_flag_service
        flags.set_mode(FLAG, "off", operator_id="sync-delta")
        response = pull(client, owner, cursor)
        attach_json("status", response.status_code)
        assert (response.status_code, error_code(response)) == (403, "ACCESS_DENIED")
    with allure.step("a malformed cursor or limit is INVALID_REQUEST"):
        flags.set_mode(FLAG, "on", operator_id="sync-delta")
        for query in ({"cursor": "%%%"}, {"cursor": "e30"}, {"limit": "0"}):
            response = pull(client, owner, **{"cursor": cursor, **query})
            attach_json("status", response.status_code)
            assert (response.status_code, error_code(response)) == (
                422,
                "INVALID_REQUEST",
            )


def test_026_FR_004_pages_return_whole_transactions_in_commit_order(
    client, owner, gateway
):
    start = cursor_at(gateway, owner)
    with allure.step("five transactions commit in order"):
        seqs = [
            publish(gateway, owner, f"cmd-{n}", [upsert(n), upsert(n + 100)])
            for n in range(1, 6)
        ]
        attach_json("commit sequences", seqs)
        assert seqs == ["1", "2", "3", "4", "5"]
    with allure.step("a two-transaction limit walks them without gap or repeat"):
        pages = walk(client, owner, start, limit=2)
        listed = [t["commit_seq"] for page in pages for t in page["transactions"]]
        check_equal("order", listed, seqs)
        check_equal("page sizes", [len(p["transactions"]) for p in pages], [2, 2, 1])
        check_equal("has_more", [p["has_more"] for p in pages], [True, True, False])
        for page in pages:
            assert set(page) >= COMMON_KEYS
            assert page["high_watermark"] == "5"
            for transaction in page["transactions"]:
                assert len(transaction["changes"]) == 2
                assert set(transaction) == {
                    "transaction_id",
                    "commit_seq",
                    "source_command_id",
                    "changes",
                }
    with allure.step("each cursor names the position after its page"):
        assert pages[0]["from_cursor"] == start
        check_equal("chained", pages[1]["from_cursor"], pages[0]["next_cursor"])
        check_equal(
            "last position",
            delta.decode_cursor(pages[2]["next_cursor"]).commit_seq,
            "5",
        )
    with allure.step("an empty page at the head keeps the input cursor"):
        head = pages[-1]["next_cursor"]
        page = pull(client, owner, head).json()
        check_equal(
            "empty page",
            (page["transactions"], page["has_more"], page["next_cursor"]),
            ([], False, head),
        )
    with allure.step("a transaction committed later appears after the same cursor"):
        publish(gateway, owner, "cmd-late", [upsert(9)])
        page = pull(client, owner, head).json()
        check_equal("late", [t["commit_seq"] for t in page["transactions"]], ["6"])


def test_026_FR_006_a_500_item_bulk_with_more_than_500_changes_is_one_transaction(
    client, owner, gateway
):
    with allure.step("a bulk of 500 releases plus receipts commits 1,003 changes"):
        changes = [upsert(n) for n in range(1, 502)]
        changes += [tombstone(n) for n in range(1000, 1500)]
        changes += [upsert(n) for n in range(2000, 2002)]
        assert len(changes) == 1003
        publish(gateway, owner, "bulk", changes)
        # Tombstones redact history, so a cursor is taken on the new generation.
        start = cursor_at(gateway, owner)
    with allure.step("the default page delivers all of it, none held back"):
        page = pull(client, owner, start).json()
        (transaction,) = page["transactions"]
        attach_json("counts", {"changes": len(transaction["changes"])})
        check_equal("changed rows", len(transaction["changes"]), 1003)
        assert "transaction_manifest" not in page
        assert page["has_more"] is False
    with allure.step("tombstones carry no value and every key appears once"):
        deleted = [c for c in transaction["changes"] if c["operation"] == "tombstone"]
        assert len(deleted) == 500
        assert all(c["value"] is None for c in deleted)
        keys = [
            (c["entity_type"], json.dumps(c["record_key"]))
            for c in transaction["changes"]
        ]
        check_equal("unique keys", len(set(keys)), len(keys))
        assert all(c["record_version"] == "1" for c in transaction["changes"])


def test_026_FR_006_multi_page_archive_and_tag_deletion_loses_no_record(
    client, owner, gateway
):
    with allure.step("an archive upserts 700 tasks and a tag deletion tombstones 700"):
        archive = [upsert(n) for n in range(700)]
        deletion = [tombstone(n) for n in range(1000, 1700)] + [upsert(900)]
        publish(gateway, owner, "archive", archive)
        publish(gateway, owner, "tag-delete", deletion)
        start = cursor_at(gateway, owner)
    with allure.step("one transaction per page still delivers each in full"):
        pages = walk(client, owner, start, limit=1)
        sizes = [len(p["transactions"][0]["changes"]) for p in pages]
        check_equal("changes per page", sizes, [700, 701])
        check_equal("has_more", [p["has_more"] for p in pages], [True, False])
    with allure.step("deleted records carry their final record version"):
        final = pages[1]["transactions"][0]["changes"]
        versions = {
            c["record_key"][0]: c["record_version"]
            for c in final
            if c["operation"] == "tombstone"
        }
        check_equal("tombstone versions", set(versions.values()), {"1"})


def test_026_FR_006_inline_pages_stop_at_the_one_mebibyte_target(
    client, owner, gateway
):
    start = cursor_at(gateway, owner)
    big = "y" * 20_000
    with allure.step("transactions of about 120 KiB each commit"):
        for n in range(20):
            publish(
                gateway, owner, f"cmd-{n}", [upsert(n * 10 + k, big) for k in range(6)]
            )
    with allure.step("a page holds whole transactions within the target"):
        pages = walk(client, owner, start)
        listed = [t["commit_seq"] for p in pages for t in p["transactions"]]
        check_equal("complete and ordered", listed, [str(n) for n in range(1, 21)])
        sizes = [
            len(json.dumps(p["transactions"], separators=(",", ":"))) for p in pages
        ]
        attach_json("page bytes", sizes)
        assert len(pages) > 1
        assert all(size <= MIB for size in sizes)
    with allure.step("the hundred-transaction cap applies to small transactions"):
        for n in range(130):
            publish(gateway, owner, f"small-{n}", [upsert(5000 + n)])
        page = pull(client, owner, pages[-1]["next_cursor"], limit=500).json()
        check_equal("capped", len(page["transactions"]), 100)
        assert page["has_more"] is True


def oversized(gateway, owner: str, records: int = 300) -> list[dict[str, Any]]:
    """A ~6 MiB transaction: incompressible 20,000-character after-images."""
    changes = [
        upsert(n, hashlib.sha256(str(n).encode()).hexdigest() * 312)
        for n in range(records)
    ]
    publish(gateway, owner, "huge", changes)
    return changes


def test_026_FR_008_an_oversized_transaction_is_a_manifest_plus_byte_chunks(
    client, owner, gateway
):
    start = cursor_at(gateway, owner)
    publish(gateway, owner, "before", [upsert(1)])
    oversized(gateway, owner)
    publish(gateway, owner, "after", [upsert(2)])
    with allure.step("the inline transaction before it is served on its own"):
        first = pull(client, owner, start).json()
        check_equal(
            "first page", [t["commit_seq"] for t in first["transactions"]], ["1"]
        )
        assert first["has_more"] is True
        assert "transaction_manifest" not in first
    with allure.step("the next page is an empty page plus a manifest"):
        second = pull(client, owner, first["next_cursor"]).json()
        manifest = second["transaction_manifest"]
        attach_json("manifest", manifest)
        assert second["transactions"] == [] and second["has_more"] is True
        assert second["next_cursor"] == first["next_cursor"]
        assert manifest["commit_seq"] == "2"
        assert manifest["page_count"] == 6 and manifest["record_count"] == 300
        assert manifest["total_bytes"] > 4 * MIB
        assert delta.decode_cursor(manifest["after_cursor"]).commit_seq == "2"
        assert set(manifest) == {
            "transfer_id",
            "transaction_id",
            "commit_seq",
            "source_command_id",
            "page_count",
            "record_count",
            "total_bytes",
            "sha256",
            "expires_at",
            "first_page_token",
            "after_cursor",
        }
    with allure.step("bounded decoded chunks reassemble the canonical Change array"):
        stream, parts = download(client, manifest)
        check_equal("pages", len(parts), manifest["page_count"])
        check_equal("bytes", len(stream), manifest["total_bytes"])
        check_equal("digest", hashlib.sha256(stream).hexdigest(), manifest["sha256"])
        assert max(map(len, parts)) <= MIB
        changes = json.loads(stream)
        assert len(changes) == 300
        assert stream.decode() == transfers.canonical_json(changes)
    with allure.step("a chunk crosses a record boundary, so it is never parsed alone"):
        with pytest.raises(ValueError, match=r"."):
            json.loads(parts[0])
        ends = [len(transfers.canonical_json(c)) for c in changes]
        boundaries = {sum(ends[: i + 1]) + i + 1 for i in range(len(ends))}
        cuts = {sum(map(len, parts[: i + 1])) for i in range(len(parts) - 1)}
        attach_json("cuts", sorted(cuts)[:3])
        assert cuts - boundaries
    with allure.step("the same oversized transaction keeps one transfer"):
        again = pull(client, owner, first["next_cursor"]).json()["transaction_manifest"]
        check_equal("transfer id", again["transfer_id"], manifest["transfer_id"])
        assert len(sql(gateway, "SELECT 1 FROM sync_transfers")) == 1
    with allure.step("the after_cursor resumes strictly after the transaction"):
        rest = pull(client, owner, manifest["after_cursor"]).json()
        check_equal("rest", [t["commit_seq"] for t in rest["transactions"]], ["3"])
        assert rest["has_more"] is False


def test_026_FR_008_a_transaction_below_the_hard_limit_stays_inline(
    client, owner, gateway
):
    start = cursor_at(gateway, owner)
    publish(
        gateway,
        owner,
        "large",
        [
            upsert(n, hashlib.sha256(str(n).encode()).hexdigest() * 312)
            for n in range(190)
        ],
    )
    with allure.step("about 3.8 MiB is served inline within the 4 MiB response"):
        response = pull(client, owner, start)
        page = response.json()
        attach_json("bytes", {"response": len(response.content)})
        assert len(page["transactions"]) == 1
        assert "transaction_manifest" not in page
        assert MIB * 3 < len(response.content) < MIB * 4


def test_026_FR_010_transfer_expiry_is_reset_required(client, owner, gateway):
    start = cursor_at(gateway, owner)
    oversized(gateway, owner)
    manifest = pull(client, owner, start).json()["transaction_manifest"]
    with allure.step("a page inside the TTL is served"):
        url = f"/api/sync/v1/transactions/{manifest['transfer_id']}"
        ok = client.get(url, params={"page_token": manifest["first_page_token"]})
        assert ok.status_code == 200
    with allure.step("after 30 minutes the transfer is RESET_REQUIRED"):
        later = gateway.clock() + timedelta(minutes=31)
        client.app.state.sync_gateway = dataclasses.replace(
            gateway, clock=lambda: later
        )
        response = client.get(url, params={"page_token": manifest["first_page_token"]})
        body = response.json()
        attach_json("body", body)
        assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")
        assert body["error"]["details"]["reset_reason"] == "transfer_expired"
    with allure.step("a new pull materializes a fresh transfer; content aged out"):
        fresh = pull(client, owner, start).json()["transaction_manifest"]
        assert fresh["transfer_id"] != manifest["transfer_id"]
        old = sql(
            gateway,
            "SELECT count(*) n FROM sync_transfer_pages WHERE transfer_id = ?",
            manifest["transfer_id"],
        )
        check_equal("expired pages removed", old[0]["n"], 0)


def test_026_FR_010_deleting_content_invalidates_transfers_and_cursors(
    client, owner, gateway
):
    start = cursor_at(gateway, owner)
    oversized(gateway, owner)
    manifest = pull(client, owner, start).json()["transaction_manifest"]
    url = f"/api/sync/v1/transactions/{manifest['transfer_id']}"
    with allure.step("a tombstone redacts history and changes the feed generation"):
        publish(gateway, owner, "delete", [tombstone(7)])
        pages = sql(gateway, "SELECT count(*) n FROM sync_transfer_pages")
        check_equal("materialized copies removed", pages[0]["n"], 0)
    with allure.step("the transfer and the old cursor are RESET_REQUIRED"):
        response = client.get(url, params={"page_token": manifest["first_page_token"]})
        assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")
        assert response.json()["error"]["details"]["reset_reason"] == "feed_changed"
        stale = pull(client, owner, start)
        assert (stale.status_code, error_code(stale)) == (409, "RESET_REQUIRED")
        assert stale.json()["error"]["details"]["reset_reason"] == "feed_changed"
        # The redacted deleted content is not readable from any later page.
        assert "task_00007" not in stale.text
    with allure.step("a cursor issued after the deletion works again"):
        fresh = cursor_at(gateway, owner, "2")
        assert pull(client, owner, fresh).json()["transactions"] == []


def test_026_FR_010_expired_pruned_restored_and_foreign_cursors_reset(
    client, owner, gateway
):
    start = cursor_at(gateway, owner)
    for n in range(3):
        publish(gateway, owner, f"cmd-{n}", [upsert(n)])
    reasons = {}

    def reset(label: str, cursor: str) -> None:
        response = pull(client, owner, cursor)
        assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")
        reasons[label] = response.json()["error"]["details"]["reset_reason"]

    with allure.step("a cursor ahead of the scope (backup restore) resets"):
        reset("restore", cursor_at(gateway, owner, "99"))
    with allure.step("another feed or access generation resets"):
        with gateway.units.begin(owner) as unit:
            current = gateway.receipts.admit(unit, gateway.authority)
        for label, changed in (
            ("feed", dataclasses.replace(current, feed_generation="other")),
            ("access", dataclasses.replace(current, access_generation="other")),
            ("owner", dataclasses.replace(current, owner_id="someone-else")),
        ):
            reset(label, delta.encode_cursor(changed, "1"))
    with allure.step("a position pruned from the 90-day window resets"):
        sql_conn = sqlite3.connect(gateway.units._repo.db_path)
        with sql_conn:
            sql_conn.execute(
                "DELETE FROM sync_change_transactions WHERE commit_seq = '1'"
            )
        sql_conn.close()
        reset("pruned", start)
        # A cursor at or after the retained start is still valid.
        ok = pull(client, owner, cursor_at(gateway, owner, "1"))
        assert [t["commit_seq"] for t in ok.json()["transactions"]] == ["2", "3"]
    attach_json("reasons", reasons)
    assert reasons == {
        "restore": "restore",
        "feed": "feed_changed",
        "access": "feed_changed",
        "owner": "feed_changed",
        "pruned": "cursor_expired",
    }


def test_026_FR_010_redacted_or_expired_content_is_never_served_partially(
    client, owner, gateway
):
    start = cursor_at(gateway, owner)
    publish(gateway, owner, "one", [upsert(1)])
    publish(gateway, owner, "two", [upsert(2)])
    conn = sqlite3.connect(gateway.units._repo.db_path)
    with allure.step("an upsert whose value was redacted resets the whole read"):
        with conn:
            conn.execute(
                "UPDATE sync_change_records SET value = NULL WHERE commit_seq='2'"
            )
        response = pull(client, owner, start)
        assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")
        assert response.json()["error"]["details"]["reset_reason"] == "content_expired"
        assert "transactions" not in response.json()
    with allure.step("content past its source expiry resets instead of leaking"):
        with conn:
            conn.execute(
                "UPDATE sync_change_records SET source_expires_at = ? "
                "WHERE commit_seq='1'",
                ((gateway.clock() - timedelta(days=1)).isoformat(),),
            )
        response = pull(client, owner, start)
        assert response.json()["error"]["details"]["reset_reason"] == "content_expired"
    conn.close()


def test_026_FR_011_transfers_are_owner_scoped_and_tokens_are_bound(
    client, owner, gateway
):
    start = cursor_at(gateway, owner)
    oversized(gateway, owner)
    manifest = pull(client, owner, start).json()["transaction_manifest"]
    url = f"/api/sync/v1/transactions/{manifest['transfer_id']}"
    token = manifest["first_page_token"]
    with allure.step("another account reads the transfer as an unknown ID"):
        container = client.app.state.container
        from app.schemas.auth import Invite
        from app.utils.time import utcnow

        container.invite_repo.create(Invite(code="invite_other", created_at=utcnow()))
        other = TestClient(client.app)
        signed = other.post(
            "/api/auth/signup",
            json={
                "email": "other-delta@example.com",
                "password": "correct horse battery staple 42",
                "invite_code": "invite_other",
            },
        )
        assert signed.status_code == 201, signed.text
        flags = container.feature_flag_service
        flags.set_mode(FLAG, "on", operator_id="sync-delta")
        foreign = other.get(url, params={"page_token": token})
        unknown = other.get(
            "/api/sync/v1/transactions/no-such-transfer", params={"page_token": token}
        )
        assert (foreign.status_code, error_code(foreign)) == (404, "RESOURCE_NOT_FOUND")
        assert (unknown.status_code, error_code(unknown)) == (404, "RESOURCE_NOT_FOUND")
        check_equal(
            "same message",
            foreign.json()["error"]["message"],
            unknown.json()["error"]["message"],
        )
        assert manifest["transfer_id"] not in foreign.text
    with allure.step("a cursor of another account resets without reading the feed"):
        theirs = other.get("/api/auth/me").json()["id"]
        response = pull(other, theirs, start)
        assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")
        assert "transactions" not in response.json()
    with allure.step("malformed, foreign-transfer and out-of-range tokens are refused"):
        forged = base64.urlsafe_b64encode(
            json.dumps({"v": 1, "t": "other", "i": 0}).encode()
        ).decode()
        far = transfers.page_token(manifest["transfer_id"], 99)
        for bad in ("!!", forged, far):
            response = client.get(url, params={"page_token": bad})
            attach_json("status", response.status_code)
            assert (response.status_code, error_code(response)) == (
                422,
                "INVALID_REQUEST",
            )
    with allure.step("a disabled scope cannot read transfer bytes"):
        flags.set_mode(FLAG, "off", operator_id="sync-delta")
        response = client.get(url, params={"page_token": token})
        assert (response.status_code, error_code(response)) == (403, "ACCESS_DENIED")


def test_026_FR_004_real_writer_changes_are_public_projections(client, owner, gateway):
    start = cursor_at(gateway, owner)
    with allure.step("a task created through REST reaches the feed as its public form"):
        created = client.post(
            "/api/tasks",
            json={"title": "Buy milk"},
            headers={"Idempotency-Key": "delta-test-key-0001"},
        )
        assert created.status_code == 201, created.text
        page = pull(client, owner, start).json()
        (transaction,) = page["transactions"]
        task = next(c for c in transaction["changes"] if c["entity_type"] == "task")
        attach_json("change", task)
        assert task["operation"] == "upsert"
        assert task["value"]["title"] == "Buy milk"
        assert task["value"]["id"] == created.json()["id"]
        assert task["record_version"] == "1"
    with allure.step("no storage-only or private member leaves the server"):
        text = json.dumps(page)
        present = [
            name
            for name in ("owner_id", "applied_progress", "clock_before", "task_before")
            if f'"{name}"' in text
        ]
        check_equal("private members present", present, [])
        assert owner not in text.replace(page["scope_id"], "")


def test_026_FR_011_account_purge_removes_the_feed_and_transfers(
    client, owner, gateway
):
    from app.modules.tasks.sync.change_log import purge_owner

    start = cursor_at(gateway, owner)
    oversized(gateway, owner)
    pull(client, owner, start)
    with allure.step("transfer metadata and pages exist before the purge"):
        assert sql(gateway, "SELECT 1 FROM sync_transfer_pages")
    with allure.step("purge_owner removes every sync table row of the scope"):
        conn = sqlite3.connect(gateway.units._repo.db_path)
        with conn:
            purge_owner(conn, owner)
        conn.close()
        left = {
            table: len(sql(gateway, f"SELECT 1 FROM {table}"))  # noqa: S608
            for table in (
                "sync_transfers",
                "sync_transfer_pages",
                "sync_change_records",
            )
        }
        check_equal("rows left", left, dict.fromkeys(left, 0))


def test_026_FR_008_canonical_json_matches_the_rust_rfc8785_core():
    with allure.step("the published UTF-16 ordering and number vector agrees"):
        wire = (
            '{"דּ":7,"😀":6,"€":5,"ö":4,"\\u0080":3,"1":2,"\\r":1,'
            '"numbers":[-0.0,1e30,4.50,2e-3,1e21,1e-7,123456789012345680000,0.000001,1.5e300,3e2,true,false,null]}'
        )
        with RustCore() as core:
            expected = core.persistence("canonical", wire.encode()).decode()
        actual = transfers.canonical_json(json.loads(wire))
        check_equal("canonical", actual, expected)
    with allure.step("control characters and quotes escape like the core"):
        text = {"k": 'a"b\\c\n\t\x01\x1f\x7f é'}
        with RustCore() as core:
            expected = core.persistence("canonical", json.dumps(text).encode()).decode()
        check_equal("escapes", transfers.canonical_json(text), expected)
    with allure.step("non-JSON values and non-finite numbers are refused"):
        for bad in (float("nan"), object()):
            with pytest.raises((ValueError, TypeError)):
                transfers.canonical_json([bad])


def test_026_FR_008_an_empty_or_exact_multiple_stream_still_has_pages():
    with allure.step("chunking is exact at the boundary and never empty"):
        assert transfers.chunks(b"", 4) == [b""]
        assert transfers.chunks(b"abcdefgh", 4) == [b"abcd", b"efgh"]
        check_equal("remainder", transfers.chunks(b"abcdefghi", 4)[-1], b"i")
        assert transfers.change_stream([]) == b"[]"


def test_026_FR_004_cursors_are_opaque_and_bound_to_the_scope_generations():
    current = ScopeAuthority("owner-1", "server", "feed-1", "access-1", "epoch")
    with allure.step("a cursor round-trips its binding and is not plain JSON"):
        token = delta.encode_cursor(current, "42")
        decoded = delta.decode_cursor(token)
        check_equal(
            "binding",
            (
                decoded.owner_id,
                decoded.access_generation,
                decoded.feed_generation,
                decoded.commit_seq,
            ),
            ("owner-1", "access-1", "feed-1", "42"),
        )
        assert "{" not in token
    with allure.step("a counter that is not canonical decimal is malformed"):
        for seq in ("-1", "007", "1.5", ""):
            forged = delta.encode_cursor(current, seq)
            with pytest.raises(Exception, match="INVALID_REQUEST"):
                delta.decode_cursor(forged)
        attach_json("rejected counters", ["-1", "007", "1.5", ""])


def test_026_FR_010_a_window_pruned_to_nothing_resets_instead_of_an_empty_page(
    client, owner, gateway
):
    start = cursor_at(gateway, owner)
    for n in range(3):
        publish(gateway, owner, f"cmd-{n}", [upsert(n)])
    with allure.step("every retained transaction ages out of the window"):
        conn = sqlite3.connect(gateway.units._repo.db_path)
        with conn:
            conn.execute("DELETE FROM sync_change_transactions")
        conn.close()
    with allure.step("the scope is ahead of the feed, so the read is a reset"):
        response = pull(client, owner, start)
        attach_json("status", response.status_code)
        assert (response.status_code, error_code(response)) == (409, "RESET_REQUIRED")
        details = response.json()["error"]["details"]
        check_equal("reason", details["reset_reason"], "cursor_expired")
