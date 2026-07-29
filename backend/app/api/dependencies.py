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


def get_current_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    config: AppConfig = Depends(get_config_dep),
) -> User:
    """Resolve the authenticated user from the session cookie.

    Raises 401 if the cookie is missing, unknown, or expired.
    """

    raw_token = request.cookies.get(config.session.cookie_name)
    user = auth_service.get_user_for_token(raw_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return user


def voice_brain_dump_enabled(user: User, config: AppConfig) -> bool:
    """Whether the ADR-0008 ``voice_brain_dump`` rollout flag is effective."""

    return config.feature_flags.effective_flags(user.email).get(
        "voice_brain_dump", False
    )


def require_voice_brain_dump_enabled(
    current_user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_config_dep),
) -> User:
    """Gate the new-capture voice Brain Dump routes on the ADR-0008 rollout flag.

    ``voice_brain_dump`` ships default OFF and rolls out OFF → INTERNAL → ON.
    An authenticated user for whom the flag is not effective gets a fail-closed
    404: the feature is simply not present for them (the refusal never discloses
    operation existence). Because this depends on :func:`get_current_user`, an
    unauthenticated caller is still rejected with 401 first.

    Exposure control is not authorization: the flag gates creation, recording,
    and forward processing, but an owner keeps privacy authority over an existing
    operation (read, withdraw consent, cancel, delete raw audio) even when the
    flag is OFF -- those routes use :func:`get_current_user` directly and check
    :func:`voice_brain_dump_enabled` only for the gated actions.
    """

    if not voice_brain_dump_enabled(current_user, config):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice brain dump is not available.",
        )
    return current_user
