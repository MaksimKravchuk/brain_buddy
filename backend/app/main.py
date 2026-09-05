"""Application entrypoint for the Brain Buddy backend."""

import logging
import os
import threading

from fastapi import FastAPI

from app.api import api_router
from app.api.account import router as account_router
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.container import Container, build_container
from app.core import configure_logging, get_config
from app.core.config import AppEnvironment

logger = logging.getLogger(__name__)

_VOICE_SWEEP_INTERVAL_SECONDS = float(
    os.getenv("BRAIN_BUDDY_VOICE_SWEEP_INTERVAL_SECONDS", "60")
)


def _run_privacy_maintenance_sweep(container: Container) -> tuple[int, int]:
    """Purge due accounts and relay content behind independent error boundaries."""

    purged_accounts = 0
    try:
        purged_accounts = container.account_service.purge_due_accounts()
    except Exception:  # noqa: BLE001 - a sweep failure must not kill the loop
        logger.exception("Account purge sweep iteration failed")

    expired_agent_runs = 0
    try:
        expired_agent_runs = container.agent_relay_service.run_retention_sweep()
    except Exception:  # noqa: BLE001 - a sweep failure must not kill the loop
        logger.exception("External-agent retention sweep iteration failed")
    return purged_accounts, expired_agent_runs


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


def _run_maintenance_sweep(container: Container) -> None:
    """One pass of the backend's periodic maintenance duties.

    Recovers due/expired provider-run leases, advances due provider runs,
    resumes operations frozen mid-commit, purges raw audio and uncommitted
    working artifacts past their configured retention, then hard-deletes
    accounts whose deletion grace period has elapsed. A single bad pass must
    never kill the loop that calls this.
    """

    purged_accounts, expired_agent_runs = _run_privacy_maintenance_sweep(container)
    (
        recovered_leases,
        advanced_runs,
        resumed_commits,
        purged_raw_audio,
        purged_working_artifacts,
    ) = _run_voice_maintenance_sweep(container)
    if (
        recovered_leases
        or advanced_runs
        or resumed_commits
        or purged_raw_audio
        or purged_working_artifacts
        or purged_accounts
        or expired_agent_runs
    ):
        logger.info(
            "Maintenance sweep: recovered %s lease(s), resumed %s commit(s), "
            "purged %s raw-audio, %s working-artifact operation(s), advanced "
            "%s provider run(s), purged %s account(s), expired %s agent run(s)",
            recovered_leases,
            resumed_commits,
            purged_raw_audio,
            purged_working_artifacts,
            advanced_runs,
            purged_accounts,
            expired_agent_runs,
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
    container: Container, stop_event: threading.Event, *, interval_seconds: float
) -> threading.Thread:
    """Start the privacy scheduler on an interval independent from voice work."""

    def _loop() -> None:
        while not stop_event.wait(interval_seconds):
            _run_privacy_maintenance_sweep(container)

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
    app.state.container = build_container(config)
    _maybe_seed_admin(app.state.container)
    # Retry-safe startup scan: recover any provider lease that expired while
    # no process was running, then purge whatever raw audio/working
    # artifacts are already due. This must run unconditionally (including in
    # tests) since it is a one-shot, synchronous, already-tested code path.
    _run_maintenance_sweep(app.state.container)

    app.state.voice_sweep_stop_event = threading.Event()
    app.state.voice_sweep_wake_event = threading.Event()
    app.state.privacy_maintenance_stop_event = threading.Event()
    app.state.container.voice_brain_dump_service.runner_wake = (
        app.state.voice_sweep_wake_event.set
    )
    app.state.voice_sweep_thread = None
    app.state.privacy_maintenance_thread = None
    enable_test_voice_sweep = (
        os.getenv("BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST", "").strip() == "1"
    )
    background_maintenance_enabled = (
        config.environment is not AppEnvironment.TEST or enable_test_voice_sweep
    )

    if _VOICE_SWEEP_INTERVAL_SECONDS > 0 and background_maintenance_enabled:
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
        interrupted = app.state.container.agent_observer.mark_interrupted_exchanges()
        # Started next to the maintenance thread and under the same gate: the
        # observer is the only thing that ever moves a dispatched run forward,
        # and a test suite that built many short-lived apps in one process
        # would otherwise have as many schedulers racing one another.
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
        )

    if (
        app.state.voice_sweep_thread is not None
        or app.state.privacy_maintenance_thread is not None
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
            if app.state.voice_sweep_thread is not None:
                app.state.voice_sweep_thread.join(timeout=5)
            if app.state.privacy_maintenance_thread is not None:
                app.state.privacy_maintenance_thread.join(timeout=5)

    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(auth_router, prefix=f"{config.api_prefix}/auth")
    app.include_router(account_router, prefix=f"{config.api_prefix}/account")
    app.include_router(admin_router, prefix=f"{config.api_prefix}/admin")
    app.include_router(api_router, prefix=config.api_prefix)

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
