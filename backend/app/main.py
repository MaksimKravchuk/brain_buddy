"""Application entrypoint for the Brain Buddy backend."""

import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from fastapi import FastAPI

from app.api import api_router
from app.api.account import router as account_router
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.cli_auth import router as cli_auth_router
from app.api.errors import register_exception_handlers
from app.api.mcp import install_task_mcp
from app.api.middleware import CorrelationIdMiddleware
from app.api.modern_auth import router as modern_auth_router
from app.api.review import register_review_exception_handlers
from app.container import Container, build_container
from app.core import configure_logging, get_config
from app.core.config import AppEnvironment
from app.modules.tasks.jobs.agent_adapter import (
    OBSERVE_JOB_TYPE,
    AgentObservationAdapter,
    AgentRecoveryAdapter,
)
from app.modules.tasks.jobs.execution import JobExecutionGate
from app.modules.tasks.jobs.privacy_adapter import PrivacyMaintenanceAdapter
from app.modules.tasks.jobs.review_adapter import ReviewJobAdapter
from app.modules.tasks.jobs.voice_adapter import VOICE_JOB_TYPE, VoiceMaintenanceAdapter
from app.modules.tasks.jobs.worker import (
    JobRegistry,
    JobWorker,
    Responsibility,
    SchedulerHandoff,
    SchedulerOwner,
)
from app.modules.tasks.review_service import ReviewSweepResult
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

_VOICE_SWEEP_INTERVAL_SECONDS = float(
    os.getenv("BRAIN_BUDDY_VOICE_SWEEP_INTERVAL_SECONDS", "60")
)

#: Spec 026 PR-64: default OFF. Read once at boot; while it is off the legacy
#: loops below are the sole owners of every responsibility, exactly as before.
_DURABLE_SCHEDULER_ENV = "BRAIN_BUDDY_DURABLE_SCHEDULER"


def _durable_scheduler_enabled() -> bool:
    raw = os.getenv(_DURABLE_SCHEDULER_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _run_privacy_maintenance_sweep(
    container: Container, handoff: SchedulerHandoff | None = None
) -> tuple[int, int, int]:
    """Purge authentication metadata, due accounts, relay content, and CRT receipts.

    With a ``handoff`` the durable worker may own the account purge, relay and CRT
    receipt retention and the Review sweep; those steps are then skipped here. Auth
    cleanup and CRT command reconciliation always stay with this loop.
    """

    durable = handoff.durable if handoff is not None else (lambda _r: False)
    try:
        container.modern_auth_service.cleanup_expired_metadata()
    except Exception:  # noqa: BLE001 - a sweep failure must not kill the loop
        logger.warning("Authentication metadata cleanup deferred")

    try:
        container.auth_migration.cleanup_expired_backup()
    except Exception:  # noqa: BLE001 - a sweep failure must not kill the loop
        logger.warning("Authentication backup cleanup deferred")
    try:
        container.cli_auth_service.cleanup()
    except Exception:  # noqa: BLE001 - coarse diagnostics never contain grant data
        logger.warning("CLI authorization cleanup deferred")

    retained = not durable(Responsibility.PRIVACY_RETENTION)
    purged_accounts = (
        _isolated_step(
            lambda: container.account_service.purge_due_accounts(),
            "Account purge sweep iteration failed",
        )
        if retained
        else 0
    )
    expired_agent_runs = (
        _isolated_step(
            lambda: container.agent_relay_service.run_retention_sweep(),
            "External-agent retention sweep iteration failed",
        )
        if retained
        else 0
    )

    try:
        container.crt_command_service.reconcile_pending_commands()
    except Exception:  # noqa: BLE001 - a sweep failure must not kill the loop
        logger.exception("CRT command reconciliation sweep iteration failed")

    expired_crt_receipts = (
        _isolated_step(
            lambda: container.crt_command_repo.purge_expired(),
            "CRT command retention sweep iteration failed",
        )
        if retained
        else 0
    )

    # Spec 020: its own block, so a review failure stops neither purge nor
    # relay retention, and the 3-tuple above stays this function's contract.
    if not durable(Responsibility.REVIEW_SWEEP):
        _run_review_maintenance_sweep(container)
    return purged_accounts, expired_agent_runs, expired_crt_receipts


def _isolated_step(call: Callable[[], int], failure: str) -> int:
    """One retention step whose failure must not stop the steps after it."""

    try:
        return call()
    except Exception:  # noqa: BLE001 - a sweep failure must not kill the loop
        logger.exception(failure)
        return 0


def _run_review_maintenance_sweep(container: Container) -> ReviewSweepResult | None:
    """One weekly-review sweep run (spec 020, contracts/http.md §9).

    Retention (idempotency records past 24 h, 7-day snapshots, idle runs,
    35-day usage rows) for every owner with review rows or an expired
    idempotency record, whatever the flag state, then the exposure part (sweep-gap floor, clock repair, auto-park) for activated
    owners whose ``weekly_review`` flag is effective. Runs from the privacy
    maintenance loop and, through it, from the startup sweep. A failure is
    logged as the exception type only: the message could carry task content.
    """

    try:
        return container.review_service.run_maintenance_sweep()
    except Exception as exc:  # noqa: BLE001 - a sweep failure must not kill the loop
        logger.error(
            "review_sweep_failed error=%s reason=%s", type(exc).__name__, "sweep"
        )
        return None


def _run_voice_maintenance_sweep(
    container: Container,
) -> tuple[int, int, int, int, int]:
    """Run voice recovery and retention without affecting privacy scheduling."""

    try:
        recovered_leases = (
            container.voice_brain_dump_service.recover_due_provider_leases()
        )
        advanced_runs = (
            container.voice_brain_dump_service.run_due_brain_dump_provider_runs()
        )
        resumed_commits = (
            container.voice_brain_dump_service.recover_committing_operations()
        )
        purged_raw_audio = container.voice_brain_dump_service.purge_expired_raw_audio()
        purged_working_artifacts = (
            container.voice_brain_dump_service.purge_expired_working_artifacts()
        )
    except Exception:  # noqa: BLE001 - a sweep failure must not kill the loop
        logger.exception("Voice maintenance sweep iteration failed")
        return (0, 0, 0, 0, 0)
    return (
        recovered_leases,
        advanced_runs,
        resumed_commits,
        purged_raw_audio,
        purged_working_artifacts,
    )


def _run_maintenance_sweep(
    container: Container, handoff: SchedulerHandoff | None = None
) -> None:
    """One pass of the backend's periodic maintenance duties.

    Recovers due/expired provider-run leases, advances due provider runs,
    resumes operations frozen mid-commit, purges raw audio and uncommitted
    working artifacts past their configured retention, then hard-deletes
    accounts whose deletion grace period has elapsed. A single bad pass must
    never kill the loop that calls this. Responsibilities the durable worker owns
    are skipped (their first run is the worker's boot occurrence).
    """

    (
        purged_accounts,
        expired_agent_runs,
        expired_crt_receipts,
    ) = _run_privacy_maintenance_sweep(container, handoff)
    voice_counts = (0, 0, 0, 0, 0)
    if handoff is None or not handoff.durable(Responsibility.VOICE_SWEEP):
        voice_counts = _run_voice_maintenance_sweep(container)
    (
        recovered_leases,
        advanced_runs,
        resumed_commits,
        purged_raw_audio,
        purged_working_artifacts,
    ) = voice_counts
    if (
        recovered_leases
        or advanced_runs
        or resumed_commits
        or purged_raw_audio
        or purged_working_artifacts
        or purged_accounts
        or expired_agent_runs
        or expired_crt_receipts
    ):
        logger.info(
            "Maintenance sweep: recovered %s lease(s), resumed %s commit(s), "
            "purged %s raw-audio, %s working-artifact operation(s), advanced "
            "%s provider run(s), purged %s account(s), expired %s agent run(s), "
            "purged %s CRT receipt(s)",
            recovered_leases,
            resumed_commits,
            purged_raw_audio,
            purged_working_artifacts,
            advanced_runs,
            purged_accounts,
            expired_agent_runs,
            expired_crt_receipts,
        )


def _start_voice_sweep_thread(
    container: Container, stop_event: threading.Event, wake_event: threading.Event
) -> threading.Thread:
    """Start a tracked, stoppable daemon thread running the periodic sweep.

    Not an untracked ``asyncio.create_task`` fire-and-forget: the thread and
    its stop signal live on ``app.state`` so shutdown can join it, and
    ``daemon=True`` is defense in depth if shutdown is skipped.
    """

    def _loop() -> None:
        while not stop_event.is_set():
            wake_event.wait(_VOICE_SWEEP_INTERVAL_SECONDS)
            wake_event.clear()
            if stop_event.is_set():
                break
            _run_voice_maintenance_sweep(container)

    thread = threading.Thread(target=_loop, name="voice-operation-sweep", daemon=True)
    thread.start()
    return thread


def _start_privacy_maintenance_thread(
    container: Container,
    stop_event: threading.Event,
    *,
    interval_seconds: float,
    handoff: SchedulerHandoff | None = None,
) -> threading.Thread:
    """Start the privacy scheduler on an interval independent from voice work.

    After a handoff this loop keeps only what the worker did not take (auth
    cleanup, CRT reconciliation).
    """

    def _loop() -> None:
        while not stop_event.wait(interval_seconds):
            _run_privacy_maintenance_sweep(container, handoff)

    thread = threading.Thread(
        target=_loop, name="privacy-maintenance-sweep", daemon=True
    )
    thread.start()
    return thread


def _maybe_seed_admin(container: Container) -> None:
    """Seed an admin account from environment variables, if configured.

    Both `BRAIN_BUDDY_ADMIN_EMAIL` and `BRAIN_BUDDY_ADMIN_PASSWORD` must be
    set for seeding to run. If either is missing we leave the instance as
    the normal invite-gated signup flow. If the password fails policy, we
    raise so the deploy fails loudly instead of silently skipping.
    """

    admin_email = os.getenv("BRAIN_BUDDY_ADMIN_EMAIL")
    admin_password = os.getenv("BRAIN_BUDDY_ADMIN_PASSWORD")
    if not admin_email or not admin_password:
        return
    container.auth_service.seed_admin(email=admin_email, password=admin_password)


def _start_auth_dispatch_thread(
    container: Container, stop: threading.Event
) -> threading.Thread:
    def dispatch() -> None:
        while not stop.is_set():
            try:
                container.modern_auth_service.dispatch_one()
            except (
                Exception
            ):  # noqa: BLE001 - recover the loop without exposing credentials
                logger.warning("Authentication delivery iteration deferred")
            stop.wait(1)

    thread = threading.Thread(target=dispatch, name="auth-delivery", daemon=True)
    thread.start()
    return thread


def _wake_job(worker: JobWorker, job_type: str) -> Callable[[], None]:
    """A push into the ledger that never fails the request or push that made it."""

    def wake() -> None:
        try:
            worker.wake(job_type)
        except Exception:  # noqa: BLE001 - the periodic occurrence still runs
            logger.warning("Durable job wake deferred for %s", job_type)

    return wake


def _install_durable_scheduler(
    container: Container,
    handoff: SchedulerHandoff,
    *,
    voice_interval_seconds: float,
    privacy_interval_seconds: float,
    gate: JobExecutionGate | None = None,
    now: Callable[[], datetime] = utcnow,
) -> JobWorker | None:
    """Register the completed adapters and take over their responsibilities.

    ``None`` (and nothing assigned) unless the handoff is enabled. Each adapter
    is registered and its responsibility assigned to the worker in one step, so
    the legacy loop for it never starts. Call before any legacy loop starts: the
    observation adapter refuses a live observer thread. Registers no effect of
    its own; the adapters call the existing ports under the execution context.
    """

    if not handoff.enabled:
        return None
    gate = gate or container.job_execution
    registry = JobRegistry()
    owned = SchedulerOwner.DURABLE
    privacy = timedelta(seconds=privacy_interval_seconds)
    registry.register(ReviewJobAdapter(container.review_service, gate, cadence=privacy))
    handoff.assign(Responsibility.REVIEW_SWEEP, owned)
    registry.register(
        PrivacyMaintenanceAdapter(
            container.account_service,
            container.agent_relay_service,
            container.crt_command_repo,
            gate,
            cadence=privacy,
        )
    )
    handoff.assign(Responsibility.PRIVACY_RETENTION, owned)
    observer = container.agent_observer
    registry.register(AgentObservationAdapter(observer, gate))
    handoff.assign(Responsibility.AGENT_OBSERVATION, owned)
    registry.register(
        AgentRecoveryAdapter(observer, gate, container.job_repository, now=now)
    )
    handoff.assign(Responsibility.AGENT_RECOVERY, owned)
    if voice_interval_seconds > 0:
        registry.register(
            VoiceMaintenanceAdapter(
                container.voice_brain_dump_service,
                gate,
                cadence=timedelta(seconds=voice_interval_seconds),
            )
        )
        handoff.assign(Responsibility.VOICE_SWEEP, owned)
    worker = JobWorker(container.job_repository, registry, now=now)
    observer.wake_listener = _wake_job(worker, OBSERVE_JOB_TYPE)
    if handoff.durable(Responsibility.VOICE_SWEEP):
        container.voice_brain_dump_service.runner_wake = _wake_job(
            worker, VOICE_JOB_TYPE
        )
    return worker


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    config = get_config()
    configure_logging(config)

    app = FastAPI(
        title="Brain Buddy API",
        version=config.data.schema_version,
        openapi_url=f"{config.api_prefix}/openapi.json",
        docs_url=f"{config.api_prefix}/docs",
        redoc_url=f"{config.api_prefix}/redoc",
    )
    app.state.config = config
    app.state.container = build_container(config, serve_navigator=True)
    _maybe_seed_admin(app.state.container)
    enable_test_voice_sweep = (
        os.getenv("BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST", "").strip() == "1"
    )
    background_maintenance_enabled = (
        config.environment is not AppEnvironment.TEST or enable_test_voice_sweep
    )
    app.state.voice_sweep_stop_event = threading.Event()
    app.state.voice_sweep_wake_event = threading.Event()
    app.state.privacy_maintenance_stop_event = threading.Event()
    app.state.container.voice_brain_dump_service.runner_wake = (
        app.state.voice_sweep_wake_event.set
    )
    # Spec 026 PR-64. The durable worker takes over only where the background
    # schedulers themselves run (never in the test suite's short-lived apps), and
    # only with the gate on; every responsibility is assigned exactly one owner
    # here, before any loop starts, and the rest stay with the legacy loops.
    handoff = SchedulerHandoff(
        enabled=_durable_scheduler_enabled() and background_maintenance_enabled
    )
    app.state.scheduler_handoff = handoff
    app.state.durable_worker = _install_durable_scheduler(
        app.state.container,
        handoff,
        voice_interval_seconds=_VOICE_SWEEP_INTERVAL_SECONDS,
        privacy_interval_seconds=config.agent_relay.retention_sweep_interval_seconds,
    )
    handoff.assign_remaining_to_legacy()
    # Retry-safe startup scan: recover any provider lease that expired while
    # no process was running, then purge whatever raw audio/working
    # artifacts are already due. This must run unconditionally (including in
    # tests) since it is a one-shot, synchronous, already-tested code path.
    # Handed-off responsibilities run as the worker's boot occurrence instead.
    _run_maintenance_sweep(app.state.container, handoff)

    app.state.auth_dispatch_stop_event = threading.Event()
    app.state.auth_dispatch_thread = None
    app.state.voice_sweep_thread = None
    app.state.privacy_maintenance_thread = None

    if config.modern_auth.crypto_ready and background_maintenance_enabled:
        app.state.auth_dispatch_thread = _start_auth_dispatch_thread(
            app.state.container, app.state.auth_dispatch_stop_event
        )

    if (
        _VOICE_SWEEP_INTERVAL_SECONDS > 0
        and background_maintenance_enabled
        and not handoff.durable(Responsibility.VOICE_SWEEP)
    ):
        # A real periodic sweep thread is only started outside tests: the
        # test suite builds many short-lived apps/repositories per process,
        # and TaskRepository.command_lock is a process-wide class lock, so a
        # long-lived background thread left running past its own test's
        # temp-dir teardown would race and deadlock unrelated tests. The
        # Compose E2E runner is a separate process and opts in explicitly.
        app.state.voice_sweep_thread = _start_voice_sweep_thread(
            app.state.container,
            app.state.voice_sweep_stop_event,
            app.state.voice_sweep_wake_event,
        )
    if background_maintenance_enabled:
        # Once, at boot, before a request can be served — but only the half of
        # recovery that needs nothing from the network. Every exchange a restart
        # left mid-flight is *marked* by what it can prove: a queued one never
        # left, so it is **Not sent** and offered again; a started one is marked
        # interrupted. Gated with the other maintenance for the same reason the
        # sweeps are: the test suite builds many short-lived apps in one
        # process, and a boot-time scan over a shared, process-wide lock would
        # race unrelated tests.
        # With the worker owning recovery, the same marking is its boot job.
        interrupted: list[tuple[str, str]] = []
        if not handoff.durable(Responsibility.AGENT_RECOVERY):
            interrupted = (
                app.state.container.agent_observer.mark_interrupted_exchanges()
            )
        # Started next to the maintenance thread and under the same gate: the
        # observer is the only thing that ever moves a dispatched run forward,
        # and a test suite that built many short-lived apps in one process
        # would otherwise have as many schedulers racing one another.
        if not handoff.durable(Responsibility.AGENT_OBSERVATION):
            app.state.container.agent_observer.start()
        # And only now the lookups, on the observer's own pool. Each one is a
        # `ListTasks` under the short-call deadline; running them here rather
        # than above is the difference between an unreachable agent delaying one
        # run's resolution and it holding `/health` closed for the deadline
        # times the backlog, while `fly.backend.toml`'s five-second check
        # restarts the machine that is trying to recover. Still a lookup and
        # never a send: no send is ever initiated without a user action
        # (AC-032).
        app.state.container.agent_observer.resolve_interrupted_exchanges(interrupted)
        app.state.privacy_maintenance_thread = _start_privacy_maintenance_thread(
            app.state.container,
            app.state.privacy_maintenance_stop_event,
            interval_seconds=config.agent_relay.retention_sweep_interval_seconds,
            handoff=handoff,
        )
        if app.state.durable_worker is not None:
            # The boot sweep as occurrences the lease protects: recovery of
            # interrupted exchanges plus a first run of every handed-off job.
            app.state.durable_worker.ensure_schedules(due_now=True)
            app.state.durable_worker.start()

    if (
        app.state.voice_sweep_thread is not None
        or app.state.privacy_maintenance_thread is not None
        or app.state.durable_worker is not None
    ):

        @app.on_event("shutdown")
        def _stop_maintenance_sweeps() -> None:
            app.state.voice_sweep_stop_event.set()
            app.state.voice_sweep_wake_event.set()
            app.state.privacy_maintenance_stop_event.set()
            # Stops the scheduler, joins it under a bound, and cancels only
            # the pool work that never started: an exchange already in flight
            # may be at the agent, and dropping it would leave a run nobody
            # will ever settle.
            app.state.container.agent_observer.shutdown()
            if app.state.durable_worker is not None:
                app.state.durable_worker.shutdown()
            if app.state.voice_sweep_thread is not None:
                app.state.voice_sweep_thread.join(timeout=5)
            if app.state.privacy_maintenance_thread is not None:
                app.state.privacy_maintenance_thread.join(timeout=5)

    app.add_middleware(CorrelationIdMiddleware, api_prefix=config.api_prefix)
    register_exception_handlers(app)

    @app.on_event("shutdown")
    def close_auth_provider() -> None:
        app.state.auth_dispatch_stop_event.set()
        if app.state.auth_dispatch_thread is not None:
            app.state.auth_dispatch_thread.join(timeout=12)
        app.state.container.modern_auth_service.provider.close()

    app.include_router(modern_auth_router, prefix=config.api_prefix)
    app.include_router(cli_auth_router, prefix=config.api_prefix)
    register_review_exception_handlers(app)
    app.include_router(auth_router, prefix=f"{config.api_prefix}/auth")
    app.include_router(account_router, prefix=f"{config.api_prefix}/account")
    app.include_router(admin_router, prefix=f"{config.api_prefix}/admin")
    app.include_router(api_router, prefix=config.api_prefix)
    if config.mcp_enabled:
        install_task_mcp(app, app.state.container, config)

    @app.get("/health", tags=["health"])
    @app.get(f"{config.api_prefix}/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Return a lightweight health check payload."""
        return {
            "status": "ok",
            "environment": config.environment.value,
            "schema_version": config.data.schema_version,
        }

    return app


app = create_app()
