"""026-FR-003/011/022/023 and SC-005/SC-007: account export and purge of sync state.

The existing GDPR export gains the owner's sync scope and device epochs only;
receipts, fingerprints, key digests, change images, transfers, snapshots and
job/lease state stay protected. The existing deletion authority erases every
owner-keyed sync row, and nothing about another owner.
"""

from __future__ import annotations

import io
import json
import logging
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import allure
import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.modules.tasks.jobs import JobRepository
from app.modules.tasks.sync.change_log import SYNC_TABLES
from tests.allure_evidence import attach_json

from .test_account_deletion import (
    _backdate_deletion,
    _container,
    _request_deletion,
    _user_id,
)
from .test_sync_commands_api import set_flag

SECRETS = {
    "fingerprint": "FINGERPRINT-SECRET-A",
    "key_digest": "KEY-DIGEST-SECRET-A",
    "receipt_result": "RECEIPT-TEXT-SECRET-A",
    "change_value": "CHANGE-TEXT-SECRET-A",
    "transfer": b"TRANSFER-PAYLOAD-SECRET-A",
    "snapshot": b"SNAPSHOT-PAYLOAD-SECRET-A",
    "lease": "LEASE-OWNER-SECRET-A",
    "payload_ref": "PAYLOAD-REF-SECRET-A",
}

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Sync export and purge"),
    allure.story("Account export and purge cover sync records safely"),
]


def _register(client: TestClient, owner: str, device: str) -> None:
    response = client.post(
        "/api/sync/v1/devices",
        json={
            "scope_id": owner,
            "device_id": device,
            "device_epoch": "epoch-1",
            "protocol_version": 1,
        },
    )
    assert response.status_code == 200, response.text


def _db(client: TestClient) -> Path:
    return _container(client).task_repo.db_path


def _seed(client: TestClient, owner: str, tag: str) -> None:
    """Rows in every owner-keyed sync table, with recognisable protected text."""
    JobRepository(_db(client))  # creates the jobs table
    with closing(sqlite3.connect(_db(client))) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO sync_command_receipts VALUES (?,?,?,?,?,?,?,?)",
            (
                owner,
                f"cmd-{tag}",
                "api",
                f"{SECRETS['fingerprint']}-{tag}",
                "{}",
                f"{SECRETS['receipt_result']}-{tag}",
                "2026-10-01T00:00:00Z",
                "2026-10-02T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO sync_legacy_keys VALUES (?,?,?)",
            (owner, f"{SECRETS['key_digest']}-{tag}", f"cmd-{tag}"),
        )
        conn.execute(
            "INSERT INTO sync_record_versions VALUES (?,?,?,?,0)",
            (owner, "task", f"task-{tag}", "1"),
        )
        conn.execute(
            "INSERT INTO sync_change_transactions VALUES (?,?,?,?,?)",
            (owner, "900", f"tx-{tag}", f"cmd-{tag}", "2026-10-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO sync_change_records VALUES (?,?,?,?,?,?,?,?,?)",
            (
                owner,
                "900",
                "task",
                f"task-{tag}",
                "1",
                "1",
                "upsert",
                f"{SECRETS['change_value']}-{tag}",
                None,
            ),
        )
        conn.execute(
            "INSERT INTO sync_transfers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                owner,
                f"tr-{tag}",
                "900",
                f"tx-{tag}",
                f"cmd-{tag}",
                "f",
                "a",
                1,
                1,
                1,
                "sha",
                "2026-10-01T00:00:00Z",
                "2026-10-01T00:30:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO sync_transfer_pages VALUES (?,?,?,?,?)",
            (owner, f"tr-{tag}", 0, SECRETS["transfer"] + tag.encode(), "sha"),
        )
        conn.execute(
            "INSERT INTO sync_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                owner,
                f"sn-{tag}",
                "900",
                "f",
                "a",
                1,
                1,
                1,
                "sha",
                "2026-10-01T00:00:00Z",
                "2026-10-01T00:30:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO sync_snapshot_pages VALUES (?,?,?,?,?)",
            (owner, f"sn-{tag}", 0, SECRETS["snapshot"] + tag.encode(), "sha"),
        )
        conn.execute(
            "INSERT INTO jobs (id, scope, job_type, dedup_key, payload_ref, run_at, "
            "status, max_attempts, lease_owner, effect_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"job-{tag}",
                owner,
                "ai.proposal",
                f"dedup-{tag}",
                f"{SECRETS['payload_ref']}-{tag}",
                0,
                "leased",
                3,
                f"{SECRETS['lease']}-{tag}",
                f"eff-{tag}",
                0,
                0,
            ),
        )


def _counts(client: TestClient, owner: str) -> dict[str, int]:
    with closing(sqlite3.connect(_db(client))) as conn:
        out = {
            table: conn.execute(
                f"SELECT count(*) FROM {table} WHERE owner_id = ?",  # noqa: S608
                (owner,),
            ).fetchone()[0]
            for table in SYNC_TABLES
        }
        out["jobs"] = conn.execute(
            "SELECT count(*) FROM jobs WHERE scope = ?", (owner,)
        ).fetchone()[0]
    return out


@pytest.fixture()
def two_owners(second_api_client):
    client_a, client_b = second_api_client
    set_flag(client_a, True)
    owner_a, owner_b = _user_id(client_a), _user_id(client_b)
    _register(client_a, owner_a, "device-a")
    _register(client_b, owner_b, "device-b")
    _seed(client_a, owner_a, "A")
    _seed(client_b, owner_b, "B")
    return client_a, client_b, owner_a, owner_b


def _export(client: TestClient) -> zipfile.ZipFile:
    response = client.get("/api/account/export")
    assert response.status_code == 200, response.text
    return zipfile.ZipFile(io.BytesIO(response.content))


def test_026_FR_003_export_adds_scope_and_devices_for_this_owner_only(two_owners):
    client_a, _, owner_a, owner_b = two_owners
    with allure.step("download the owner's export"):
        archive = _export(client_a)
        names = set(archive.namelist())
        attach_json("members", sorted(names))
    with allure.step("sync scope and device epochs are present and owner-bound"):
        assert {"sync/scope.json", "sync/devices.json"} <= names
        devices = json.loads(archive.read("sync/devices.json"))
        scope = json.loads(archive.read("sync/scope.json"))
        attach_json("devices", devices)
        assert [d["device_id"] for d in devices] == ["device-a"]
        assert devices[0]["status"] == "active"
        assert len(scope) == 1
        manifest = json.loads(archive.read("export_manifest.json"))
        assert manifest["counts"]["sync_device_epochs"] == 1
    with allure.step("no other owner's data appears anywhere in the archive"):
        attach_json("members checked", sorted(names))
        for name in names:
            text = archive.read(name)
            assert owner_b.encode() not in text, name
            assert b"device-b" not in text, name


def test_026_FR_023_export_has_no_protected_text_fingerprints_or_media(two_owners):
    client_a, _, _, _ = two_owners
    archive = _export(client_a)
    with allure.step("no protected sync value is in any member"):
        attach_json("secret categories checked", sorted(SECRETS))
        blob = b"".join(archive.read(name) for name in archive.namelist())
        for key, secret in SECRETS.items():
            needle = secret if isinstance(secret, bytes) else secret.encode()
            assert needle not in blob, key
    with allure.step("the manifest names the excluded protected categories"):
        manifest = json.loads(archive.read("export_manifest.json"))
        attach_json("excluded", manifest["excluded"])
        assert any("sync command receipts" in item for item in manifest["excluded"])


def test_026_FR_011_logs_carry_no_sync_content_during_export_and_purge(
    two_owners, caplog
):
    client_a, _, owner_a, _ = two_owners
    with caplog.at_level(logging.DEBUG):
        _export(client_a)
        _request_deletion(client_a)
        _backdate_deletion(client_a, owner_a, days=15)
        assert _container(client_a).account_service.purge_due_accounts() == 1
    with allure.step("log text holds no payload, fingerprint, digest or lease text"):
        text = "\n".join(record.getMessage() for record in caplog.records)
        attach_json("log lines checked", len(caplog.records))
        for key, secret in SECRETS.items():
            if isinstance(secret, str):
                assert secret not in text, key


def test_026_FR_022_purge_erases_every_sync_table_for_the_owner_only(two_owners):
    client_a, client_b, owner_a, owner_b = two_owners
    container: Container = _container(client_a)
    with allure.step("both owners have rows in every sync table before the purge"):
        before_a, before_b = _counts(client_a, owner_a), _counts(client_a, owner_b)
        attach_json("before", {"a": before_a, "b": before_b})
        assert all(count >= 1 for count in before_a.values()), before_a
        assert all(count >= 1 for count in before_b.values()), before_b
    _request_deletion(client_a)
    _backdate_deletion(client_a, owner_a, days=15)
    with allure.step("the existing deletion authority purges the owner"):
        assert container.account_service.purge_due_accounts() == 1
    with allure.step("every sync table and job is empty for the purged owner"):
        after_a = _counts(client_a, owner_a)
        attach_json("after", after_a)
        assert set(after_a.values()) == {0}, after_a
    with allure.step("the other owner's rows are untouched"):
        attach_json("other owner", _counts(client_a, owner_b))
        assert _counts(client_a, owner_b) == before_b
        archive = _export(client_b)
        assert [
            d["device_id"] for d in json.loads(archive.read("sync/devices.json"))
        ] == ["device-b"]


def test_026_SC_007_no_owner_keyed_table_keeps_a_purged_owner_row(two_owners):
    """A future sync table with an owner column cannot silently escape the purge."""
    client_a, _, owner_a, _ = two_owners
    _request_deletion(client_a)
    _backdate_deletion(client_a, owner_a, days=15)
    assert _container(client_a).account_service.purge_due_accounts() == 1
    with closing(sqlite3.connect(_db(client_a))) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'sync_%'"
            )
        ]
        leftovers = {}
        for table in tables:
            columns = [
                r[1] for r in conn.execute(f"PRAGMA table_info({table})")
            ]  # noqa: S608
            if "owner_id" in columns:
                leftovers[table] = conn.execute(
                    f"SELECT count(*) FROM {table} WHERE owner_id = ?",  # noqa: S608
                    (owner_a,),
                ).fetchone()[0]
        attach_json("leftovers", leftovers)
        assert leftovers and set(leftovers.values()) == {0}, leftovers
