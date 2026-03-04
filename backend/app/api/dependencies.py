"""FastAPI dependency helpers for resolving services."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.container import Container
from app.schemas.domain import AccountDocument
from app.services import (
    AccountService,
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


def get_account_service(
    container: Container = Depends(get_container),
) -> AccountService:
    return container.account_service


def get_current_account(request: Request) -> AccountDocument:
    """Extract the authenticated account set by ApiKeyMiddleware."""
    account = getattr(request.state, "account", None)
    if account is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return account
