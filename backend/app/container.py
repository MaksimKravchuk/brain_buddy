"""Lightweight dependency container for application services."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from app.ai.providers import MockValidationProvider, OpenAIValidationProvider
from app.ai.task_tracker import FakeTaskTrackerAdapter, TaskTrackerAdapter
from app.ai.transcription import MockTranscriptionProvider, TranscriptionProvider
from app.core.config import AppConfig
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
from app.repositories.brain_dump import BrainDumpRepository
from app.services import (
    AuthService,
    NodeService,
    RelationService,
    TreeService,
    ValidationService,
    VersionService,
)
from app.services.brain_dump_service import BrainDumpService

logger = logging.getLogger(__name__)


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
    tree_service: TreeService
    node_service: NodeService
    relation_service: RelationService
    version_service: VersionService
    validation_service: ValidationService
    auth_service: AuthService
    brain_dump_repo: BrainDumpRepository
    brain_dump_service: BrainDumpService


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
    brain_dump_repo = BrainDumpRepository(data_root)

    # Production providers: use real OpenAI Whisper + RTM REST when
    # credentials are present. Fall back to mock/fake with a warning so
    # the app still runs in dev/test. This is the explicit integration
    # boundary — we never fake production voice or RTM behaviour.
    from app.ai.task_tracker import RTMRestAdapter
    from app.ai.transcription import OpenAITranscriptionProvider

    openai_key = os.getenv("BRAIN_BUDDY_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    rtm_key = os.getenv("RTM_API_KEY")
    rtm_secret = os.getenv("RTM_SHARED_SECRET")

    transcription_provider: TranscriptionProvider
    if openai_key:
        transcription_provider = OpenAITranscriptionProvider(api_key=openai_key)
        logger.info("Brain Dump: using OpenAI Whisper transcription provider")
    else:
        transcription_provider = MockTranscriptionProvider()
        logger.warning(
            "Brain Dump: OPENAI_API_KEY not set — using mock transcription. "
            "Set OPENAI_API_KEY or BRAIN_BUDDY_OPENAI_API_KEY for production."
        )

    task_tracker: TaskTrackerAdapter
    if rtm_key and rtm_secret:
        task_tracker = RTMRestAdapter(api_key=rtm_key, shared_secret=rtm_secret)
        logger.info("Brain Dump: using RTM REST adapter for task export")
    else:
        task_tracker = FakeTaskTrackerAdapter()
        logger.warning(
            "Brain Dump: RTM_API_KEY/RTM_SHARED_SECRET not set — using fake "
            "task tracker. Set both for production RTM Inbox export."
        )

    brain_dump_service = BrainDumpService(
        repo=brain_dump_repo,
        transcription_provider=transcription_provider,
        task_tracker=task_tracker,
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
        tree_service=tree_service,
        node_service=node_service,
        relation_service=relation_service,
        version_service=version_service,
        validation_service=validation_service,
        auth_service=auth_service,
        brain_dump_repo=brain_dump_repo,
        brain_dump_service=brain_dump_service,
    )
