"""Mock validation provider used for tests and offline workflows."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .base import ProviderContext, ProviderResult, ValidationProvider


@dataclass(slots=True)
class MockValidationProvider(ValidationProvider):
    """Return deterministic pseudo-random responses for validation requests."""

    provider_id: str = "mock"

    def validate(
        self,
        prompt: str,
        context: ProviderContext,
        *,
        config=None,
    ) -> ProviderResult:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        seed = int(digest[:8], 16)
        confidence = max(45, min(95, 50 + seed % 51))

        if confidence >= 85:
            verdict = "strong"
            severity = "info"
            assessment = "Links read as coherent; keep monitoring data quality."
        elif confidence >= 65:
            verdict = "uncertain"
            severity = "warning"
            assessment = "Reasoning mostly holds but clarify supporting evidence."
        else:
            verdict = "weak"
            severity = "error"
            assessment = "Causal link appears speculative; gather proof or reframe."

        link_index = 1 if context.chain_length else 0
        observations = [
            {
                "link_index": link_index,
                "assessment": assessment,
                "severity": severity,
            }
        ]

        suggestions: list[str] = []
        if severity != "info":
            suggestions.append(
                "What evidence confirms the stated cause directly affects the effect?"
            )
        if confidence < 80 and context.chain_length > 1:
            suggestions.append(
                "Can intermediate factors be documented to solidify this chain?"
            )

        raw = {
            "confidence": confidence,
            "verdict": verdict,
            "observations": observations,
            "suggested_questions": suggestions[:3],
        }

        return ProviderResult(
            confidence=confidence,
            verdict=verdict,
            observations=observations,
            suggested_questions=suggestions[:3],
            raw=raw,
        )
