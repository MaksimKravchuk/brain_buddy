"""Voice Brain Dump schema-v2 workflow contracts."""

from .confirmation import ConfirmedAction, confirm_native_inbox_actions
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
from .service import VoiceBrainDumpService
from .task_port import InProcessTaskPort, TaskPort

__all__ = [
    "AccurateSttPort",
    "AccurateSttRequest",
    "ConfirmedAction",
    "DeterministicAccurateStt",
    "DeterministicFastStt",
    "DeterministicTextReconciler",
    "FastSttPort",
    "FastSttRequest",
    "InProcessTaskPort",
    "ProposalConflict",
    "ProposalPatch",
    "ProposalProjection",
    "ReconcileTextRequest",
    "ReconciledProposal",
    "TaskPort",
    "TextReconcilerPort",
    "TranscriptHypothesis",
    "VoiceBrainDumpService",
    "active_transcript_hypotheses",
    "apply_proposal_patches",
    "confirm_native_inbox_actions",
]
