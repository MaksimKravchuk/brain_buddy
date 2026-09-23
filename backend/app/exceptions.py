"""Custom exception hierarchy for Brain Buddy backend."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class BrainBuddyError(Exception):
    """Base class for application-specific exceptions."""


class NotFoundError(BrainBuddyError):
    """Raised when a requested resource cannot be located."""

    def __init__(self, resource: str, identifier: str) -> None:
        message = f"{resource} '{identifier}' was not found."
        super().__init__(message)
        self.resource = resource
        self.identifier = identifier


class ConflictError(BrainBuddyError):
    """Raised when a write operation conflicts with current resource state."""

    def __init__(
        self, resource: str, identifier: str, message: str | None = None
    ) -> None:
        super().__init__(message or f"{resource} '{identifier}' already exists.")
        self.resource = resource
        self.identifier = identifier


class IdempotencyConflictError(ConflictError):
    """Raised when a scoped idempotency key is reused for another request."""

    def __init__(self) -> None:
        super().__init__(
            "Idempotency-Key",
            "scoped",
            "The Idempotency-Key was reused with a different request.",
        )
        self.detail = {"reason": "idempotency_conflict"}


class IdempotencyReceiptExpiredError(ConflictError):
    """Raised when an exact-replay receipt is outside its retention window."""

    def __init__(self) -> None:
        super().__init__(
            "Idempotency receipt",
            "expired",
            "The idempotency receipt expired; refetch and explicitly reconcile.",
        )
        self.detail = {"reason": "idempotency_receipt_expired"}


class IdempotencyReceiptUnavailableError(ConflictError):
    """Raised when a committed receipt cannot safely reconstruct its response."""

    def __init__(self) -> None:
        super().__init__(
            "Idempotency receipt",
            "unavailable",
            "The idempotency receipt cannot be replayed safely.",
        )
        self.detail = {"reason": "idempotency_receipt_unavailable"}


class PendingCommandError(ConflictError):
    """Raised when another CRT command is pending for the same resource."""

    def __init__(self, resource_id: str) -> None:
        super().__init__(
            "CRT command",
            resource_id,
            "A prior CRT command is still pending reconciliation; retry later.",
        )
        self.detail = {"reason": "pending_command", "tree_id": resource_id}


class StaleRevisionError(ConflictError):
    """Raised when an owner supplied an older aggregate revision."""

    def __init__(
        self,
        resource: str,
        identifier: str,
        *,
        current_revision: int,
        current_updated_at: datetime,
    ) -> None:
        super().__init__(
            resource,
            identifier,
            "This tree has newer changes; review the conflict before saving.",
        )
        self.current_revision = current_revision
        self.current_updated_at = current_updated_at
        self.detail = {
            "reason": "stale_revision",
            "tree_id": identifier,
            "current_revision": current_revision,
            "current_updated_at": current_updated_at,
        }


class RepositoryError(BrainBuddyError):
    """Wrap lower-level IO or serialization failures."""


class StorageUnavailableError(RepositoryError):
    """Raised when the storage backend is temporarily unable to serve requests."""


class ReauthFailedError(BrainBuddyError):
    """Raised when a sensitive account action's password re-check fails.

    Mapped to 403 — deliberately not 401, because the frontend treats 401 as
    "session gone" and would clear local auth state mid-form.
    """

    def __init__(self) -> None:
        super().__init__("Current password is incorrect.")


class ValidationFailure(BrainBuddyError):
    """Raised when requested operation fails domain validation checks."""

    def __init__(
        self,
        message: str,
        detail: Any | None = None,
        *,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.detail = detail
        self.estimated_cost_usd = estimated_cost_usd


class AdminAuthorizationError(BrainBuddyError):
    """A permitted operator attempted a forbidden account mutation."""


class ProviderRetryableError(BrainBuddyError):
    """Raised by a provider port when a call fails but a retry may succeed."""

    def __init__(self, message: str, *, estimated_cost_usd: float = 0.0) -> None:
        super().__init__(message)
        self.estimated_cost_usd = estimated_cost_usd


class ProviderTerminalError(BrainBuddyError):
    """Raised by a provider port when a call fails in a way retries cannot fix."""

    def __init__(self, message: str, *, estimated_cost_usd: float = 0.0) -> None:
        super().__init__(message)
        self.estimated_cost_usd = estimated_cost_usd


__all__ = [
    "AdminAuthorizationError",
    "BrainBuddyError",
    "ConflictError",
    "IdempotencyConflictError",
    "IdempotencyReceiptExpiredError",
    "IdempotencyReceiptUnavailableError",
    "NotFoundError",
    "ProviderRetryableError",
    "ProviderTerminalError",
    "PendingCommandError",
    "ReauthFailedError",
    "RepositoryError",
    "StorageUnavailableError",
    "StaleRevisionError",
    "ValidationFailure",
]
