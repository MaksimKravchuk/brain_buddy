"""T029: one precedence rule for consent ``providers`` vs the legacy ``provider``.

Pinned decision: a non-empty ``providers`` list is authoritative. If the legacy
single ``provider`` field is *also* set it must be a member of that list, or the
consent is rejected fail-closed at the same pre-upload boundary that enforces the
complete configured vendor set. Legacy-only consent (no list) still resolves to a
singleton set, so an older single-provider client keeps working.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.core.config import VoiceAudioLimits
from app.exceptions import ValidationFailure
from app.modules.tasks import TaskRepository, TaskService
from app.utils.time import utcnow
from app.workflows.voice_brain_dump.domain import BrainDumpConsent
from app.workflows.voice_brain_dump.repository import OperationRepository
from app.workflows.voice_brain_dump.service import VoiceBrainDumpService
from app.workflows.voice_brain_dump.task_port import InProcessTaskPort

_EFFECTIVE = VoiceBrainDumpService._effective_consented_providers


class _ExternalStt:
    requires_external_processing = True
    max_cost_usd_per_operation = 1.0

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name


class _ExternalReconciler:
    requires_external_processing = True

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id


def _service(data_dir: Path, **kwargs: object) -> VoiceBrainDumpService:
    task_service = TaskService(TaskRepository(data_dir))
    return VoiceBrainDumpService(
        OperationRepository(data_dir),
        audio_limits=VoiceAudioLimits(
            allowed_mime_types=frozenset({"audio/x-brain-buddy-test-text"})
        ),
        task_port=InProcessTaskPort(task_service.create_native_inbox_task),
        **kwargs,
    )


def _consent(
    *, providers: list[str], provider: str | None, external: bool = True
) -> BrainDumpConsent:
    return BrainDumpConsent(
        microphone=True,
        external_processing_allowed=external,
        provider=provider,
        providers=providers,
        recorded_at=utcnow(),
    )


# --- Precedence in the effective-set projection -----------------------------


def test_effective_set_is_list_only_when_no_legacy_provider() -> None:
    assert _EFFECTIVE(_consent(providers=["openai"], provider=None)) == {"openai"}


def test_effective_set_is_singleton_for_legacy_only_consent() -> None:
    assert _EFFECTIVE(_consent(providers=[], provider="openai")) == {"openai"}


def test_effective_set_is_empty_when_nothing_named() -> None:
    assert _EFFECTIVE(_consent(providers=[], provider=None)) == set()


def test_matching_dual_field_resolves_to_the_authoritative_list() -> None:
    consent = _consent(providers=["deepgram", "openai"], provider="openai")
    assert _EFFECTIVE(consent) == {"deepgram", "openai"}


def test_list_is_authoritative_and_never_unions_a_disagreeing_legacy_provider() -> None:
    # The legacy field is NOT unioned in: a non-empty list wins outright, so a
    # disagreeing legacy provider can never silently widen the consented set.
    consent = _consent(providers=["openai"], provider="deepgram")
    assert _EFFECTIVE(consent) == {"openai"}


# --- Fail-closed enforcement at the pre-upload boundary ----------------------


def test_matching_dual_field_consent_is_accepted(data_dir: Path) -> None:
    service = _service(
        data_dir, allowed_external_provider_categories=frozenset({"openai"})
    )
    service._assert_external_provider_consent(
        _consent(providers=["openai"], provider="openai")
    )


def test_list_only_consent_is_accepted(data_dir: Path) -> None:
    service = _service(
        data_dir, allowed_external_provider_categories=frozenset({"openai"})
    )
    service._assert_external_provider_consent(
        _consent(providers=["openai"], provider=None)
    )


def test_legacy_only_consent_is_accepted(data_dir: Path) -> None:
    service = _service(
        data_dir, allowed_external_provider_categories=frozenset({"openai"})
    )
    service._assert_external_provider_consent(_consent(providers=[], provider="openai"))


def test_conflicting_dual_field_consent_is_rejected(data_dir: Path) -> None:
    # Both vendors are individually allow-listed, so this fails *because the two
    # fields disagree*, not because either names an unconfigured provider.
    service = _service(
        data_dir,
        allowed_external_provider_categories=frozenset({"openai", "deepgram"}),
    )
    with pytest.raises(ValidationFailure) as excinfo:
        service._assert_external_provider_consent(
            _consent(providers=["openai"], provider="deepgram")
        )
    assert "AUDIO_UPLOAD_PROVIDER_CONSENT_CONFLICT" in str(excinfo.value)


def test_precedence_does_not_weaken_the_complete_vendor_set_guard(
    data_dir: Path,
) -> None:
    # Split-vendor pipeline: consent whose (matching) legacy provider is in the
    # list but whose list omits the second required vendor still fails closed.
    service = _service(
        data_dir,
        accurate_stt=_ExternalStt("deepgram"),
        text_reconciler=_ExternalReconciler("openai"),
        allowed_external_provider_categories=frozenset({"deepgram", "openai"}),
    )
    with pytest.raises(ValidationFailure) as excinfo:
        service._assert_external_provider_consent(
            _consent(providers=["deepgram"], provider="deepgram")
        )
    assert "AUDIO_UPLOAD_PROVIDER_CONSENT_REQUIRED" in str(excinfo.value)

    # The complete matching set (with a matching legacy provider) is accepted.
    service._assert_external_provider_consent(
        _consent(providers=["deepgram", "openai"], provider="deepgram")
    )


def test_conflicting_dual_field_fails_closed_at_upload_without_persistence(
    api_client,
) -> None:
    """End-to-end: a conflicting consent uploads nothing and invokes no vendor."""

    service = api_client.app.state.container.voice_brain_dump_service
    service.allowed_external_provider_categories = frozenset({"openai", "deepgram"})

    started = api_client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "precedence-start"},
        json={
            "consent": {
                "microphone": True,
                "external_processing_allowed": True,
                "provider": "deepgram",
                "providers": ["openai"],
                "language_hints": [],
                "vocabulary": [],
            }
        },
    )
    assert started.status_code == 201, started.text
    operation_id = started.json()["id"]

    audio = b"conflicting consent must never upload"
    rejected = api_client.put(
        f"/api/brain-dump-operations/{operation_id}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert rejected.status_code in {400, 422}, rejected.text
    assert "AUDIO_UPLOAD_PROVIDER_CONSENT_CONFLICT" in rejected.text

    owner_id = api_client.get("/api/auth/me").json()["id"]
    persisted = service.get_brain_dump_operation(operation_id, owner_id=owner_id)
    assert persisted.audio_chunks == []
    assert persisted.media_ref is None
    assert persisted.segments == []
