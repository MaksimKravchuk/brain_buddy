"""Lightweight dependency container for application services."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Never

from app.ai.providers import MockValidationProvider, OpenAIValidationProvider
from app.ai.title_completion import build_title_completion_provider
from app.core.config import (
    AppConfig,
    AppEnvironment,
    VoiceProviderSettings,
)
from app.modules.agents.a2a.card import fetch_card
from app.modules.agents.a2a.client import A2AClient
from app.modules.agents.observer import AgentObserver
from app.modules.agents.repository import AgentRepository
from app.modules.agents.secrets import (
    SealedSecret,
    SecretBox,
    SecretsUnavailable,
    build_secret_box,
)
from app.modules.agents.service import (
    AgentRelayService,
    ExchangePolicy,
    TaskSnapshot,
)
from app.modules.tasks import TaskRepository, TaskService
from app.modules.tasks.autocomplete import TaskTitleAutocompleteService
from app.repositories import (
    FeatureFlagOverrideRepository,
    IndexRepository,
    InviteRepository,
    ProviderRepository,
    SessionRepository,
    TreeRepository,
    UserRepository,
    ValidationRepository,
    VersionRepository,
)
from app.repositories.feature_flag import FlagMode
from app.services import (
    AccountService,
    AdminService,
    AuthService,
    FeatureFlagService,
    NodeService,
    RelationService,
    TreeService,
    ValidationService,
    VersionService,
)
from app.services.auth_service import ACCOUNT_DELETION_GRACE
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
    agent_repo: AgentRepository
    feature_flag_repo: FeatureFlagOverrideRepository
    tree_service: TreeService
    node_service: NodeService
    relation_service: RelationService
    version_service: VersionService
    validation_service: ValidationService
    auth_service: AuthService
    account_service: AccountService
    admin_service: AdminService
    feature_flag_service: FeatureFlagService
    task_service: TaskService
    voice_brain_dump_service: VoiceBrainDumpService
    agent_relay_service: AgentRelayService
    agent_observer: AgentObserver
    task_title_autocomplete_service: TaskTitleAutocompleteService


class _UnavailableRelaySecretBox(SecretBox):
    """Fail-closed placeholder for a dark, empty production relay."""

    def __init__(self) -> None:
        # Deliberately do not generate, persist, or accept key material.
        pass

    def __repr__(self) -> str:
        return "UnavailableRelaySecretBox()"

    @staticmethod
    def _raise() -> Never:
        raise SecretsUnavailable(
            "BRAIN_BUDDY_AGENT_RELAY_KEYS is required before relay data can be used."
        )

    @property
    def active_key_id(self) -> str:
        self._raise()

    def seal(self, plaintext: str, *, aad: str) -> SealedSecret:
        self._raise()

    def fingerprint(self, message: str) -> str:
        self._raise()

    def fingerprint_candidates(self, message: str) -> list[str]:
        self._raise()

    def fingerprint_matches(self, stored: str, message: str) -> bool:
        self._raise()

    def open(self, sealed: SealedSecret, *, aad: str) -> str:
        self._raise()


def _build_agent_secret_box(
    config: AppConfig,
    repo: AgentRepository,
    feature_flag_repo: FeatureFlagOverrideRepository,
) -> SecretBox:
    """Decide, once at construction, whether the placeholder secret box is safe.

    DD-16: the relay's *rollout* mode now lives in SQLite, not the retired
    environment baseline. A degraded read (corrupt or locked store) fails
    closed for rollout, exactly like a healthy row explicitly OFF — every
    managed flag is ineffective and every mutation refused either way — so it
    is treated the same as a confirmed-OFF read for the placeholder shortcut.
    Degraded can never *waive* the key requirement, though: when relay data
    already exists on disk, inbound events reached it without being
    flag-gated, so those persisted credentials must stay decryptable — real
    keys are required regardless of what the flag store says.
    """

    raw_keys = os.getenv("BRAIN_BUDDY_AGENT_RELAY_KEYS")
    overlay = feature_flag_repo.read()
    relay_entry = overlay.flags.get("external_agent_relay")
    relay_effectively_off_fail_closed = overlay.degraded or (
        relay_entry is not None and relay_entry.mode is FlagMode.OFF
    )
    if (
        config.environment is AppEnvironment.PRODUCTION
        and not (raw_keys or "").strip()
        and relay_effectively_off_fail_closed
        and not repo.has_any_relay_data()
    ):
        return _UnavailableRelaySecretBox()
    return build_secret_box(raw_keys, environment=config.environment)


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
    agent_repo = AgentRepository(data_root)

    def _resolve_account_id_by_email(email: str) -> str | None:
        """Migration-only lookup: an email that does not resolve is skipped,
        never substituted (DD-15)."""

        account = user_repo.get_by_email(email)
        return account.id if account is not None else None

    feature_flag_repo = FeatureFlagOverrideRepository(
        data_root,
        # A callback, not a value: the deploy-staged managed-flag baseline is
        # parsed only if this volume has never migrated (DD-15), so a stale or
        # malformed staging value cannot fail an already-migrated boot.
        load_migration_seed=config.feature_flags.load_managed_migration_seed,
        resolve_account_id=_resolve_account_id_by_email,
    )

    # Built once, here, so the migration-time SQLite read `_build_agent_secret_
    # box` needs (DD-16) sees the same repository instance every other flag
    # read and mutation goes through.
    agent_secret_box = _build_agent_secret_box(config, agent_repo, feature_flag_repo)
    relay_capability_available = not isinstance(
        agent_secret_box, _UnavailableRelaySecretBox
    )

    # Built before the services that read a managed flag: `_voice_enabled_for_
    # owner` below and every `/admin/feature-flags` route resolve through this
    # one instance, so a mutation is visible to the very next evaluation
    # (010-FR-005, 010-FR-008).
    admin_service = AdminService(
        user_repo=user_repo,
        session_repo=session_repo,
        operator_emails=config.admin.operator_emails,
    )
    feature_flag_service = FeatureFlagService(
        repository=feature_flag_repo,
        config=config,
        user_repo=user_repo,
        admin_service=admin_service,
        relay_capability_available=relay_capability_available,
    )

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
    task_title_autocomplete_service = TaskTitleAutocompleteService(
        repository=task_repo,
        provider=build_title_completion_provider(
            config.task_title_autocomplete,
            environment=config.environment,
            environ=os.environ,
        ),
    )

    def _voice_enabled_for_owner(owner_id: str) -> bool:
        """Whether ``voice_brain_dump`` is effective for the operation's owner.

        Used by the background runner so external provider work never advances
        for an owner whose exposure flag is OFF. A missing user fails closed.
        """

        user = user_repo.get_by_id(owner_id)
        if user is None:
            return False
        return feature_flag_service.is_effective("voice_brain_dump", user)

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
        allowed_external_provider_categories=_allowed_external_provider_categories(
            config
        ),
        audio_limits=config.voice.audio_limits,
        task_port=InProcessTaskPort(task_service.create_native_inbox_task),
        voice_enabled_for_owner=_voice_enabled_for_owner,
    )

    def _task_snapshot(task_id: str, *, owner_id: str) -> TaskSnapshot:
        """Read-only view of a Task for the relay.

        Deliberately narrow: the relay may look at a Task's title and details to
        build a hand-off manifest, and has no way to write one back (FR-012).
        """

        task = task_service.get_task(task_id, owner_id=owner_id)
        return TaskSnapshot(id=task.id, title=task.title, details=task.details)

    relay_settings = config.agent_relay
    # Bounded on purpose, and bounded *here*: a held `SendMessage` occupies a
    # worker for up to the reply window, so an unbounded pool would let a single
    # slow agent consume the process (data-model.md §9).
    exchange_executor = ThreadPoolExecutor(
        max_workers=relay_settings.exchange_workers,
        thread_name_prefix="agent-exchange",
    )
    # Separate pools, not tuning: an observation must not queue behind a held
    # exchange, and a cancel — which is what *resolves* a held exchange on some
    # runtimes — must not queue behind either (data-model.md §9, AC-035).
    observation_executor = ThreadPoolExecutor(
        max_workers=relay_settings.observer_workers,
        thread_name_prefix="agent-observation",
    )
    control_executor = ThreadPoolExecutor(
        max_workers=relay_settings.control_workers,
        thread_name_prefix="agent-control",
    )
    agent_relay_service = AgentRelayService(
        agent_repo,
        a2a_client=A2AClient(
            timeout_seconds=relay_settings.connector_timeout_seconds,
            reply_window_seconds=relay_settings.reply_window_seconds,
            max_response_bytes=relay_settings.connector_max_response_bytes,
            task_max_response_bytes=relay_settings.a2a_task_max_response_bytes,
            allow_private_destinations=relay_settings.allow_private_destinations,
        ),
        secret_box=agent_secret_box,
        task_snapshot=_task_snapshot,
        callback_url=config.agent_relay_callback_url,
        push_base_url=config.agent_relay_push_base_url,
        # Deployment policy for discovery is bound here, once, rather than held
        # by the service: the service's job is to decide what a card *means*,
        # not how long BrainBuddy waits for one.
        card_fetcher=partial(
            fetch_card,
            timeout_seconds=relay_settings.connector_timeout_seconds,
            max_response_bytes=relay_settings.connector_max_response_bytes,
            allow_private_destinations=relay_settings.allow_private_destinations,
        ),
        exchange=ExchangePolicy(
            executor=exchange_executor,
            dispatch_wait_seconds=relay_settings.dispatch_wait_seconds,
            reply_window=timedelta(seconds=relay_settings.reply_window_seconds),
            observation_interval=timedelta(
                seconds=relay_settings.observation_interval_seconds
            ),
        ),
        stale_after=timedelta(seconds=relay_settings.stale_after_seconds),
        reporting_window=timedelta(seconds=relay_settings.reporting_window_seconds),
        content_retention=timedelta(seconds=relay_settings.content_retention_seconds),
        allow_private_destinations=relay_settings.allow_private_destinations,
    )
    # Constructed after the service and given it, so there is no cycle: the
    # client never needs a service, the service never needs a container, and the
    # observer binds itself as the service's exchange pump.
    agent_observer = AgentObserver(
        agent_relay_service,
        exchange_executor=exchange_executor,
        observation_executor=observation_executor,
        control_executor=control_executor,
        max_exchanges_per_connection=relay_settings.max_exchanges_per_connection,
        observation_interval=timedelta(
            seconds=relay_settings.observation_interval_seconds
        ),
    )

    # Grace period between a deletion request and the irreversible purge.
    # Overridable (in seconds) so the compose E2E suite can exercise the
    # purge without waiting two weeks.
    grace_env = os.getenv("BRAIN_BUDDY_ACCOUNT_PURGE_GRACE_SECONDS")
    deletion_grace = (
        timedelta(seconds=float(grace_env)) if grace_env else ACCOUNT_DELETION_GRACE
    )

    auth_service = AuthService(
        user_repo=user_repo,
        session_repo=session_repo,
        invite_repo=invite_repo,
        password_policy=config.password_policy,
        session_settings=config.session,
        # Plain configuration value, not the AdminService handle: the
        # reservation is a rule about which addresses a member may bind
        # (009-FR-012), and passing a service here would couple auth to the
        # admin portal in both directions.
        reserved_emails=config.admin.operator_emails,
        deletion_grace=deletion_grace,
    )
    account_service = AccountService(
        user_repo=user_repo,
        session_repo=session_repo,
        invite_repo=invite_repo,
        tree_service=tree_service,
        version_repo=version_repo,
        validation_repo=validation_repo,
        task_repo=task_repo,
        voice_operation_repo=voice_operation_repo,
        agent_repo=agent_repo,
        feature_flag_repo=feature_flag_repo,
        auth_service=auth_service,
        reserved_emails=config.admin.operator_emails,
        deletion_grace=deletion_grace,
    )
    admin_service.set_mutation_services(
        auth_service=auth_service, account_service=account_service
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
        agent_repo=agent_repo,
        feature_flag_repo=feature_flag_repo,
        tree_service=tree_service,
        node_service=node_service,
        relation_service=relation_service,
        version_service=version_service,
        validation_service=validation_service,
        auth_service=auth_service,
        account_service=account_service,
        admin_service=admin_service,
        feature_flag_service=feature_flag_service,
        task_service=task_service,
        voice_brain_dump_service=voice_brain_dump_service,
        agent_relay_service=agent_relay_service,
        agent_observer=agent_observer,
        task_title_autocomplete_service=task_title_autocomplete_service,
    )
