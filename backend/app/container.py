"""Lightweight dependency container for application services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.ai.providers import MockValidationProvider, OpenAIValidationProvider
from app.repositories import (
    IndexRepository,
    ProviderRepository,
    TreeRepository,
    ValidationRepository,
    VersionRepository,
)
from app.services import (
    NodeService,
    RelationService,
    TreeService,
    ValidationService,
    VersionService,
)


@dataclass(slots=True)
class Container:
    """Aggregate repositories and services for dependency wiring."""

    tree_repo: TreeRepository
    index_repo: IndexRepository
    version_repo: VersionRepository
    validation_repo: ValidationRepository
    provider_repo: ProviderRepository
    tree_service: TreeService
    node_service: NodeService
    relation_service: RelationService
    version_service: VersionService
    validation_service: ValidationService


def build_container(data_root: Path) -> Container:
    tree_repo = TreeRepository(data_root)
    index_repo = IndexRepository(data_root)
    version_repo = VersionRepository(data_root)
    validation_repo = ValidationRepository(data_root)
    provider_repo = ProviderRepository(data_root)

    tree_service = TreeService(tree_repo, index_repo)
    node_service = NodeService(tree_repo, tree_service)
    relation_service = RelationService(tree_repo, tree_service)
    version_service = VersionService(tree_repo, version_repo, tree_service)
    validation_service = ValidationService(
        tree_repo=tree_repo,
        tree_service=tree_service,
        validation_repo=validation_repo,
        provider_repo=provider_repo,
        providers={
            "mock": MockValidationProvider(),
            "openai": OpenAIValidationProvider(),
        },
    )

    return Container(
        tree_repo=tree_repo,
        index_repo=index_repo,
        version_repo=version_repo,
        validation_repo=validation_repo,
        provider_repo=provider_repo,
        tree_service=tree_service,
        node_service=node_service,
        relation_service=relation_service,
        version_service=version_service,
        validation_service=validation_service,
    )
