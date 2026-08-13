"""Tests for the GDPR account data export archive."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.container import Container
from app.modules.agents.domain import (
    AgentAuditEntryDocument,
    AgentConnectionDocument,
    AgentIdempotencyRecord,
    AgentReportingContract,
    AgentRunCommandDocument,
    AgentRunDocument,
    AgentRunEventDocument,
    AgentRunManifest,
)
from app.modules.agents.secrets import SealedSecret
from app.schemas.domain import ValidationEntry
from app.utils.time import utcnow

from .test_brain_dump_operations_api import _start_operation, _upload_and_seal


def _container(client: TestClient) -> Container:
    return client.app.state.container  # type: ignore[attr-defined]


def _seed_account(client: TestClient, *, marker: str, key_prefix: str) -> str:
    """Create one tree (with node, version, validation history) and a task."""

    tree = client.post("/api/trees", json={"name": f"{marker} tree"})
    assert tree.status_code == 201, tree.text
    tree_id = tree.json()["id"]

    node = client.post(
        f"/api/trees/{tree_id}/nodes",
        json={"label": f"{marker} node", "type": "child", "position": {"x": 0, "y": 0}},
    )
    assert node.status_code == 201, node.text
    node_id = node.json()["id"]

    version = client.post(
        f"/api/trees/{tree_id}/versions",
        json={"label": f"{marker} snapshot", "author": marker},
    )
    assert version.status_code == 201, version.text

    _container(client).validation_repo.append_entry(
        tree_id,
        node_id,
        ValidationEntry(
            confidence=80,
            summary=f"{marker} validation summary",
            provider="mock",
            prompt_hash="a" * 64,
            checked_at=utcnow(),
        ),
    )

    task = client.post(
        "/api/tasks",
        headers={"Idempotency-Key": f"{key_prefix}-task"},
        json={"title": f"{marker} task"},
    )
    assert task.status_code == 201, task.text
    return tree_id


def _download_zip(client: TestClient) -> zipfile.ZipFile:
    resp = client.get("/api/account/export")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    assert "brain-buddy-export-" in resp.headers["content-disposition"]
    return zipfile.ZipFile(io.BytesIO(resp.content))


def _seed_relay_export_data(
    client: TestClient, *, marker: str, content_expires_at: datetime | None = None
) -> str:
    owner_id = client.get("/api/account").json()["id"]
    repo = _container(client).agent_repo
    now = datetime(2026, 8, 11, tzinfo=UTC)
    connection_id = f"agentconn_{marker}"
    run_id = f"agentrun_{marker}"
    repo.create_connection(
        AgentConnectionDocument(
            id=connection_id,
            owner_id=owner_id,
            name=f"{marker} Relay",
            endpoint_url="https://agent.example.com/hooks",
            credential=SealedSecret(
                key_id="k1", ciphertext=f"{marker}-credential-secret"
            ),
            inbound_secret=SealedSecret(
                key_id="k1", ciphertext=f"{marker}-signing-secret"
            ),
            status="ready",
            scope_verified_at=now,
            revision=1,
            created_at=now,
            updated_at=now,
        )
    )
    repo.create_run(
        AgentRunDocument(
            id=run_id,
            owner_id=owner_id,
            task_id=f"task_{marker}",
            connection_id=connection_id,
            agent_name=f"{marker} Relay",
            manifest=AgentRunManifest(
                token="a" * 64,
                run_id=run_id,
                task_id=f"task_{marker}",
                connection_id=connection_id,
                agent_name=f"{marker} Relay",
                title=f"{marker}-manifest-title",
                details=f"{marker}-manifest-details",
                reporting=AgentReportingContract(
                    callback_url="https://brainbuddy.example/api/agent-events",
                    connection_id=connection_id,
                ),
                reporting_instructions=f"{marker}-reporting-instructions",
            ),
            progress_text=f"{marker}-run-progress",
            question_text=f"{marker}-run-question",
            result_text=f"{marker}-run-result",
            result_link=f"https://agent.example.com/{marker}-result",
            failure_reason=f"{marker}-run-failure",
            content_expires_at=content_expires_at or now + timedelta(days=30),
            dispatched_at=now,
            revision=1,
            created_at=now,
            updated_at=now,
        )
    )
    repo.append_event(
        AgentRunEventDocument(
            id=f"evt_{marker}",
            owner_id=owner_id,
            run_id=run_id,
            connection_id=connection_id,
            type="running",
            run_version=1,
            summary=f"{marker}-event-secret",
            received_at=now,
        )
    )
    repo.save_command(
        AgentRunCommandDocument(
            id=f"cmd_{marker}",
            owner_id=owner_id,
            run_id=run_id,
            kind="reply",
            body=f"{marker}-command-secret",
            created_at=now,
        )
    )
    repo.append_audit(
        AgentAuditEntryDocument(
            id=f"audit_{marker}",
            owner_id=owner_id,
            action="run_dispatched",
            outcome="ok",
            connection_id=connection_id,
            run_id=run_id,
            created_at=now,
        )
    )
    repo.save_idempotency(
        owner_id=owner_id,
        record=AgentIdempotencyRecord(
            key_hash=f"{marker}-idempotency-receipt",
            command="dispatch",
            request_hash=f"{marker}-request-receipt",
            resource_id=run_id,
            command_id=None,
            delivery_attempted=True,
            completed=True,
            response_body={"secret": f"{marker}-response-receipt"},
            created_at=now,
        ),
    )
    return connection_id


def test_export_contains_every_store_and_no_secrets(api_client: TestClient) -> None:
    """The archive covers account, trees, tasks, and voice — minus secrets."""

    tree_id = _seed_account(api_client, marker="Primary", key_prefix="export")
    operation = _start_operation(api_client, key="export-voice")
    _upload_and_seal(api_client, operation, b"Pay VAT. Send invoice.", "export-seal")

    archive = _download_zip(api_client)
    names = set(archive.namelist())

    account = json.loads(archive.read("account.json"))
    assert account["email"] == "primary@example.com"
    assert "password_hash" not in account

    manifest = json.loads(archive.read("export_manifest.json"))
    assert manifest["format"] == "brain-buddy-account-export/v1"
    assert manifest["counts"]["trees"] == 1
    assert manifest["counts"]["voice_audio_chunks"] >= 1

    tree = json.loads(archive.read(f"trees/{tree_id}/tree.json"))
    assert tree["title"] == "Primary tree"
    assert any(name.startswith(f"trees/{tree_id}/versions/") for name in names)
    validation_files = [
        name for name in names if name.startswith(f"trees/{tree_id}/validation/")
    ]
    assert validation_files
    history = json.loads(archive.read(validation_files[0]))
    assert history[0]["summary"] == "Primary validation summary"

    tasks = json.loads(archive.read("tasks/tasks.json"))
    assert [task["title"] for task in tasks] == ["Primary task"]

    operations = json.loads(archive.read("voice/operations.json"))
    assert len(operations) == 1
    audio_files = [name for name in names if name.startswith("voice/audio/")]
    assert audio_files
    assert archive.read(audio_files[0])  # non-empty raw bytes


def test_export_omits_audio_once_raw_audio_is_deleted(api_client: TestClient) -> None:
    """Erased raw audio must not resurface in a later export."""

    operation = _start_operation(api_client, key="export-erase-voice")
    _upload_and_seal(api_client, operation, b"Draft the memo.", "export-erase-seal")
    op_id = operation["id"]

    revision = api_client.get(f"/api/brain-dump-operations/{op_id}").json()["revision"]
    deleted = api_client.post(
        f"/api/brain-dump-operations/{op_id}/delete_raw_audio",
        headers={"Idempotency-Key": "export-erase-delete"},
        json={"expected_revision": revision},
    )
    assert deleted.status_code == 200, deleted.text

    archive = _download_zip(api_client)
    audio_files = [
        name for name in archive.namelist() if name.startswith("voice/audio/")
    ]
    assert audio_files == []
    manifest = json.loads(archive.read("export_manifest.json"))
    assert manifest["counts"]["voice_audio_chunks"] == 0


def test_export_is_scoped_to_the_caller(second_api_client) -> None:
    """One user's export never contains another user's content."""

    client_a, client_b = second_api_client
    _seed_account(client_a, marker="Alice", key_prefix="export-a")
    _seed_account(client_b, marker="Bob", key_prefix="export-b")

    archive_b = _download_zip(client_b)
    everything = " ".join(
        archive_b.read(name).decode("utf-8", errors="ignore")
        for name in archive_b.namelist()
    )
    assert "Alice" not in everything
    assert "primary@example.com" not in everything
    assert "Bob task" in everything


def test_export_contains_owner_scoped_portable_relay_data(second_api_client) -> None:
    """Unexpired owner relay content is portable while secrets stay excluded."""

    client_a, client_b = second_api_client
    _seed_relay_export_data(client_a, marker="alice")
    bob_connection_id = _seed_relay_export_data(client_b, marker="bob")

    archive = _download_zip(client_b)
    relay = json.loads(archive.read("relay/relay.json"))
    assert [connection["id"] for connection in relay["connections"]] == [
        bob_connection_id
    ]
    assert relay["connections"][0]["name"] == "bob Relay"
    run = relay["runs"][0]
    assert run["manifest"]["title"] == "bob-manifest-title"
    assert run["manifest"]["details"] == "bob-manifest-details"
    assert run["manifest"]["reporting_instructions"] == ("bob-reporting-instructions")
    assert run["progress_text"] == "bob-run-progress"
    assert run["question_text"] == "bob-run-question"
    assert run["result_text"] == "bob-run-result"
    assert run["result_link"] == "https://agent.example.com/bob-result"
    assert run["failure_reason"] == "bob-run-failure"
    assert relay["events"][0]["summary"] == "bob-event-secret"
    assert relay["commands"][0]["body"] == "bob-command-secret"

    manifest = json.loads(archive.read("export_manifest.json"))
    assert (
        manifest["counts"]
        | {
            "relay_connections": 1,
            "relay_runs": 1,
            "relay_events": 1,
            "relay_commands": 1,
            "relay_audit_entries": 1,
        }
        == manifest["counts"]
    )
    assert manifest["excluded"][-3:] == [
        "relay credentials, inbound signing secrets, and sealed secret boxes",
        "relay idempotency keys and raw request/response receipts",
        "relay content already expired or redacted under the retention policy",
    ]

    serialized = json.dumps(relay, sort_keys=True)
    for forbidden in (
        "alice",
        "bob-credential-secret",
        "bob-signing-secret",
        "bob-idempotency-receipt",
        "bob-request-receipt",
        "bob-response-receipt",
    ):
        assert forbidden not in serialized


def test_export_uses_generated_at_to_redact_due_unswept_relay_content(
    api_client: TestClient, monkeypatch
) -> None:
    """The account export applies one authoritative boundary without a sweep."""

    from app.services import account_service as account_service_module

    exported_at = datetime(2026, 8, 12, 9, 30, tzinfo=UTC)
    monkeypatch.setattr(account_service_module, "utcnow", lambda: exported_at)
    _seed_relay_export_data(
        api_client, marker="boundary", content_expires_at=exported_at
    )

    archive = _download_zip(api_client)
    relay = json.loads(archive.read("relay/relay.json"))
    manifest = json.loads(archive.read("export_manifest.json"))

    assert manifest["generated_at"] == exported_at.isoformat()
    assert datetime.fromisoformat(relay["runs"][0]["content_expires_at"]) == exported_at
    assert relay["runs"][0]["content_expired"] is True
    assert relay["runs"][0]["manifest"] is None
    assert relay["events"][0]["summary"] is None
    assert relay["commands"][0]["body"] is None

    stored = _container(api_client).agent_repo.get_run(
        "agentrun_boundary",
        owner_id=api_client.get("/api/account").json()["id"],
    )
    assert stored.content_expired is False
    assert stored.result_text == "boundary-run-result"


def test_export_requires_auth(anonymous_api_client: TestClient) -> None:
    """Anonymous callers get the standard 401 envelope."""

    assert anonymous_api_client.get("/api/account/export").status_code == 401
