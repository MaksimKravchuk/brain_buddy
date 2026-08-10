"""Tests for the GDPR account data export archive."""

from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.container import Container
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


def test_export_requires_auth(anonymous_api_client: TestClient) -> None:
    """Anonymous callers get the standard 401 envelope."""

    assert anonymous_api_client.get("/api/account/export").status_code == 401
