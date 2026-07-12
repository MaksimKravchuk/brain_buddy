"""Execution module: evidence/result recording.

Implements ADR-0001 Execution module for manual evidence recording.
Task-tracker dispatch is deferred (no configured adapter in MVP).
"""

from .domain import EvidenceResult, EvidenceResultKind, EvidenceResultSource
from .repository import ExecutionRepository
from .service import ExecutionService

__all__ = [
    "EvidenceResult",
    "EvidenceResultKind",
    "EvidenceResultSource",
    "ExecutionRepository",
    "ExecutionService",
]
