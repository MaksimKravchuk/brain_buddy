"""Validation service orchestrating provider calls and persistence."""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.ai.prompts import ValidationPrompt, build_validation_prompt
from app.ai.providers import (
    MockValidationProvider,
    OpenAIValidationProvider,
    ProviderContext,
    ProviderResult,
    ValidationProvider,
)
from app.exceptions import NotFoundError, ValidationFailure
from app.repositories import ProviderRepository, TreeRepository, ValidationRepository
from app.schemas import ValidationRequest, ValidationResponse
from app.schemas.common import ValidationState
from app.schemas.domain import TreeDocument, ValidationEntry
from app.services.tree_service import TreeService
from app.utils.time import utcnow


class ValidationService:
    """Coordinate validation prompt generation, provider execution, and persistence."""

    def __init__(
        self,
        tree_repo: TreeRepository,
        tree_service: TreeService,
        validation_repo: ValidationRepository,
        provider_repo: ProviderRepository,
        providers: dict[str, ValidationProvider] | None = None,
        default_provider_id: str = "mock",
    ) -> None:
        self.tree_repo = tree_repo
        self.tree_service = tree_service
        self.validation_repo = validation_repo
        self.provider_repo = provider_repo
        self.providers = providers or {
            "mock": MockValidationProvider(),
            "openai": OpenAIValidationProvider(),
        }
        self.default_provider_id = default_provider_id

    def trigger_validation(
        self, tree_id: str, node_id: str, payload: ValidationRequest
    ) -> ValidationResponse:
        tree = self.tree_repo.load(tree_id)
        self._resolve_node(tree, node_id)

        prompt = self._build_prompt(tree, node_id)
        provider_id, provider_config = self._determine_provider(payload.provider)
        provider = self._get_provider(provider_id)
        context = ProviderContext(
            tree_id=tree_id,
            node_id=node_id,
            prompt_version=prompt.prompt_version,
            chain_length=len(prompt.steps),
        )

        result = provider.validate(
            prompt.prompt, context=context, config=provider_config
        )
        confidence = max(0, min(100, int(result.confidence)))
        summary = self._summarize_result(result)

        checked_at = utcnow()
        validation_state = ValidationState(
            confidence=confidence, provider=provider_id, last_checked=checked_at
        )
        entry = ValidationEntry(
            confidence=confidence,
            summary=summary,
            provider=provider_id,
            prompt_hash=self._hash_prompt(prompt),
            checked_at=checked_at,
            raw_response=result.raw,
        )

        self.validation_repo.append_entry(tree_id, node_id, entry)

        def apply_validation(current: TreeDocument) -> TreeDocument:
            _, index = self._resolve_node(current, node_id)
            return self._update_node_validation(
                current, index, validation_state, checked_at
            )

        self.tree_service.mutate_tree(
            tree_id, apply_validation, timestamp=checked_at
        )

        return ValidationResponse(
            node_id=node_id,
            provider=provider_id,
            confidence=confidence,
            summary=summary,
            checked_at=checked_at,
        )

    def get_history(self, tree_id: str, node_id: str) -> list[ValidationEntry]:
        return self.validation_repo.load_history(tree_id, node_id)

    def _resolve_node(self, tree: TreeDocument, node_id: str):
        for index, candidate in enumerate(tree.nodes):
            if candidate.id == node_id:
                return candidate, index
        raise NotFoundError("Node", node_id)

    def _determine_provider(self, requested_id: str | None):
        registry = self.provider_repo.load()
        provider_id = (
            requested_id or registry.default_provider or self.default_provider_id
        )
        provider_config = registry.providers.get(provider_id)
        if provider_id not in self.providers:
            raise ValidationFailure(f"Provider '{provider_id}' is not supported.")
        return provider_id, provider_config

    def _get_provider(self, provider_id: str) -> ValidationProvider:
        return self.providers[provider_id]

    def _build_prompt(self, tree: TreeDocument, node_id: str) -> ValidationPrompt:
        try:
            return build_validation_prompt(tree, node_id)
        except KeyError as exc:  # pragma: no cover - guarded by _resolve_node
            raise NotFoundError("Node", node_id) from exc

    def _update_node_validation(
        self,
        tree: TreeDocument,
        node_index: int,
        state: ValidationState,
        timestamp: datetime,
    ) -> TreeDocument:
        node = tree.nodes[node_index]
        metadata = node.metadata.model_copy(update={"updated_at": timestamp})
        updated_node = node.model_copy(
            update={"validation": state, "metadata": metadata}
        )
        nodes = list(tree.nodes)
        nodes[node_index] = updated_node
        return tree.model_copy(update={"nodes": nodes})

    def _summarize_result(self, result: ProviderResult) -> str:
        verdict = result.verdict.capitalize()
        if result.observations:
            assessment = str(result.observations[0].get("assessment", ""))
            if assessment:
                return f"{verdict}: {assessment}"
        return verdict

    def _hash_prompt(self, prompt: ValidationPrompt) -> str:
        digest = hashlib.sha256(prompt.prompt.encode("utf-8")).hexdigest()
        return digest[:32]
