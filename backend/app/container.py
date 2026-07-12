"""Lightweight dependency container for application services."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.providers import MockValidationProvider, OpenAIValidationProvider
from app.core.config import AppConfig
from app.modules.capture import CaptureRepository, CaptureService
from app.modules.execution import ExecutionRepository, ExecutionService
from app.modules.review import ReviewRepository, ReviewService
from app.modules.thinking import ThinkingRepository, ThinkingService
from app.repositories import (
    IndexRepository,
    InviteRepository,
    ProviderRepository,
    SessionRepository,
    TreeRepository,
    UserRepository,
    ValidationRepository,
    VersionRepository,
)
from app.services import (
    AuthService,
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
    user_repo: UserRepository
    session_repo: SessionRepository
    invite_repo: InviteRepository
    capture_repo: CaptureRepository
    review_repo: ReviewRepository
    thinking_repo: ThinkingRepository
    execution_repo: ExecutionRepository
    tree_service: TreeService
    node_service: NodeService
    relation_service: RelationService
    version_service: VersionService
    validation_service: ValidationService
    auth_service: AuthService
    capture_service: CaptureService
    review_service: ReviewService
    thinking_service: ThinkingService
    execution_service: ExecutionService


def build_container(config: AppConfig) -> Container:
    data_root = config.data_dir
    tree_repo = TreeRepository(data_root)
    index_repo = IndexRepository(data_root)
    version_repo = VersionRepository(data_root)
    validation_repo = ValidationRepository(data_root)
    provider_repo = ProviderRepository(data_root)
    user_repo = UserRepository(data_root)
    session_repo = SessionRepository(data_root)
    invite_repo = InviteRepository(data_root)

    capture_repo = CaptureRepository(data_root)
    review_repo = ReviewRepository(data_root)
    thinking_repo = ThinkingRepository(data_root)
    execution_repo = ExecutionRepository(data_root)

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
    auth_service = AuthService(
        user_repo=user_repo,
        session_repo=session_repo,
        invite_repo=invite_repo,
        password_policy=config.password_policy,
        session_settings=config.session,
    )
    capture_service = CaptureService(capture_repo)
    review_service = ReviewService(review_repo)
    thinking_service = ThinkingService(thinking_repo, tree_service, node_service)
    execution_service = ExecutionService(execution_repo)

    return Container(
        tree_repo=tree_repo,
        index_repo=index_repo,
        version_repo=version_repo,
        validation_repo=validation_repo,
        provider_repo=provider_repo,
        user_repo=user_repo,
        session_repo=session_repo,
        invite_repo=invite_repo,
        capture_repo=capture_repo,
        review_repo=review_repo,
        thinking_repo=thinking_repo,
        execution_repo=execution_repo,
        tree_service=tree_service,
        node_service=node_service,
        relation_service=relation_service,
        version_service=version_service,
        validation_service=validation_service,
        auth_service=auth_service,
        capture_service=capture_service,
        review_service=review_service,
        thinking_service=thinking_service,
        execution_service=execution_service,
    )
