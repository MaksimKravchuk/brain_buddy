"""FastAPI dependency helpers for resolving services."""

from __future__ import annotations

from fastapi import Depends, Request

from app.container import Container
from app.services import (
    NodeService,
    RelationService,
    TreeService,
    ValidationService,
    VersionService,
)


def get_container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - application misconfiguration
        raise RuntimeError("Application container has not been configured.")
    return container


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
