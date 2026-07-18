"""Pure schema-v2 transcript/proposal projection rules for Voice Brain Dump."""

from __future__ import annotations

from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from typing import Any, Literal

from app.exceptions import ValidationFailure

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
            raise ValidationFailure("Transcript hypothesis requires a positive audio span.")
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
        key=lambda segment: (segment.start_ms, segment.end_ms, segment.sequence, segment.id),
    )


def apply_proposal_patches(
    base: list[ReconciledProposal], patches: list[ProposalPatch]
) -> ProposalProjection:
    """Project append-only patches while preserving user locks and tombstone history."""

    by_id = {proposal.id: proposal for proposal in base}
    order = [proposal.id for proposal in base]
    history: dict[str, ReconciledProposal] = dict(by_id)

    for patch in patches:
        if patch.operation in {"add", "merge", "split"}:
            if patch.title is None:
                raise ValidationFailure("Proposal add/split/merge requires a title.")
            for predecessor_id in patch.predecessor_ids:
                predecessor = by_id.get(predecessor_id)
                if predecessor is not None:
                    successor_ids = sorted({*predecessor.successor_ids, patch.proposal_id})
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
                status="reconciled" if patch.producer == "reconciler" else "provisional",
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

        if patch.operation in {"remove", "supersede"}:
            updated = _replace(
                current, tombstoned=True, revision=current.revision + 1
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
        elif "title" in current.locked_fields and patch.title and patch.title != current.title:
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

    active = [by_id[item_id] for item_id in order if item_id in by_id and not by_id[item_id].tombstoned]
    active.sort(key=lambda proposal: (proposal.ordinal, proposal.id))
    active = [_replace(proposal, ordinal=index + 1) for index, proposal in enumerate(active)]
    return ProposalProjection(active=active, history=list(history.values()), patches=patches)


def _insertion_ordinal(
    by_id: dict[str, ReconciledProposal], order: list[str], predecessor_ids: list[str]
) -> int:
    predecessor_ordinals = [by_id[item_id].ordinal for item_id in predecessor_ids if item_id in by_id]
    if predecessor_ordinals:
        return min(predecessor_ordinals)
    return len([proposal for proposal in by_id.values() if not proposal.tombstoned]) + 1


def _replace(proposal: ReconciledProposal, **updates: Any) -> ReconciledProposal:
    return replace(proposal, **updates)
