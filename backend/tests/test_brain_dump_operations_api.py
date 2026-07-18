"""API tests for native voice Brain Dump operations."""

from __future__ import annotations


def _start_operation(api_client, key: str = "start-brain-dump"):
    response = api_client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": key},
        json={"consent": {"microphone": True, "external_processing_allowed": False}},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_brain_dump_operation_collects_provisional_tasks_without_inbox_writes(api_client) -> None:
    operation = _start_operation(api_client)
    assert operation["status"] == "recording"
    assert operation["kind"] == "voice_brain_dump"
    assert operation["proposals"] == []

    empty_inbox = api_client.get("/api/tasks", params={"state": "inbox"})
    assert empty_inbox.status_code == 200
    assert empty_inbox.json()["counts_by_state"]["inbox"] == 0

    append = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-initial-segment"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "Renew car insurance. Reply to Anna about the offsite.",
                    "stability": "stable",
                }
            ]
        },
    )
    assert append.status_code == 200, append.text
    body = append.json()
    assert body["status"] == "recording"
    assert [proposal["title"] for proposal in body["proposals"]] == [
        "Renew car insurance",
        "Reply to Anna about the offsite",
    ]
    assert [proposal["ordinal"] for proposal in body["proposals"]] == [1, 2]
    assert {proposal["status"] for proposal in body["proposals"]} == {"provisional"}

    still_empty = api_client.get("/api/tasks", params={"state": "inbox"})
    assert still_empty.json()["counts_by_state"]["inbox"] == 0


def test_brain_dump_cumulative_final_replaces_interim_words(api_client) -> None:
    operation = _start_operation(api_client, key="start-cumulative-final-operation")

    interim = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-cumulative-interim"},
        json={
            "segments": [
                {"sequence": 1, "text": "buy oat milk", "stability": "interim"}
            ]
        },
    )
    assert interim.status_code == 200, interim.text
    assert [proposal["title"] for proposal in interim.json()["proposals"]] == [
        "Buy oat milk"
    ]
    assert interim.json()["proposals"][0]["status"] == "wording_changing"

    final = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-cumulative-final"},
        json={
            "segments": [
                {
                    "sequence": 2,
                    "text": "buy oat milk. call dentist",
                    "stability": "stable",
                }
            ]
        },
    )
    assert final.status_code == 200, final.text
    assert [proposal["title"] for proposal in final.json()["proposals"]] == [
        "Buy oat milk",
        "Call dentist",
    ]
    assert "Buy oat milk buy oat milk" not in {
        proposal["title"] for proposal in final.json()["proposals"]
    }


def test_brain_dump_same_sequence_interim_can_be_replaced_by_final(api_client) -> None:
    operation = _start_operation(api_client, key="start-replace-interim-operation")

    interim = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-replaceable-interim"},
        json={
            "segments": [
                {"sequence": 1, "text": "buy oat milk", "stability": "interim"}
            ]
        },
    )
    assert interim.status_code == 200, interim.text

    final = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "replace-interim-with-final"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "buy oat milk. call dentist",
                    "stability": "stable",
                }
            ]
        },
    )
    assert final.status_code == 200, final.text
    body = final.json()
    assert [(segment["sequence"], segment["text"], segment["stability"]) for segment in body["segments"]] == [
        (1, "buy oat milk. call dentist", "stable")
    ]
    assert [proposal["title"] for proposal in body["proposals"]] == [
        "Buy oat milk",
        "Call dentist",
    ]


def test_user_edits_survive_later_transcript_reconciliation_and_delete_before_save(api_client) -> None:
    operation = _start_operation(api_client, key="start-edit-operation")
    append = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-edit-segment"},
        json={
            "segments": [
                {"sequence": 1, "text": "Book flights. Call dentist.", "stability": "stable"}
            ]
        },
    ).json()
    first_id = append["proposals"][0]["id"]
    second_id = append["proposals"][1]["id"]

    edited = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{first_id}",
        headers={"Idempotency-Key": "edit-first-proposal"},
        json={"title": "Book refundable Lisbon flights", "expected_revision": append["revision"]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["proposals"][0]["status"] == "user_edited"

    deleted = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{second_id}",
        headers={"Idempotency-Key": "delete-second-proposal"},
        json={"deleted": True, "expected_revision": edited.json()["revision"]},
    )
    assert deleted.status_code == 200, deleted.text

    later = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-reworded-segment"},
        json={
            "segments": [
                {
                    "sequence": 2,
                    "text": "Book flights to Lisbon. Call dentist to move Monday appointment. Draft launch post.",
                    "stability": "stable",
                }
            ]
        },
    )
    assert later.status_code == 200, later.text
    titles_by_id = {proposal["id"]: proposal["title"] for proposal in later.json()["proposals"]}
    assert titles_by_id[first_id] == "Book refundable Lisbon flights"
    assert titles_by_id[second_id] == "Call dentist"
    assert any(proposal["title"] == "Draft launch post" for proposal in later.json()["proposals"])

    finish = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/finish",
        headers={"Idempotency-Key": "finish-edit-operation"},
        json={"expected_revision": later.json()["revision"]},
    )
    assert finish.status_code == 200, finish.text
    assert finish.json()["status"] == "awaiting_confirmation"

    commit = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-edit-operation"},
        json={"expected_revision": finish.json()["revision"]},
    )
    assert commit.status_code == 200, commit.text
    committed = commit.json()
    assert committed["status"] == "completed"
    assert committed["committed_task_ids"]

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert [item["title"] for item in inbox["items"]] == [
        "Book refundable Lisbon flights",
        "Draft launch post",
    ]


def test_brain_dump_commit_is_atomic_and_idempotent_on_retry(api_client) -> None:
    operation = _start_operation(api_client, key="start-idempotent-operation")
    appended = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-idempotent-segment"},
        json={
            "segments": [
                {"sequence": 1, "text": "Pay VAT. Send invoice.", "stability": "stable"}
            ]
        },
    ).json()
    finished = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/finish",
        headers={"Idempotency-Key": "finish-idempotent-operation"},
        json={"expected_revision": appended["revision"]},
    ).json()

    headers = {"Idempotency-Key": "commit-idempotent-operation"}
    first = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers=headers,
        json={"expected_revision": finished["revision"]},
    )
    duplicate = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers=headers,
        json={"expected_revision": finished["revision"]},
    )
    assert first.status_code == duplicate.status_code == 200
    assert duplicate.json()["committed_task_ids"] == first.json()["committed_task_ids"]

    retry_with_new_key = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-idempotent-operation-retry"},
        json={"expected_revision": first.json()["revision"]},
    )
    assert retry_with_new_key.status_code == 200
    assert retry_with_new_key.json()["committed_task_ids"] == first.json()["committed_task_ids"]

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert inbox["counts_by_state"]["inbox"] == 2
    assert [item["title"] for item in inbox["items"]] == ["Pay VAT", "Send invoice"]


def test_brain_dump_pause_resume_cancel_and_owner_scope(api_client, second_api_client) -> None:
    operation = _start_operation(api_client, key="start-resume-operation")
    paused = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/pause",
        headers={"Idempotency-Key": "pause-resume-operation"},
        json={"expected_revision": operation["revision"]},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused"

    resumed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/resume",
        headers={"Idempotency-Key": "resume-operation"},
        json={"expected_revision": paused.json()["revision"]},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "recording"

    cancelled = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/cancel",
        headers={"Idempotency-Key": "cancel-operation"},
        json={"expected_revision": resumed.json()["revision"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    client_a, client_b = second_api_client
    private_operation = client_a.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "start-private-operation"},
        json={"consent": {"microphone": True, "external_processing_allowed": False}},
    ).json()
    hidden = client_b.get(f"/api/brain-dump-operations/{private_operation['id']}")
    assert hidden.status_code == 404
