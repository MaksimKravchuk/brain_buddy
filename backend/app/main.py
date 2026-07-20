"""Application entrypoint for the Brain Buddy backend."""

import logging
import os
import threading

from fastapi import FastAPI

from app.api import api_router
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


def _run_voice_sweep(container: Container) -> None:
    """One pass of the persisted voice-operation runner's periodic duties.

    Recovers due/expired provider-run leases, then purges raw audio and
    uncommitted working artifacts past their configured retention. A single
    bad pass must never kill the loop that calls this.
    """

    try:
        recovered_leases = container.voice_brain_dump_service.recover_due_provider_leases()
        advanced_runs = container.voice_brain_dump_service.run_due_brain_dump_provider_runs()
        purged_raw_audio = container.voice_brain_dump_service.purge_expired_raw_audio()
        purged_working_artifacts = (
            container.voice_brain_dump_service.purge_expired_working_artifacts()
        )
        drained_audio_deletions = (
            container.voice_brain_dump_service.drain_pending_raw_audio_deletions()
        )
    except Exception:  # noqa: BLE001 - a sweep failure must not kill the loop
        logger.exception("Voice operation sweep iteration failed")
        return
    if (
        recovered_leases
        or advanced_runs
        or purged_raw_audio
        or purged_working_artifacts
        or drained_audio_deletions
    ):
        logger.info(
            "Voice sweep: recovered %s lease(s), purged %s raw-audio, %s "
            "working-artifact operation(s), advanced %s provider run(s), "
            "drained %s pending raw-audio deletion(s)",
            recovered_leases,
            purged_raw_audio,
            purged_working_artifacts,
            advanced_runs,
            drained_audio_deletions,
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
            _run_voice_sweep(container)

    thread = threading.Thread(target=_loop, name="voice-operation-sweep", daemon=True)
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
        version=config.api.semantic_version,
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
    _run_voice_sweep(app.state.container)

    app.state.voice_sweep_stop_event = threading.Event()
    app.state.voice_sweep_wake_event = threading.Event()
    app.state.container.voice_brain_dump_service.runner_wake = (
        app.state.voice_sweep_wake_event.set
    )
    app.state.voice_sweep_thread = None
    enable_test_voice_sweep = (
        os.getenv("BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST", "").strip() == "1"
    )
    if _VOICE_SWEEP_INTERVAL_SECONDS > 0 and (
        config.environment is not AppEnvironment.TEST or enable_test_voice_sweep
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

        @app.on_event("shutdown")
        def _stop_voice_sweep() -> None:
            app.state.voice_sweep_stop_event.set()
            app.state.voice_sweep_wake_event.set()
            if app.state.voice_sweep_thread is not None:
                app.state.voice_sweep_thread.join(timeout=5)

    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(auth_router, prefix=f"{config.api_prefix}/auth")
    app.include_router(api_router, prefix=config.api_prefix)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Return a lightweight health check payload."""
        return {
            "status": "ok",
            "environment": config.environment.value,
            "schema_version": config.data.schema_version,
        }

    return app


app = create_app()
