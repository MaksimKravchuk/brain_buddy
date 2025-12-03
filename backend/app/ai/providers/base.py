"""Base interfaces for validation providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.schemas.domain import ProviderConfig


@dataclass(slots=True)
class ProviderContext:
    """Contextual information supplied to providers for each validation call."""

    tree_id: str
    node_id: str
    prompt_version: str
    chain_length: int


@dataclass(slots=True)
class ProviderResult:
    """Structured provider output returned to the validation service."""

    confidence: int
    verdict: str
    observations: list[dict]
    suggested_questions: list[str]
    raw: dict


class ValidationProvider(Protocol):
    """Protocol describing validation provider behaviour."""

    provider_id: str

    def validate(
        self,
        prompt: str,
        context: ProviderContext,
        *,
        config: ProviderConfig | None = None,
    ) -> ProviderResult:
        """Execute the validation request and return structured result."""
        ...
