"""Item 1: transcript segments carry a content hash that survives text purge.

FR-002 promises segment IDs plus content hashes remain after exact text is
purged. Every persisted segment now stamps content_sha256 at creation, and the
working-artifact purge retains a durable segment-ID -> content-hash map so a
cited segment can still be authenticated once its text is gone.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from app.schemas.tasks import ExpectedRevisionRequest
from tests.test_brain_dump_commit_ledger import _drive_to_awaiting, _owner_id


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_segment_content_hash_present_at_creation_and_survives_purge(
    api_client,
) -> None:
    container = api_client.app.state.container
    service = container.voice_brain_dump_service
    repo = container.voice_operation_repo
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "seg-hash")
    op_id = operation["id"]

    review = service.get_brain_dump_operation(op_id, owner_id=owner_id)
    assert review.segments, "precondition: reconciled transcript segments exist"
    # Every segment stamps the exact-text hash at persistence.
    for segment in review.segments:
        assert segment.content_sha256 == _sha256(segment.text)
    original_hashes = {s.id: s.content_sha256 for s in review.segments}
    original_texts = [s.text for s in review.segments]

    service.commit_brain_dump_operation(
        op_id,
        ExpectedRevisionRequest(expected_revision=finished["revision"]),
        owner_id=owner_id,
        idempotency_key="seg-hash-commit",
    )
    persisted = service.get_brain_dump_operation(op_id, owner_id=owner_id)
    repo.save_brain_dump_operation(
        persisted.model_copy(
            update={
                "working_artifacts_expires_at": persisted.working_artifacts_expires_at
                - timedelta(days=14)
            }
        )
    )
    assert service.purge_expired_working_artifacts() >= 1

    swept = service.get_brain_dump_operation(op_id, owner_id=owner_id)
    # Exact text is gone, but the segment-ID -> content-hash map survives intact.
    assert swept.segments == []
    survived = {h.id: h.content_sha256 for h in swept.segment_content_hashes}
    assert survived == original_hashes

    # None of the exact utterance text remains anywhere in the voice DB.
    dump = json.dumps(
        {
            "operation": swept.model_dump(mode="json"),
            "idempotency": [
                r.response_body
                for r in repo.list_idempotency_for_owner(owner_id=owner_id)
            ],
        }
    )
    for text in original_texts:
        assert text not in dump
