"""FastAPI dependency helpers for resolving services."""

from __future__ import annotations

import logging
from typing import cast

from fastapi import Depends, HTTPException, Request, status

from app.container import Container
from app.core.config import AppConfig
from app.core.logging import get_correlation_id
from app.modules.agents.service import AgentRelayService
from app.modules.tasks import TaskService
from app.modules.tasks.autocomplete import TaskTitleAutocompleteService
from app.schemas.auth import User
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
from app.workflows.voice_brain_dump.service import VoiceBrainDumpService

logger = logging.getLogger(__name__)


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


def get_account_service(
    container: Container = Depends(get_container),
) -> AccountService:
    return container.account_service


def get_admin_service(
    container: Container = Depends(get_container),
) -> AdminService:
    return container.admin_service


def get_feature_flag_service(
    container: Container = Depends(get_container),
) -> FeatureFlagService:
    """The runtime rollout resolver for the two managed flags (010-FR-008)."""

    return container.feature_flag_service


def get_task_service(container: Container = Depends(get_container)) -> TaskService:
    return container.task_service


def get_task_title_autocomplete_service(
    container: Container = Depends(get_container),
) -> TaskTitleAutocompleteService:
    return container.task_title_autocomplete_service


def get_voice_brain_dump_service(
    container: Container = Depends(get_container),
) -> VoiceBrainDumpService:
    return container.voice_brain_dump_service


def get_agent_relay_service(
    container: Container = Depends(get_container),
) -> AgentRelayService:
    return container.agent_relay_service


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


ADMIN_STATUS_EVENT = "admin_capability_probe"
"""Log event for the `/admin/status` capability check (009-FR-011)."""

ADMIN_DATA_EVENT = "admin_data_route"
"""Log event for the lookup and revoke data routes (009-FR-011)."""


ADMIN_ROUTE_UNMATCHED = "unmatched"
"""Fail-closed placeholder when no route template can be resolved."""


def _admin_log_event(request: Request, config: AppConfig) -> str:
    """Which admin event this request is, for the FR-011 denial split.

    A capability probe is issued on every `/admin` page load; a data-route
    denial is a real attempt to read or mutate another account. Collapsing
    them into one message makes the denial stream unusable as a signal.
    """

    if _admin_route(request, config).endswith("/status"):
        return ADMIN_STATUS_EVENT
    return ADMIN_DATA_EVENT


def _admin_route(request: Request, config: AppConfig) -> str:
    """The matched route *template*, canonicalized, never the raw request path.

    The revoke path interpolates a caller-supplied account id, which is raw
    request input and must stay out of every record (009-FR-008) — so the
    template is the only admissible source, and `request.url.path` and the
    path params are deliberately never consulted.

    `scope["route"]` is framework-version-dependent, though. Older
    FastAPI/Starlette expose the route as registered on the application, so the
    template already carries the `include_router` prefix
    (`/api/admin/accounts/lookup`). Newer versions let the innermost matching
    router set it, so the same request yields a router-local template
    (`/accounts/lookup`). Both are inside this project's declared dependency
    ranges, and an audit record whose shape depends on which one resolved is
    not a canonical record. So the mount prefix is re-applied from
    configuration when — and only when — the template does not already carry
    it; blind prepending would double it on the older shape.

    Anything that is not a usable absolute template stays redacted: no route,
    no `path`, an empty path, or a relative one all yield
    `ADMIN_ROUTE_UNMATCHED` rather than a guess.
    """

    template = getattr(request.scope.get("route"), "path", None)
    if not isinstance(template, str) or not template.startswith("/"):
        return ADMIN_ROUTE_UNMATCHED
    prefix = f"{config.api_prefix}/admin"
    if template == prefix or template.startswith(f"{prefix}/"):
        return template
    return f"{prefix}{template}"


def require_operator(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    config: AppConfig = Depends(get_config_dep),
    admin_service: AdminService = Depends(get_admin_service),
) -> User:
    """Gate every `/admin` route on a valid session AND the operator allow-list.

    Resolves the session itself rather than depending on `get_current_user`,
    so a missing, invalid, or expired session logs one generic, content-free
    warning before the 401 (no cookie, token, or email in the log line). An
    authenticated caller not on the allow-list gets 403, logged with the
    caller's account id only, never their email. Both checks run before any
    account lookup or mutation, so the denial can never vary with whether a
    target account exists (009-FR-002).

    Denial records follow the 009-FR-008 per-event matrix exactly:

    * **401** — correlation id, route template, event and outcome. There is
      no resolved operator to name, and naming the rejected cookie would leak
      the credential the request was denied for.
    * **403** — the same, plus the caller's account id. Never a target id: a
      denial must be decided before any target is resolved, so there is
      nothing to name and resolving one would break "deny before touch".
    """

    event = _admin_log_event(request, config)
    route = _admin_route(request, config)
    raw_token = request.cookies.get(config.session.cookie_name)
    user = auth_service.get_user_for_token(raw_token)
    if user is None:
        logger.warning(
            "Admin access denied: event=%s route=%s correlation=%s outcome=%s",
            event,
            route,
            get_correlation_id(),
            "no_valid_session",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    if not admin_service.is_operator(user.email):
        logger.warning(
            "Admin access denied: event=%s route=%s correlation=%s operator=%s "
            "outcome=%s",
            event,
            route,
            get_correlation_id(),
            user.id,
            "not_an_operator",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized."
        )
    return user


def voice_brain_dump_enabled(user: User, feature_flags: FeatureFlagService) -> bool:
    """Whether the ADR-0008 ``voice_brain_dump`` rollout flag is effective.

    Resolves through the runtime resolver rather than `config.feature_flags`
    directly (010-FR-008): a runtime override on this managed flag must reach
    every one of its call sites, or the operator screen would be lying about
    who can capture.
    """

    return feature_flags.is_effective("voice_brain_dump", user)


def require_voice_brain_dump_enabled(
    current_user: User = Depends(get_current_user),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
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

    if not voice_brain_dump_enabled(current_user, feature_flags):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice brain dump is not available.",
        )
    return current_user


def external_agent_relay_enabled(user: User, feature_flags: FeatureFlagService) -> bool:
    """Whether ``external_agent_relay`` is effective for this user (DD-16).

    Resolves through the runtime resolver rather than `config.feature_flags`
    directly (010-FR-008): the SQLite rollout answer is ANDed with the
    construction-time relay capability, so a runtime ON never exposes the
    relay without a constructed secret box.
    """

    return feature_flags.is_effective("external_agent_relay", user)


def require_external_agent_relay_enabled(
    current_user: User = Depends(get_current_user),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> User:
    """Gate relay operations that create or enable future external work.

    Ships default OFF and rolls out OFF → INTERNAL → ON. An authenticated user
    without the flag gets a fail-closed 404: the feature is simply not present.
    Because this depends on :func:`get_current_user`, an unauthenticated caller
    is still rejected with 401 first.

    Owner-scoped reads, disconnect, and safe reply/cancel commands for existing
    runs use :func:`get_current_user` directly. The inbound connector-event route is also
    deliberately not gated, so rollback never abandons already-dispatched work.
    """

    if not external_agent_relay_enabled(current_user, feature_flags):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="External agent relay is not available.",
        )
    return current_user
