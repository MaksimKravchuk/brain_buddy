"""Custom exception hierarchy for Brain Buddy backend."""

from __future__ import annotations

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


class RepositoryError(BrainBuddyError):
    """Wrap lower-level IO or serialization failures."""


class StorageUnavailableError(RepositoryError):
    """Raised when the storage backend is temporarily unable to serve requests."""


class ValidationFailure(BrainBuddyError):
    """Raised when requested operation fails domain validation checks."""

    def __init__(self, message: str, detail: Any | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class ProviderRetryableError(BrainBuddyError):
    """Raised by a provider port when a call fails but a retry may succeed."""


class ProviderTerminalError(BrainBuddyError):
    """Raised by a provider port when a call fails in a way retries cannot fix."""


__all__ = [
    "BrainBuddyError",
    "ConflictError",
    "NotFoundError",
    "ProviderRetryableError",
    "ProviderTerminalError",
    "RepositoryError",
    "StorageUnavailableError",
    "ValidationFailure",
]
