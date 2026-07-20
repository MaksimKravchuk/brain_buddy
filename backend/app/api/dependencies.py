"""FastAPI dependency helpers for resolving services."""

from __future__ import annotations

from typing import cast

from fastapi import Depends, HTTPException, Request, status

from app.container import Container
from app.core.config import AppConfig
from app.modules.tasks import TaskService
from app.schemas.auth import User
from app.services import (
    AuthService,
    NodeService,
    RelationService,
    TreeService,
    ValidationService,
    VersionService,
)
from app.workflows.voice_brain_dump.service import VoiceBrainDumpService


def get_container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - application misconfiguration
        raise RuntimeError("Application container has not been configured.")
    return cast(Container, container)


def get_config_dep(request: Request) -> AppConfig:
    config = getattr(request.app.state, "config", None)
    if config is None:  # pragma: no cover - application misconfiguration
        raise RuntimeError("Application config has not been configured.")
    return cast(AppConfig, config)


def get_tree_service(container: Container = Depends(get_container)) -> TreeService:
    return container.tree_service


def get_node_service(container: Container = Depends(get_container)) -> NodeService:
    return container.node_service


def get_relation_service(
    container: Container = Depends(get_container),
) -> RelationService:
    return container.relation_service


def get_version_service(
    container: Container = Depends(get_container),
) -> VersionService:
    return container.version_service


def get_validation_service(
    container: Container = Depends(get_container),
) -> ValidationService:
    return container.validation_service


def get_auth_service(container: Container = Depends(get_container)) -> AuthService:
    return container.auth_service


def get_task_service(container: Container = Depends(get_container)) -> TaskService:
    return container.task_service


def get_voice_brain_dump_service(
    container: Container = Depends(get_container),
) -> VoiceBrainDumpService:
    return container.voice_brain_dump_service


def get_session_token(request: Request, config: AppConfig) -> str | None:
    """Return one unambiguous opaque Session credential from cookie or Bearer auth."""

    cookie_token = request.cookies.get(config.session.cookie_name)
    authorization = request.headers.get("Authorization")
    if cookie_token and authorization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either a session cookie or Bearer credential, not both.",
        )
    if authorization is None:
        return cookie_token

    scheme, separator, token = authorization.partition(" ")
    if scheme != "Bearer" or not separator or not token or token.strip() != token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return token


def get_current_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    config: AppConfig = Depends(get_config_dep),
) -> User:
    """Resolve the authenticated user from the session cookie.

    Raises 401 if the cookie is missing, unknown, or expired.
    """

    raw_token = get_session_token(request, config)
    user = auth_service.get_user_for_token(raw_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return user
