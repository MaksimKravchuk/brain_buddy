"""Tests for /api/brain-dump endpoints — voice-only brain dump to RTM Inbox."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_session_requires_auth(anonymous_api_client: TestClient) -> None:
    resp = anonymous_api_client.post("/api/brain-dump/sessions")
    assert resp.status_code == 401


def test_create_session_returns_active_or_new(api_client: TestClient) -> None:
    resp = api_client.post("/api/brain-dump/sessions")
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] is not None
    assert body["status"] == "recording"
    assert body["drafts"] == []


def test_get_session_returns_drafts(api_client: TestClient) -> None:
    create = api_client.post("/api/brain-dump/sessions")
    session_id = create.json()["id"]

    resp = api_client.get(f"/api/brain-dump/sessions/{session_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == session_id
    assert body["drafts"] == []


def test_get_session_wrong_owner_404(second_api_client) -> None:
    client_a, client_b = second_api_client
    create = client_a.post("/api/brain-dump/sessions")
    session_id = create.json()["id"]

    resp = client_b.get(f"/api/brain-dump/sessions/{session_id}")
    assert resp.status_code == 404


def test_upload_audio_appends_drafts(api_client: TestClient) -> None:
    create = api_client.post("/api/brain-dump/sessions")
    session_id = create.json()["id"]

    # Upload fake audio (mock transcription provider returns task drafts).
    resp = api_client.post(
        f"/api/brain-dump/sessions/{session_id}/audio",
        files={"file": ("audio.webm", b"\x00\x01" * 100, "audio/webm")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["drafts"]) > 0
    assert all(d["text"] for d in body["drafts"])
    assert body["status"] == "reviewing"


def test_edit_draft_text(api_client: TestClient) -> None:
    create = api_client.post("/api/brain-dump/sessions")
    session_id = create.json()["id"]

    upload = api_client.post(
        f"/api/brain-dump/sessions/{session_id}/audio",
        files={"file": ("audio.webm", b"\x00\x01" * 100, "audio/webm")},
    )
    draft_id = upload.json()["drafts"][0]["id"]

    resp = api_client.patch(
        f"/api/brain-dump/sessions/{session_id}/drafts/{draft_id}",
        json={"text": "Edited task text"},
    )
    assert resp.status_code == 200
    body = resp.json()
    edited = [d for d in body["drafts"] if d["id"] == draft_id]
    assert len(edited) == 1
    assert edited[0]["text"] == "Edited task text"


def test_edit_nonexistent_draft_404(api_client: TestClient) -> None:
    create = api_client.post("/api/brain-dump/sessions")
    session_id = create.json()["id"]

    resp = api_client.patch(
        f"/api/brain-dump/sessions/{session_id}/drafts/nonexistent",
        json={"text": "text"},
    )
    assert resp.status_code == 404


def test_delete_draft(api_client: TestClient) -> None:
    create = api_client.post("/api/brain-dump/sessions")
    session_id = create.json()["id"]

    upload = api_client.post(
        f"/api/brain-dump/sessions/{session_id}/audio",
        files={"file": ("audio.webm", b"\x00\x01" * 100, "audio/webm")},
    )
    draft_id = upload.json()["drafts"][0]["id"]

    resp = api_client.delete(f"/api/brain-dump/sessions/{session_id}/drafts/{draft_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert all(d["id"] != draft_id for d in body["drafts"])


def test_save_session_exports_to_rtm_inbox(api_client: TestClient) -> None:
    create = api_client.post("/api/brain-dump/sessions")
    session_id = create.json()["id"]

    upload = api_client.post(
        f"/api/brain-dump/sessions/{session_id}/audio",
        files={"file": ("audio.webm", b"\x00\x01" * 100, "audio/webm")},
    )
    drafts_before = upload.json()["drafts"]
    assert len(drafts_before) > 0

    resp = api_client.post(f"/api/brain-dump/sessions/{session_id}/save")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert len(body["export_results"]) == len(drafts_before)
    for result in body["export_results"]:
        assert result["success"] is True
        assert result["external_ref"] is not None


def test_save_empty_session_succeeds_with_no_exports(api_client: TestClient) -> None:
    create = api_client.post("/api/brain-dump/sessions")
    session_id = create.json()["id"]

    resp = api_client.post(f"/api/brain-dump/sessions/{session_id}/save")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["export_results"] == []


def test_save_already_completed_session_409(api_client: TestClient) -> None:
    create = api_client.post("/api/brain-dump/sessions")
    session_id = create.json()["id"]

    api_client.post(f"/api/brain-dump/sessions/{session_id}/save")
    resp = api_client.post(f"/api/brain-dump/sessions/{session_id}/save")
    assert resp.status_code == 409


def test_add_more_voice_after_review(api_client: TestClient) -> None:
    create = api_client.post("/api/brain-dump/sessions")
    session_id = create.json()["id"]

    upload1 = api_client.post(
        f"/api/brain-dump/sessions/{session_id}/audio",
        files={"file": ("audio.webm", b"\x00\x01" * 100, "audio/webm")},
    )
    first_drafts = upload1.json()["drafts"]
    assert len(first_drafts) > 0

    # Add more voice — should append to existing drafts.
    upload2 = api_client.post(
        f"/api/brain-dump/sessions/{session_id}/audio",
        files={"file": ("audio.webm", b"\x02\x03" * 100, "audio/webm")},
    )
    assert upload2.status_code == 200
    all_drafts = upload2.json()["drafts"]
    assert len(all_drafts) > len(first_drafts)
    # Original drafts should still be present.
    first_ids = {d["id"] for d in first_drafts}
    for fd in first_ids:
        assert any(d["id"] == fd for d in all_drafts)


def test_resume_session_returns_existing_active(api_client: TestClient) -> None:
    create = api_client.post("/api/brain-dump/sessions")
    session_id = create.json()["id"]

    # Creating again should resume the same active session.
    create2 = api_client.post("/api/brain-dump/sessions")
    assert create2.json()["id"] == session_id


def test_no_text_capture_endpoint_exists(api_client: TestClient) -> None:
    """Voice is the only capture input — no text-to-draft endpoint."""
    resp = api_client.post(
        "/api/brain-dump/sessions/some-id/drafts",
        json={"text": "typed text"},
    )
    assert resp.status_code == 404
