"""Item 2: exposure OFF must not remove an owner's privacy controls.

Turning ``voice_brain_dump`` OFF is exposure control, not authorization. An owner
who already has an operation keeps read/status plus the privacy commands
(withdraw consent, cancel, delete raw audio) over it; only new-capture/forward
surfaces are gated. Separately, the background runner must not advance external
provider work for an OFF owner, while privacy/purge duties keep running.
"""

from __future__ import annotations

import hashlib

from app.core.config import FeatureFlagSettings, FeatureFlagState
from tests.test_brain_dump_operations_api import (
    _manifest_hash,
    _start_operation,
    _upload_and_seal,
)


def _set_voice_flag(api_client, state: FeatureFlagState) -> None:
    """Restage the deploy-time baseline this app was built with.

    Since spec 010 the two managed flags resolve through
    ``FeatureFlagService``, which holds the config it was constructed with, so
    a harness that restaged only ``app.state.config`` would no longer move the
    baseline the gate actually reads. Production never restages either: both
    are built once from the same immutable config at startup.
    """

    config = api_client.app.state.config
    restaged = config.model_copy(
        update={
            "feature_flags": FeatureFlagSettings(
                states={"voice_brain_dump": state},
                internal_users=config.feature_flags.internal_users,
            )
        }
    )
    api_client.app.state.config = restaged
    api_client.app.state.container.feature_flag_service.config = restaged


def _revision(api_client, operation_id: str) -> int:
    return api_client.get(f"/api/brain-dump-operations/{operation_id}").json()[
        "revision"
    ]


def test_flag_off_keeps_privacy_controls_reachable_gates_new_capture(
    api_client,
) -> None:
    # Build an existing, reconciled operation while the flag is ON.
    operation = _start_operation(api_client, key="off-privacy-start")
    _upload_and_seal(
        api_client, operation, b"Pay VAT. Send invoice.", "off-privacy-seal"
    )
    op_id = operation["id"]

    _set_voice_flag(api_client, FeatureFlagState.OFF)

    # New-capture / forward surfaces are gated: fail-closed 404 "not available".
    start = api_client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "off-privacy-start-2"},
        json={
            "consent": {
                "microphone": True,
                "external_processing_allowed": False,
                "provider": None,
                "language_hints": [],
                "vocabulary": [],
            }
        },
    )
    assert start.status_code == 404 and "not available" in start.text.lower()
    for action in ("commit", "seal"):
        gated = api_client.post(
            f"/api/brain-dump-operations/{op_id}/{action}",
            headers={"Idempotency-Key": f"off-privacy-{action}"},
            json={"expected_revision": _revision(api_client, op_id)},
        )
        assert gated.status_code == 404, gated.text
        assert "not available" in gated.text.lower()
    upload = api_client.put(
        f"/api/brain-dump-operations/{op_id}/audio/1",
        content=b"more",
        headers={"X-Content-SHA256": hashlib.sha256(b"more").hexdigest()},
    )
    assert upload.status_code == 404, upload.text

    # Read/status stays reachable.
    read = api_client.get(f"/api/brain-dump-operations/{op_id}")
    assert read.status_code == 200, read.text

    # Privacy authority stays reachable: withdraw, delete raw audio, cancel.
    withdrawn = api_client.post(
        f"/api/brain-dump-operations/{op_id}/withdraw_consent",
        headers={"Idempotency-Key": "off-privacy-withdraw"},
        json={"expected_revision": _revision(api_client, op_id)},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["consent"]["external_processing_allowed"] is False

    deleted = api_client.post(
        f"/api/brain-dump-operations/{op_id}/delete_raw_audio",
        headers={"Idempotency-Key": "off-privacy-delete"},
        json={"expected_revision": _revision(api_client, op_id)},
    )
    assert deleted.status_code == 200, deleted.text

    cancelled = api_client.post(
        f"/api/brain-dump-operations/{op_id}/cancel",
        headers={"Idempotency-Key": "off-privacy-cancel"},
        json={"expected_revision": _revision(api_client, op_id)},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"


def test_runner_pauses_provider_work_for_flag_off_owner(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    operation = _start_operation(
        api_client, key="off-runner-start", external_processing_allowed=True
    )
    audio = b"queued provider needs this audio"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "off-runner-seal"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["provider_runs"][-1]["status"] == "pending"

    # OFF for this owner: the runner must not advance the due provider run.
    service.voice_enabled_for_owner = lambda _owner_id: False
    assert service.run_due_brain_dump_provider_runs() == 0
    still = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert still["provider_runs"][-1]["status"] == "pending"

    # ON again: the same due run is processed.
    service.voice_enabled_for_owner = lambda _owner_id: True
    assert service.run_due_brain_dump_provider_runs() >= 1
    advanced = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert advanced["provider_runs"][-1]["status"] != "pending"
