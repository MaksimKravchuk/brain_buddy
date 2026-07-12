"""Thinking/CRT module: problem candidates and CRT promotion.

Implements ADR-0001 Thinking module: assess candidates, promote/dismiss,
query source/results. Promotion wraps the existing TreeService to create
a CRT tree and initial node.
"""

from .domain import (
    CrtPromotion,
    ProblemCandidate,
    ProblemCandidateSignal,
    ProblemCandidateStatus,
    PromotionStatus,
)
from .repository import ThinkingRepository
from .service import ThinkingService

__all__ = [
    "CrtPromotion",
    "ProblemCandidate",
    "ProblemCandidateSignal",
    "ProblemCandidateStatus",
    "PromotionStatus",
    "ThinkingRepository",
    "ThinkingService",
]
