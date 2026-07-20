"""Application entrypoint for the Brain Buddy backend."""

import logging
import os

from fastapi import FastAPI

from app.api import api_router
from app.api.auth import router as auth_router
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.container import Container, build_container
from app.core import configure_logging, get_config

logger = logging.getLogger(__name__)


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
    purged_raw_audio = app.state.container.task_service.purge_expired_raw_audio()
    if purged_raw_audio:
        logger.info("Purged %s expired voice raw-audio operation(s)", purged_raw_audio)

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
