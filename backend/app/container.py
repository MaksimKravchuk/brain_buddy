"""Lightweight dependency container for application services."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from app.ai.providers import MockValidationProvider, OpenAIValidationProvider
from app.core.config import AppConfig, AppEnvironment, VoiceProviderSettings
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
    AccountService,
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
from app.workflows.voice_brain_dump.adapters.deepgram_stt import DeepgramAccurateStt
from app.workflows.voice_brain_dump.providers import (
    AccurateSttPort,
    DeterministicAccurateStt,
    DeterministicTextReconciler,
    DisabledAccurateStt,
    DisabledTextReconciler,
    TextReconcilerPort,
)
from app.workflows.voice_brain_dump.repository import OperationRepository
from app.workflows.voice_brain_dump.service import VoiceBrainDumpService
from app.workflows.voice_brain_dump.task_port import InProcessTaskPort


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
    voice_operation_repo: OperationRepository
    tree_service: TreeService
    node_service: NodeService
    relation_service: RelationService
    version_service: VersionService
    validation_service: ValidationService
    auth_service: AuthService
    account_service: AccountService
    task_service: TaskService
    voice_brain_dump_service: VoiceBrainDumpService


def _build_accurate_stt(config: AppConfig) -> AccurateSttPort:
    settings = config.voice.accurate_stt
    if settings.provider == "deterministic":
        if config.environment is not AppEnvironment.TEST:
            return DisabledAccurateStt("STT_DETERMINISTIC_PROVIDER_TEST_ONLY")
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
    if settings.provider == "deepgram":
        api_key = os.getenv(settings.api_key_env)
        if not api_key:
            return DisabledAccurateStt("STT_PROVIDER_CREDENTIALS_MISSING")
        return DeepgramAccurateStt(
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


def _worst_case_provider_seconds(settings: VoiceProviderSettings) -> float:
    """Worst-case wall-clock time one logical call may occupy a lease.

    ``max_retries + 1`` attempts, each up to ``timeout_seconds``, plus every
    backoff wait between them (the schedule repeats its last value past its
    own length, matching the adapters' own ``_backoff`` behavior).
    """

    attempts = settings.max_retries + 1
    backoff_total = sum(
        settings.retry_backoff_seconds[
            min(index, len(settings.retry_backoff_seconds) - 1)
        ]
        for index in range(settings.max_retries)
    )
    return attempts * settings.timeout_seconds + backoff_total


def _provider_run_lease_seconds(config: AppConfig) -> float:
    """Persisted recovery lease duration for one accurate-STT/reconciler run.

    Must cover the configured provider timeout, its bounded retry/backoff
    schedule, and a safe margin for both roles (whichever is larger) so a
    still-valid ongoing call is never recovered/retried early.
    """

    worst_case = max(
        _worst_case_provider_seconds(config.voice.accurate_stt),
        _worst_case_provider_seconds(config.voice.reconciler),
    )
    return worst_case + config.voice.lease_recovery_margin_seconds


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


def _allowed_external_provider_categories(config: AppConfig) -> frozenset[str]:
    """The provider categories consent may name, per configuration.

    Each configured role contributes its verbatim category string (``openai`` /
    ``deepgram`` / ``deterministic``) so consent driven by the discovery endpoint
    -- which reports those same config strings -- clears the pre-upload guard. A
    ``disabled`` role contributes nothing. ``deterministic`` additionally admits
    ``openai`` for backward compatibility with legacy single-provider clients
    (and older tests) that named ``openai`` for a deterministic stack before the
    discovery endpoint reported the category honestly. This only widens the set
    of *nameable* categories; the actual egress guard
    (``_required_external_provider_categories`` derived from the wired adapters'
    ``requires_external_processing``) is unchanged, so no unconsented vendor can
    receive data.
    """

    allowed: set[str] = set()
    for provider in (
        config.voice.accurate_stt.provider,
        config.voice.reconciler.provider,
    ):
        if provider == "disabled":
            continue
        allowed.add(provider)
        if provider == "deterministic":
            allowed.add("openai")
    return frozenset(allowed)


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
    voice_operation_repo = OperationRepository(data_root)

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
    task_service = TaskService(task_repo)

    def _voice_enabled_for_owner(owner_id: str) -> bool:
        """Whether ``voice_brain_dump`` is effective for the operation's owner.

        Used by the background runner so external provider work never advances
        for an owner whose exposure flag is OFF. A missing user fails closed.
        """

        user = user_repo.get_by_id(owner_id)
        if user is None:
            return False
        return config.feature_flags.effective_flags(user.email).get(
            "voice_brain_dump", False
        )

    voice_brain_dump_service = VoiceBrainDumpService(
        voice_operation_repo,
        accurate_stt=_build_accurate_stt(config),
        text_reconciler=_build_text_reconciler(config),
        raw_audio_retention=timedelta(seconds=config.voice.retention.raw_audio_seconds),
        working_artifacts_retention=timedelta(
            seconds=config.voice.retention.working_artifacts_seconds
        ),
        max_operation_recoveries=config.voice.max_operation_recoveries,
        max_cumulative_cost_usd_per_operation=(
            config.voice.max_cumulative_cost_usd_per_operation
        ),
        provider_run_lease_seconds=_provider_run_lease_seconds(config),
        allowed_external_provider_categories=_allowed_external_provider_categories(config),
        audio_limits=config.voice.audio_limits,
        task_port=InProcessTaskPort(task_service.create_native_inbox_task),
        voice_enabled_for_owner=_voice_enabled_for_owner,
    )
    auth_service = AuthService(
        user_repo=user_repo,
        session_repo=session_repo,
        invite_repo=invite_repo,
        password_policy=config.password_policy,
        session_settings=config.session,
    )
    account_service = AccountService(
        user_repo=user_repo,
        session_repo=session_repo,
        auth_service=auth_service,
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
        voice_operation_repo=voice_operation_repo,
        tree_service=tree_service,
        node_service=node_service,
        relation_service=relation_service,
        version_service=version_service,
        validation_service=validation_service,
        auth_service=auth_service,
        account_service=account_service,
        task_service=task_service,
        voice_brain_dump_service=voice_brain_dump_service,
    )
