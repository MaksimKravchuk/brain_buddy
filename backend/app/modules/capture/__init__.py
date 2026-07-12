"""Capture module: immutable source captures and mutable capture items.

Owns AtomicCaptureSource (immutable) and CaptureItem (mutable) records,
plus CaptureSession for text-based input. Voice/async operations are
deferred to ADR-0002 implementation.
"""

from .domain import (
    AtomicCaptureSource,
    CaptureItem,
    CaptureItemState,
    CaptureKind,
    CaptureSession,
    CaptureSessionStatus,
)
from .repository import CaptureRepository
from .service import CaptureService

__all__ = [
    "AtomicCaptureSource",
    "CaptureItem",
    "CaptureItemState",
    "CaptureKind",
    "CaptureRepository",
    "CaptureService",
    "CaptureSession",
    "CaptureSessionStatus",
]
