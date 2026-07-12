"""Lightweight dependency container for application services."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.providers import MockValidationProvider, OpenAIValidationProvider
from app.core.config import AppConfig
from app.modules.capture.repository import CaptureRepository
from app.modules.capture.service import CaptureService
from app.modules.execution.repository import ExecutionRepository
from app.modules.execution.service import ExecutionService
from app.modules.organize.repository import OrganizeRepository
from app.modules.organize.service import OrganizeService
from app.modules.thinking.repository import PromotionRepository, ThinkingRepository
from app.modules.thinking.service import ThinkingService
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
from app.workflows.capture_review import CaptureReviewWorkflow


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
    organize_repo: OrganizeRepository
    thinking_repo: ThinkingRepository
    promotion_repo: PromotionRepository
    execution_repo: ExecutionRepository
    tree_service: TreeService
    node_service: NodeService
    relation_service: RelationService
    version_service: VersionService
    validation_service: ValidationService
    auth_service: AuthService
    capture_service: CaptureService
    organize_service: OrganizeService
    thinking_service: ThinkingService
    execution_service: ExecutionService
    capture_review_workflow: CaptureReviewWorkflow


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

    # vNext module repositories
    capture_repo = CaptureRepository(data_root / "captures")
    organize_repo = OrganizeRepository(data_root / "organize")
    thinking_repo = ThinkingRepository(data_root / "candidates")
    promotion_repo = PromotionRepository(data_root / "promotions")
    execution_repo = ExecutionRepository(data_root / "dispatches")

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

    # vNext module services
    capture_service = CaptureService(capture_repo)
    organize_service = OrganizeService(organize_repo)
    thinking_service = ThinkingService(thinking_repo, promotion_repo)
    execution_service = ExecutionService(execution_repo, organize_repo)

    capture_review_workflow = CaptureReviewWorkflow(
        capture_service=capture_service,
        organize_service=organize_service,
        execution_service=execution_service,
        thinking_service=thinking_service,
    )

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
        organize_repo=organize_repo,
        thinking_repo=thinking_repo,
        promotion_repo=promotion_repo,
        execution_repo=execution_repo,
        tree_service=tree_service,
        node_service=node_service,
        relation_service=relation_service,
        version_service=version_service,
        validation_service=validation_service,
        auth_service=auth_service,
        capture_service=capture_service,
        organize_service=organize_service,
        thinking_service=thinking_service,
        execution_service=execution_service,
        capture_review_workflow=capture_review_workflow,
    )
