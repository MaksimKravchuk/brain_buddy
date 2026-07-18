"""Voice Brain Dump schema-v2 workflow contracts."""

from .domain import (
    ProposalConflict,
    ProposalPatch,
    ProposalProjection,
    ReconciledProposal,
    TranscriptHypothesis,
    active_transcript_hypotheses,
    apply_proposal_patches,
)
from .providers import (
    AccurateSttPort,
    AccurateSttRequest,
    DeterministicAccurateStt,
    DeterministicFastStt,
    DeterministicTextReconciler,
    FastSttPort,
    FastSttRequest,
    ReconcileTextRequest,
    TextReconcilerPort,
)

__all__ = [
    "AccurateSttPort",
    "AccurateSttRequest",
    "DeterministicAccurateStt",
    "DeterministicFastStt",
    "DeterministicTextReconciler",
    "FastSttPort",
    "FastSttRequest",
    "ProposalConflict",
    "ProposalPatch",
    "ProposalProjection",
    "ReconcileTextRequest",
    "ReconciledProposal",
    "TextReconcilerPort",
    "TranscriptHypothesis",
    "active_transcript_hypotheses",
    "apply_proposal_patches",
]
