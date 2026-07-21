"""Pure schema-v2 transcript/proposal projection rules for Voice Brain Dump."""

from __future__ import annotations

from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.exceptions import ValidationFailure
from app.schemas.common import StorageBaseModel

ProviderRole = Literal["browser_preview", "fast", "accurate"]
TranscriptStability = Literal["interim", "stable"]
PatchProducer = Literal["fast", "accurate", "reconciler", "user"]
PatchOperation = Literal["add", "update", "split", "merge", "remove", "supersede"]


@dataclass(frozen=True)
class TranscriptHypothesis:
    """One immutable transcript version with explicit audio span and supersession."""

    id: str
    sequence: int
    start_ms: int
    end_ms: int
    text: str
    stability: TranscriptStability
    provider_role: ProviderRole
    confidence: float | None = None
    language: str | None = None
    model: str | None = None
    supersedes_segment_ids: list[str] = dataclass_field(default_factory=list)

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValidationFailure("Transcript sequence must be positive.")
        if self.start_ms < 0 or self.end_ms < 0 or self.end_ms <= self.start_ms:
            raise ValidationFailure(
                "Transcript hypothesis requires a positive audio span."
            )
        if not self.text.strip():
            raise ValidationFailure("Transcript hypothesis text is required.")


@dataclass(frozen=True)
class ProposalConflict:
    field: str
    current_value: str | None
    suggested_value: str | None
    producer: PatchProducer
    source_segment_ids: list[str] = dataclass_field(default_factory=list)


@dataclass(frozen=True)
class ReconciledProposal:
    id: str
    title: str
    source_segment_ids: list[str]
    status: Literal["provisional", "reconciled", "user_edited", "conflicted"]
    predecessor_ids: list[str] = dataclass_field(default_factory=list)
    successor_ids: list[str] = dataclass_field(default_factory=list)
    locked_fields: list[str] = dataclass_field(default_factory=list)
    conflicts: list[ProposalConflict] = dataclass_field(default_factory=list)
    tombstoned: bool = False
    ordinal: int = 1
    revision: int = 1
    title_revision: int = 1
    """Revision at which ``title`` was last changed; drives stale-base checks."""


@dataclass(frozen=True)
class ProposalPatch:
    """Append-only proposal patch. Proposal IDs, never array positions, are targets."""

    operation: PatchOperation
    proposal_id: str
    producer: PatchProducer
    title: str | None = None
    source_segment_ids: list[str] = dataclass_field(default_factory=list)
    predecessor_ids: list[str] = dataclass_field(default_factory=list)
    successor_ids: list[str] = dataclass_field(default_factory=list)
    locked_fields: list[str] = dataclass_field(default_factory=list)
    base_revision: int | None = None
    """Revision this patch was computed against; drives stale-base handling.

    When set and older than the target's ``title_revision``, a title change
    is treated as a *conflicting stale patch* (PA-05: rejected into an open
    conflict, never a silent overwrite). A patch that leaves ``title`` unset
    only ever touches disjoint fields and always rebases cleanly (PA-04).
    """

    @classmethod
    def add(
        cls,
        *,
        proposal_id: str,
        title: str,
        source_segment_ids: list[str],
        producer: PatchProducer,
        base_revision: int | None = None,
    ) -> ProposalPatch:
        return cls(
            operation="add",
            proposal_id=proposal_id,
            title=title,
            source_segment_ids=source_segment_ids,
            producer=producer,
            base_revision=base_revision,
        )

    @classmethod
    def update(
        cls,
        *,
        proposal_id: str,
        producer: PatchProducer,
        title: str | None = None,
        source_segment_ids: list[str] | None = None,
        locked_fields: list[str] | None = None,
        base_revision: int | None = None,
    ) -> ProposalPatch:
        return cls(
            operation="update",
            proposal_id=proposal_id,
            title=title,
            source_segment_ids=source_segment_ids or [],
            locked_fields=locked_fields or [],
            producer=producer,
            base_revision=base_revision,
        )

    @classmethod
    def remove(cls, *, proposal_id: str, producer: PatchProducer) -> ProposalPatch:
        return cls(operation="remove", proposal_id=proposal_id, producer=producer)

    @classmethod
    def merge(
        cls,
        *,
        proposal_id: str,
        title: str,
        predecessor_ids: list[str],
        source_segment_ids: list[str],
        producer: PatchProducer = "reconciler",
    ) -> ProposalPatch:
        return cls(
            operation="merge",
            proposal_id=proposal_id,
            title=title,
            predecessor_ids=predecessor_ids,
            source_segment_ids=source_segment_ids,
            producer=producer,
        )

    @classmethod
    def split(
        cls,
        *,
        proposal_id: str,
        title: str,
        predecessor_ids: list[str],
        source_segment_ids: list[str],
        producer: PatchProducer = "reconciler",
    ) -> ProposalPatch:
        return cls(
            operation="split",
            proposal_id=proposal_id,
            title=title,
            predecessor_ids=predecessor_ids,
            source_segment_ids=source_segment_ids,
            producer=producer,
        )

    @classmethod
    def supersede(
        cls,
        *,
        proposal_id: str,
        title: str,
        predecessor_ids: list[str],
        source_segment_ids: list[str],
        producer: PatchProducer = "reconciler",
    ) -> ProposalPatch:
        return cls(
            operation="supersede",
            proposal_id=proposal_id,
            title=title,
            predecessor_ids=predecessor_ids,
            source_segment_ids=source_segment_ids,
            producer=producer,
        )


@dataclass(frozen=True)
class ProposalProjection:
    active: list[ReconciledProposal]
    history: list[ReconciledProposal]
    patches: list[ProposalPatch]


def active_transcript_hypotheses(
    hypotheses: list[TranscriptHypothesis],
) -> list[TranscriptHypothesis]:
    """Return non-superseded transcript versions in audio order."""

    superseded = {
        superseded_id
        for hypothesis in hypotheses
        for superseded_id in hypothesis.supersedes_segment_ids
    }
    return sorted(
        [hypothesis for hypothesis in hypotheses if hypothesis.id not in superseded],
        key=lambda segment: (
            segment.start_ms,
            segment.end_ms,
            segment.sequence,
            segment.id,
        ),
    )


def apply_proposal_patches(
    base: list[ReconciledProposal], patches: list[ProposalPatch]
) -> ProposalProjection:
    """Project append-only patches while preserving user locks and tombstone history."""

    by_id = {proposal.id: proposal for proposal in base}
    order = [proposal.id for proposal in base]
    history: dict[str, ReconciledProposal] = dict(by_id)

    for patch in patches:
        if patch.operation in {"add", "merge", "split", "supersede"}:
            if patch.title is None:
                raise ValidationFailure(
                    "Proposal add/split/merge/supersede requires a title."
                )
            for predecessor_id in patch.predecessor_ids:
                predecessor = by_id.get(predecessor_id)
                if predecessor is not None:
                    successor_ids = sorted(
                        {*predecessor.successor_ids, patch.proposal_id}
                    )
                    tombstone = _replace(
                        predecessor,
                        tombstoned=True,
                        successor_ids=successor_ids,
                        revision=predecessor.revision + 1,
                    )
                    by_id[predecessor_id] = tombstone
                    history[predecessor_id] = tombstone
            ordinal = _insertion_ordinal(by_id, order, patch.predecessor_ids)
            proposal = ReconciledProposal(
                id=patch.proposal_id,
                title=patch.title,
                source_segment_ids=patch.source_segment_ids,
                predecessor_ids=patch.predecessor_ids,
                status=(
                    "reconciled" if patch.producer == "reconciler" else "provisional"
                ),
                ordinal=ordinal,
            )
            by_id[proposal.id] = proposal
            history[proposal.id] = proposal
            if proposal.id not in order:
                order.append(proposal.id)
            continue

        current = by_id.get(patch.proposal_id)
        if current is None:
            raise ValidationFailure(f"Unknown proposal ID '{patch.proposal_id}'.")

        if patch.operation == "remove":
            if patch.producer == "user":
                # An explicit user delete is already confirmed -- apply it now.
                updated = _replace(
                    current, tombstoned=True, revision=current.revision + 1
                )
            else:
                # A provider-driven destructive removal must stay visible and
                # individually confirmed rather than silently disappearing:
                # surface it as an open conflict (blocking freeze/confirm)
                # instead of tombstoning the proposal outright.
                updated = _replace(
                    current,
                    status="conflicted",
                    conflicts=[
                        *current.conflicts,
                        ProposalConflict(
                            field="removal",
                            current_value="active",
                            suggested_value="removed",
                            producer=patch.producer,
                            source_segment_ids=patch.source_segment_ids,
                        ),
                    ],
                    revision=current.revision + 1,
                )
            by_id[current.id] = updated
            history[current.id] = updated
            continue

        if patch.operation != "update":
            raise ValidationFailure(f"Unsupported proposal patch '{patch.operation}'.")

        locked_fields = sorted({*current.locked_fields, *patch.locked_fields})
        status = current.status
        conflicts = list(current.conflicts)
        title = current.title
        title_revision = current.title_revision
        source_segment_ids = current.source_segment_ids
        wants_title_change = patch.title is not None and patch.title != current.title
        is_stale_base = (
            wants_title_change
            and patch.base_revision is not None
            and patch.base_revision < current.title_revision
        )
        if patch.producer == "user":
            status = "user_edited"
            if patch.title is not None:
                title = patch.title
                title_revision = current.title_revision + 1
            if patch.source_segment_ids:
                source_segment_ids = patch.source_segment_ids
        elif (
            "title" in current.locked_fields
            and patch.title
            and patch.title != current.title
        ):
            status = "conflicted"
            conflicts.append(
                ProposalConflict(
                    field="title",
                    current_value=current.title,
                    suggested_value=patch.title,
                    producer=patch.producer,
                    source_segment_ids=patch.source_segment_ids,
                )
            )
        elif is_stale_base:
            # PA-05: a title change computed against a stale base conflicts
            # instead of silently overwriting a newer concurrent change.
            status = "conflicted"
            conflicts.append(
                ProposalConflict(
                    field="title",
                    current_value=current.title,
                    suggested_value=patch.title,
                    producer=patch.producer,
                    source_segment_ids=patch.source_segment_ids,
                )
            )
            if patch.source_segment_ids:
                # PA-04: disjoint (non-title) changes in the same patch still
                # rebase and apply even when the title itself conflicts.
                source_segment_ids = patch.source_segment_ids
        else:
            if patch.title is not None:
                title = patch.title
                title_revision = current.title_revision + 1
            if patch.source_segment_ids:
                source_segment_ids = patch.source_segment_ids
            status = "reconciled" if patch.producer == "reconciler" else status
        updated = _replace(
            current,
            title=title,
            title_revision=title_revision,
            source_segment_ids=source_segment_ids,
            status=status,
            locked_fields=locked_fields,
            conflicts=conflicts,
            revision=current.revision + 1,
        )
        by_id[current.id] = updated
        history[current.id] = updated

    active = [
        by_id[item_id]
        for item_id in order
        if item_id in by_id and not by_id[item_id].tombstoned
    ]
    active.sort(key=lambda proposal: (proposal.ordinal, proposal.id))
    active = [
        _replace(proposal, ordinal=index + 1) for index, proposal in enumerate(active)
    ]
    return ProposalProjection(
        active=active, history=list(history.values()), patches=patches
    )


def _insertion_ordinal(
    by_id: dict[str, ReconciledProposal], order: list[str], predecessor_ids: list[str]
) -> int:
    predecessor_ordinals = [
        by_id[item_id].ordinal for item_id in predecessor_ids if item_id in by_id
    ]
    if predecessor_ordinals:
        return min(predecessor_ordinals)
    return len([proposal for proposal in by_id.values() if not proposal.tombstoned]) + 1


def _replace(proposal: ReconciledProposal, **updates: Any) -> ReconciledProposal:
    return replace(proposal, **updates)


# --- Operation-private persistence records (ADR-0001/0002: owned by this
# application workflow, never by Capture/Tasks) --------------------------

BrainDumpStatus = Literal[
    "recording",
    "paused",
    "sealing",
    "fast_processing",
    "accurate_transcribing",
    "reconciling",
    "retryable_error",
    "terminal_error",
    "awaiting_confirmation",
    "committing",
    "completed",
    "cancelled",
]
BrainDumpProposalStatus = Literal[
    "provisional",
    "wording_changing",
    "ready_to_review",
    "user_edited",
    "reconciled",
    "conflicted",
]


class IdempotencyRecord(StorageBaseModel):
    """Persisted result pointer for one owner-scoped mutating voice command."""

    key: str
    command: str
    request_hash: str
    resource_id: str
    response_body: dict[str, object]
    created_at: datetime


class BrainDumpConsent(StorageBaseModel):
    microphone: bool
    external_processing_allowed: bool = False
    recorded_at: datetime
    provider: str | None = None
    language_hints: list[str] = Field(default_factory=list, max_length=10)
    vocabulary: list[str] = Field(default_factory=list, max_length=200)
    # Canonical, additive external-processing consent fields (ADR-0002/0008
    # mobile contract). ``consent_policy_version`` is only ever set once a
    # caller has recorded a decision through the new canonical
    # ``consent-decisions`` command; a ``None`` value means this operation
    # predates that contract and every current-consent check below falls
    # back to the legacy ``provider`` membership check instead.
    consent_policy_version: str | None = None
    allowed_provider_categories: list[str] = Field(default_factory=list, max_length=20)
    decision_recorded_at: datetime | None = None
    valid_until: datetime | None = None
    withdrawn_at: datetime | None = None
    status: Literal["granted", "withdrawn"] | None = None


class BrainDumpConsentDecisionDocument(StorageBaseModel):
    """Append-only owner-scoped external-processing consent decision."""

    id: str
    decision: Literal["grant", "withdraw"]
    consent_policy_version: str | None = None
    allowed_provider_categories: list[str] = Field(default_factory=list, max_length=20)
    decision_recorded_at: datetime | None = None
    valid_until: datetime | None = None
    recorded_at: datetime


class BrainDumpTranscriptSegmentDocument(StorageBaseModel):
    id: str
    sequence: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=20_000)
    stability: Literal["interim", "stable"]
    start_ms: int = Field(default=0, ge=0)
    end_ms: int = Field(default=1, gt=0)
    provider_role: Literal["browser_preview", "fast", "accurate"] = "browser_preview"
    provider: str | None = None
    model: str | None = None
    supersedes_segment_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class BrainDumpProposalConflictDocument(StorageBaseModel):
    field: str = Field(min_length=1, max_length=100)
    current_value: str | None = Field(default=None, max_length=500)
    suggested_value: str | None = Field(default=None, max_length=500)
    producer: Literal["fast", "accurate", "reconciler", "user"] = "reconciler"
    source_segment_ids: list[str] = Field(default_factory=list)


class BrainDumpProposalDocument(StorageBaseModel):
    id: str
    ordinal: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    status: BrainDumpProposalStatus = "provisional"
    source_segment_ids: list[str] = Field(default_factory=list)
    predecessor_ids: list[str] = Field(default_factory=list)
    successor_ids: list[str] = Field(default_factory=list)
    locked_fields: list[str] = Field(default_factory=list)
    conflicts: list[BrainDumpProposalConflictDocument] = Field(default_factory=list)
    deleted: bool = False
    user_edited: bool = False
    title_revision: int = Field(default=1, ge=1)
    """Revision at which ``title`` was last changed; drives stale-base checks
    for reconciler patches applied through ``apply_proposal_patches``."""
    created_at: datetime
    updated_at: datetime
    revision: int = Field(default=1, ge=1)


class BrainDumpAudioChunkDocument(StorageBaseModel):
    chunk_number: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    mime_type: str | None = None
    cumulative_duration_seconds: float | None = Field(default=None, gt=0)
    received_at: datetime


class BrainDumpProviderRunDocument(StorageBaseModel):
    """Durable checkpoint for one sealed-audio provider stage."""

    id: str
    role: Literal["accurate_stt", "reconciler"]
    status: Literal[
        "pending", "running", "succeeded", "retryable_error", "terminal_error"
    ]
    input_hash: str = Field(min_length=64, max_length=64)
    checkpoint: Literal["sealed", "accurate_transcribed", "reconciled"]
    attempt: int = Field(default=0, ge=0)
    recovery_count: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=1000)
    error_code: str | None = Field(default=None, max_length=100)
    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    template_version: str | None = Field(default=None, max_length=100)
    estimated_cost_usd: float = Field(default=0.0, ge=0)
    reserved_cost_usd: float = Field(default=0.0, ge=0)
    """Worst-case admission reservation persisted before provider I/O."""
    consumed_cost_usd: float = Field(default=0.0, ge=0)
    """Accepted/actual spend reconciled after the provider attempt completes."""
    output_segment_ids: list[str] = Field(default_factory=list)
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class BrainDumpProposalPatchDocument(StorageBaseModel):
    """Immutable audit record for one applied proposal projection change."""

    id: str
    sequence: int = Field(ge=1)
    operation: Literal["add", "update", "split", "merge", "remove", "supersede"]
    proposal_id: str
    producer: Literal["fast", "accurate", "reconciler", "user"]
    title: str | None = None
    source_segment_ids: list[str] = Field(default_factory=list)
    predecessor_ids: list[str] = Field(default_factory=list)
    successor_ids: list[str] = Field(default_factory=list)
    locked_fields: list[str] = Field(default_factory=list)
    base_revision: int | None = None
    created_at: datetime


class BrainDumpActionReceiptDocument(StorageBaseModel):
    """Immutable confirmation record linking a canonical task to its source."""

    id: str
    proposal_id: str
    task_id: str | None = None
    """``None`` only for a ``failed``/``skipped`` outcome -- no Task was
    ever created for that action, so nothing exists to reference."""
    child_idempotency_key: str
    source_segment_ids: list[str] = Field(default_factory=list)
    proposal_patch_ids: list[str] = Field(default_factory=list)
    source_operation_id: str | None = None
    source_manifest_hash: str | None = Field(default=None, min_length=64, max_length=64)
    reconciliation_run_id: str | None = None
    reconciliation_provider: str | None = Field(default=None, max_length=100)
    reconciliation_model: str | None = Field(default=None, max_length=100)
    reconciliation_template_version: str | None = Field(default=None, max_length=100)
    reconciliation_quality: Literal[
        "none", "provisional_only", "accurate", "conflicted"
    ] = "none"
    confirmed_title_sha256: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    proposal_revision: int | None = Field(default=None, ge=1)
    user_edited: bool = False
    confidence: Literal["unknown"] = "unknown"
    confirmed_by_actor_id: str | None = None
    decision: Literal["create_native_inbox_task"] = "create_native_inbox_task"
    confirmed_at: datetime
    # Canonical batch/action linkage (ADR-0002 "H(operation_id, batch_id,
    # action_id)"). ``None`` on receipts created by the legacy proposal-keyed
    # commit path that predates ``ProposalBatch``.
    batch_id: str | None = None
    action_id: str | None = None
    outcome: Literal["succeeded", "failed", "skipped"] = "succeeded"


class BrainDumpActionReceiptAttemptDocument(StorageBaseModel):
    """Append-only, never-mutated attempt log for one confirm-time action.

    Persisted in its own committed transaction *before* the action's
    ``TaskPort`` call (``started``) and again in a separate committed
    transaction after it resolves (``succeeded``/``failed_retryable``/
    ``failed_terminal``/``skipped_dependency``). Together with the
    permanent, owner-scoped ``native_inbox_task_sources`` uniqueness the
    Tasks module enforces for the same ``H(operation_id, batch_id,
    action_id)`` key, this is what makes a crash between Task creation and
    this operation's terminal write recoverable rather than silently
    untraceable: the next attempt at this action always finds either its
    own prior ``started`` row or the permanent Task-side source key, never
    a blank slate that would risk a duplicate Task. ``BrainDumpActionReceiptDocument``
    remains the single folded/terminal projection derived from these rows.
    """

    id: str
    batch_id: str
    action_id: str
    sequence: int = Field(ge=1)
    """Append order across the whole operation, not per-action order."""
    attempt: int = Field(ge=1)
    """Retry counter for this exact action -- 1 on the first attempt."""
    request_hash: str = Field(min_length=1, max_length=128)
    status: Literal[
        "started",
        "succeeded",
        "failed_retryable",
        "failed_terminal",
        "skipped_dependency",
    ]
    task_id: str | None = None
    error_code: str | None = Field(default=None, max_length=100)
    created_at: datetime


class BrainDumpProposalBatchActionDocument(StorageBaseModel):
    """Immutable per-action review snapshot frozen at batch creation.

    Never carries a result/status field: results are a separate projection
    folded from :class:`BrainDumpActionReceiptDocument` rows, exactly as the
    mobile API contract requires ("action snapshot"/"result" separation).
    """

    action_id: str
    proposal_id: str
    title: str = Field(min_length=1, max_length=500)
    target: Literal["native_inbox"] = "native_inbox"
    before_summary: str = Field(min_length=1, max_length=1000)
    after_summary: str = Field(min_length=1, max_length=1000)
    source_cue: str | None = Field(default=None, max_length=200)
    confidence: Literal["unknown"] = "unknown"
    warnings: list[str] = Field(default_factory=list, max_length=20)
    destination: Literal["native_inbox"] = "native_inbox"


class BrainDumpProposalBatchDocument(StorageBaseModel):
    """Immutable frozen review snapshot; only ``status``/``committed_at``/
    ``revision`` change after creation. ``actions`` is byte-stable forever."""

    id: str
    based_on_proposal_revision: int = Field(ge=1)
    status: Literal["frozen", "committed", "superseded", "failed"] = "frozen"
    """``failed``: every action resolved (succeeded or terminally failed) but
    at least one did not succeed; per-action results are the source of truth
    for what to retry, and retrying requires a fresh freeze (ADR-0002 "the
    batch becomes failed with per-action results and can be retried
    idempotently")."""
    actions: list[BrainDumpProposalBatchActionDocument] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    created_at: datetime
    committed_at: datetime | None = None
    revision: int = Field(default=1, ge=1)


class BrainDumpOperationDocument(StorageBaseModel):
    """Operation-private workspace for native voice Brain Dump capture."""

    id: str
    owner_id: str
    kind: Literal["voice_brain_dump"] = "voice_brain_dump"
    status: BrainDumpStatus
    consent: BrainDumpConsent
    segments: list[BrainDumpTranscriptSegmentDocument] = Field(default_factory=list)
    proposals: list[BrainDumpProposalDocument] = Field(default_factory=list)
    media_ref: str | None = None
    audio_chunks: list[BrainDumpAudioChunkDocument] = Field(default_factory=list)
    raw_audio_expires_at: datetime | None = None
    """Set once, at successful reconciliation, to ``reconciled_at + raw_audio_retention``.

    This is the sole clock the raw-audio retention sweep uses. It is never
    recomputed from a later ``updated_at`` mutation (a proposal edit, consent
    withdrawal, etc.) so an operation cannot silently outlive its configured
    raw-audio retention just because someone touched it after reconciling.
    """
    sealed_manifest_hash: str | None = Field(default=None, min_length=64, max_length=64)
    working_artifacts_expires_at: datetime | None = None
    reconciliation_quality: Literal[
        "none", "provisional_only", "accurate", "conflicted"
    ] = "none"
    provider_runs: list[BrainDumpProviderRunDocument] = Field(default_factory=list)
    proposal_patches: list[BrainDumpProposalPatchDocument] = Field(default_factory=list)
    action_receipts: list[BrainDumpActionReceiptDocument] = Field(default_factory=list)
    action_receipt_attempts: list[BrainDumpActionReceiptAttemptDocument] = Field(
        default_factory=list
    )
    """Append-only attempt log behind ``action_receipts`` -- see
    :class:`BrainDumpActionReceiptAttemptDocument`. Never replayed/removed."""
    status_history: list[BrainDumpStatus] = Field(default_factory=list)
    committed_task_ids: list[str] = Field(default_factory=list)
    legacy_import: Literal["legacy_preview_only"] | None = None
    """One-time marker for an active schema-v1 workspace projected into v2."""
    manual_review: bool = False
    """Explicit owner-selected provisional review after validation retries
    exhaust, or after an active ``legacy_preview_only`` import -- both cases
    require the same explicit ``review-provisional`` gate before a batch may
    be frozen/committed provisionally."""
    provisional_review_accepted_at: datetime | None = None
    """Set by ``review_brain_dump_provisionally``; exposed for audit/UI."""
    proposal_revision: int = Field(default=1, ge=1)
    """Operation-level counter bumped by any accepted proposal patch; a
    ``ProposalBatch`` freezes against this value and any later change
    supersedes it (ADR-0002 "freeze/confirm, patch, and conflicts")."""
    consent_decisions: list[BrainDumpConsentDecisionDocument] = Field(
        default_factory=list
    )
    proposal_batches: list[BrainDumpProposalBatchDocument] = Field(default_factory=list)
    raw_audio_state: Literal[
        "not_received", "retained", "deletion_pending", "deleted"
    ] = "not_received"
    raw_audio_deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=2, ge=1)
    revision: int = Field(default=1, ge=1)


def active_proposal_batch(
    operation: BrainDumpOperationDocument,
) -> BrainDumpProposalBatchDocument | None:
    """The one batch still awaiting resolution, if any: either currently
    frozen, or ``failed`` (a partial-failure result the owner has not yet
    superseded with a fresh freeze). Committed/superseded batches are never
    "active"."""

    for batch in reversed(operation.proposal_batches):
        if batch.status in {"frozen", "failed"}:
            return batch
    return None


def committed_proposal_batch(
    operation: BrainDumpOperationDocument,
) -> BrainDumpProposalBatchDocument | None:
    """The most recently committed batch, if any."""

    for batch in reversed(operation.proposal_batches):
        if batch.status == "committed":
            return batch
    return None


def import_mode(
    operation: BrainDumpOperationDocument,
) -> Literal["native_v2", "legacy_preview_only"]:
    return (
        "legacy_preview_only"
        if operation.legacy_import == "legacy_preview_only"
        else "native_v2"
    )


def operation_warning_codes(operation: BrainDumpOperationDocument) -> list[str]:
    codes: list[str] = []
    if operation.legacy_import == "legacy_preview_only":
        codes.append("provisional_only")
    return codes
