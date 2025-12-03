"""Custom exception hierarchy for Brain Buddy backend."""

from __future__ import annotations


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
    """Raised when a write operation would violate uniqueness constraints."""

    def __init__(self, resource: str, identifier: str) -> None:
        message = f"{resource} '{identifier}' already exists."
        super().__init__(message)
        self.resource = resource
        self.identifier = identifier


class RepositoryError(BrainBuddyError):
    """Wrap lower-level IO or serialization failures."""


class ValidationFailure(BrainBuddyError):
    """Raised when requested operation fails domain validation checks."""


__all__ = [
    "BrainBuddyError",
    "ConflictError",
    "NotFoundError",
    "RepositoryError",
    "ValidationFailure",
]
