"""Lightweight dependency container for application services."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from app.ai.providers import MockValidationProvider, OpenAIValidationProvider
from app.core.config import AppConfig, AppEnvironment
from app.modules.tasks import TaskRepository, TaskService
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
from app.workflows.voice_brain_dump.adapters import (
    OpenAiAccurateStt,
    OpenAITextReconciler,
)
from app.workflows.voice_brain_dump.providers import (
    AccurateSttPort,
    DeterministicAccurateStt,
    DeterministicTextReconciler,
    DisabledAccurateStt,
    DisabledTextReconciler,
    TextReconcilerPort,
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
    task_repo: TaskRepository
    tree_service: TreeService
    node_service: NodeService
    relation_service: RelationService
    version_service: VersionService
    validation_service: ValidationService
    auth_service: AuthService
    task_service: TaskService


def _build_accurate_stt(config: AppConfig) -> AccurateSttPort:
    settings = config.voice.accurate_stt
    if settings.provider == "deterministic":
        return DeterministicAccurateStt(allow_text_fixture_audio=True)
    if settings.provider == "openai":
        api_key = os.getenv(settings.api_key_env)
        if not api_key:
            return DisabledAccurateStt("STT_PROVIDER_CREDENTIALS_MISSING")
        return OpenAiAccurateStt(
            api_key=api_key,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
            retry_backoff_seconds=settings.retry_backoff_seconds,
            max_cost_usd_per_operation=settings.max_cost_usd_per_operation,
            estimated_cost_usd_per_megabyte=settings.estimated_cost_usd_per_megabyte,
        )
    if settings.provider == "disabled":
        return DisabledAccurateStt()
    return DisabledAccurateStt("STT_PROVIDER_UNSUPPORTED")


def _build_text_reconciler(config: AppConfig) -> TextReconcilerPort:
    settings = config.voice.reconciler
    if config.environment is AppEnvironment.TEST:
        return DeterministicTextReconciler()
    if settings.provider == "openai":
        api_key = os.getenv(settings.api_key_env)
        if not api_key:
            return DisabledTextReconciler()
        return OpenAITextReconciler(
            api_key=api_key,
            model=settings.model,
            endpoint=settings.endpoint,
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
            retry_backoff_seconds=settings.retry_backoff_seconds,
            max_cost_usd_per_operation=settings.max_cost_usd_per_operation,
            estimated_cost_usd_per_megabyte=settings.estimated_cost_usd_per_megabyte,
        )
    return DisabledTextReconciler()


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
    task_repo = TaskRepository(data_root)

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
    task_service = TaskService(
        task_repo,
        accurate_stt=_build_accurate_stt(config),
        text_reconciler=_build_text_reconciler(config),
        raw_audio_retention=timedelta(seconds=config.voice.retention.raw_audio_seconds),
    )
    auth_service = AuthService(
        user_repo=user_repo,
        session_repo=session_repo,
        invite_repo=invite_repo,
        password_policy=config.password_policy,
        session_settings=config.session,
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
        task_repo=task_repo,
        tree_service=tree_service,
        node_service=node_service,
        relation_service=relation_service,
        version_service=version_service,
        validation_service=validation_service,
        auth_service=auth_service,
        task_service=task_service,
    )
