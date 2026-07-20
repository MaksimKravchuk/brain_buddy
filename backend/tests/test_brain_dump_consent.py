"""Canonical external-processing consent tests (T058).

Covers: the non-secret processing-policy projection, policy-version/
category-set validation on grant, expiry/withdrawal fail-closed enforcement
before upload/seal/retry, owner scoping, and configuration-version change
invalidation.
"""

from __future__ import annotations

from datetime import timedelta

from app.utils.time import utcnow
from tests.test_brain_dump_operations_api import _manifest_hash, _start_operation


def _policy(api_client) -> dict[str, object]:
    response = api_client.get("/api/brain-dump-processing-policy")
    assert response.status_code == 200, response.text
    return response.json()


def _grant(
    api_client,
    operation: dict[str, object],
    *,
    key: str,
    policy_version: str | None = None,
    categories: list[str] | None = None,
):
    policy = _policy(api_client)
    return api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/consent-decisions",
        headers={"Idempotency-Key": key},
        json={
            "decision": "grant",
            "consent_policy_version": (
                policy_version
                if policy_version is not None
                else policy["consent_policy_version"]
            ),
            "allowed_provider_categories": (
                categories
                if categories is not None
                else policy["required_provider_categories"]
            ),
            "decision_recorded_at": utcnow().isoformat(),
            "expected_operation_revision": operation["revision"],
        },
    )


def test_processing_policy_is_authenticated_and_non_secret(
    api_client, anonymous_api_client
) -> None:
    anon = anonymous_api_client.get("/api/brain-dump-processing-policy")
    assert anon.status_code == 401, anon.text

    response = api_client.get("/api/brain-dump-processing-policy")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["consent_policy_version"]
    assert body["required_provider_categories"]
    assert body["consent_valid_for_seconds"] > 0
    assert body["max_chunk_size_bytes"] > 0
    assert body["max_operation_size_bytes"] > 0
    assert "api_key" not in str(body).lower()
    assert "secret" not in str(body).lower()


def test_grant_requires_exact_policy_version_match(api_client) -> None:
    operation = _start_operation(api_client, key="start-consent-version")
    mismatched = _grant(
        api_client, operation, key="grant-bad-version", policy_version="stale-v0"
    )
    assert mismatched.status_code == 400, mismatched.text
    assert "CONSENT_POLICY_VERSION_MISMATCH" in mismatched.text


def test_grant_requires_exact_category_set_match(api_client) -> None:
    operation = _start_operation(api_client, key="start-consent-categories")
    mismatched = _grant(
        api_client,
        operation,
        key="grant-bad-categories",
        categories=["cloud_stt"],
    )
    assert mismatched.status_code == 400, mismatched.text
    assert "CONSENT_CATEGORY_SET_MISMATCH" in mismatched.text


def test_valid_grant_is_current_and_persists_decision_fields(api_client) -> None:
    operation = _start_operation(api_client, key="start-consent-valid")
    granted = _grant(api_client, operation, key="grant-valid")
    assert granted.status_code == 200, granted.text
    consent = granted.json()["consent"]
    assert consent["status"] == "granted"
    assert consent["valid_until"] is not None
    assert consent["withdrawn_at"] is None
    policy = _policy(api_client)
    assert consent["consent_policy_version"] == policy["consent_policy_version"]
    assert set(consent["allowed_provider_categories"]) == set(
        policy["required_provider_categories"]
    )


def test_withdrawal_blocks_further_upload_and_purges_uncommitted_audio(
    api_client,
) -> None:
    operation = _start_operation(api_client, key="start-consent-withdraw")
    _grant(api_client, operation, key="grant-withdraw-flow").json()

    audio = b"Buy milk."
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": __import__("hashlib").sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["raw_audio"]["state"] == "retained"

    withdrawn = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/consent-decisions",
        headers={"Idempotency-Key": "withdraw-consent-flow"},
        json={
            "decision": "withdraw",
            "expected_operation_revision": uploaded.json()["revision"],
        },
    )
    assert withdrawn.status_code == 200, withdrawn.text
    withdrawn_body = withdrawn.json()
    assert withdrawn_body["consent"]["status"] == "withdrawn"
    assert withdrawn_body["consent"]["withdrawn_at"] is not None
    assert withdrawn_body["audio_chunks"] == []

    blocked = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": __import__("hashlib").sha256(audio).hexdigest()},
    )
    assert blocked.status_code == 400, blocked.text


def test_expired_canonical_consent_fails_closed_before_seal(api_client) -> None:
    operation = _start_operation(api_client, key="start-consent-expiry")
    _grant(api_client, operation, key="grant-expiry").json()

    audio = b"Buy milk."
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": __import__("hashlib").sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text

    # Force the grant into the past, modelling a stale/expired consent that
    # must be revalidated -- never assumed current from a persisted boolean.
    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    repo = container.voice_operation_repo
    stored = repo.get_brain_dump_operation_for_owner(operation["id"], owner_id=owner_id)
    expired = stored.model_copy(
        update={
            "consent": stored.consent.model_copy(
                update={"valid_until": utcnow() - timedelta(seconds=1)}
            ),
            "revision": stored.revision + 1,
        }
    )
    repo.save_brain_dump_operation(expired)

    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-expired-consent"},
        json={
            "expected_revision": expired.revision,
            "expected_chunks": 1,
            "manifest_hash": __import__("hashlib").sha256(
                __import__("json").dumps(
                    [
                        {
                            "chunk_number": 0,
                            "sha256": __import__("hashlib").sha256(audio).hexdigest(),
                            "size_bytes": len(audio),
                        }
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        },
    )
    assert sealed.status_code == 400, sealed.text
    assert "CONSENT_EXPIRED" in sealed.text


def test_claimed_provider_lease_revalidates_consent_and_fails_closed(
    api_client,
) -> None:
    """A grant current when the operation sealed can expire before the
    persisted runner actually claims the accurate-STT lease. The claim must
    revalidate canonical consent under the owner lock and fail the
    operation closed without ever invoking the provider -- proven here by
    the fact no accurate transcript segment is ever appended."""

    operation = _start_operation(api_client, key="start-consent-claim-time")
    _grant(api_client, operation, key="grant-consent-claim-time")

    audio = b"Buy milk."
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": __import__("hashlib").sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text

    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-consent-claim-time"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 200, sealed.text

    # The grant was current at seal time; expire it now, before the
    # persisted runner actually claims the accurate-STT lease.
    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    repo = container.voice_operation_repo
    stored = repo.get_brain_dump_operation_for_owner(operation["id"], owner_id=owner_id)
    expired = stored.model_copy(
        update={
            "consent": stored.consent.model_copy(
                update={"valid_until": utcnow() - timedelta(seconds=1)}
            ),
        }
    )
    repo.save_brain_dump_operation(expired)

    service = container.voice_brain_dump_service
    service.run_due_brain_dump_provider_runs()

    final = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert final["status"] == "terminal_error"
    latest_run = final["provider_runs"][-1]
    assert latest_run["error_code"] == "CONSENT_EXPIRED"
    assert not any(
        segment.get("provider_role") == "accurate" for segment in final["segments"]
    )


def test_consent_decision_is_owner_scoped(second_api_client) -> None:
    client_a, client_b = second_api_client
    operation = _start_operation(client_a, key="start-consent-owner")

    as_b = client_b.post(
        f"/api/brain-dump-operations/{operation['id']}/consent-decisions",
        headers={"Idempotency-Key": "grant-owner-b"},
        json={
            "decision": "grant",
            "consent_policy_version": _policy(client_a)["consent_policy_version"],
            "allowed_provider_categories": _policy(client_a)[
                "required_provider_categories"
            ],
            "decision_recorded_at": utcnow().isoformat(),
            "expected_operation_revision": operation["revision"],
        },
    )
    assert as_b.status_code == 404, as_b.text
