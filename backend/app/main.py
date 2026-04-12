"""Application entrypoint for the Brain Buddy backend."""

from fastapi import FastAPI

from app.api import api_router
from app.api.auth import router as auth_router
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.container import build_container
from app.core import configure_logging, get_config


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
