"""Authenticated MCP adapter for the existing owner-scoped task commands."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, TypeVar

from anyio import to_thread
from fastapi import FastAPI
from mcp.server.auth.middleware.auth_context import (
    AuthContextMiddleware,
    get_access_token,
)
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.middleware.authentication import AuthenticationMiddleware

from app.api.task_mapping import task_response as _to_response
from app.container import Container
from app.core.config import AppConfig
from app.exceptions import BrainBuddyError
from app.schemas.tasks import (
    OpenTaskState,
    TaskCounts,
    TaskCreateRequest,
    TaskListResponse,
    TaskPriority,
    TaskResponse,
    TaskState,
    TaskTransitionRequest,
)

logger = logging.getLogger(__name__)
_Result = TypeVar("_Result")
_Key = Annotated[str, Field(min_length=1, max_length=200)]
_TaskId = Annotated[str, Field(min_length=1, max_length=200)]
_READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


class SessionTokenVerifier(TokenVerifier):
    """Use existing revocable sessions; MCP never accepts browser cookies."""

    def __init__(self, container: Container) -> None:
        self.container = container

    async def verify_token(self, token: str) -> AccessToken | None:
        def verify() -> AccessToken | None:
            user = self.container.auth_service.get_user_for_token(token)
            if user is None:
                return None
            admitted = self.container.feature_flag_service.is_effective(
                "task_mcp", user
            )
            return AccessToken(
                token=token,
                client_id=user.id,
                subject=user.id,
                scopes=["tasks"] if admitted else [],
            )

        return await to_thread.run_sync(verify)


def build_task_mcp(container: Container, config: AppConfig) -> FastMCP[None]:
    server: FastMCP[None] = FastMCP(
        "BrainBuddy Tasks",
        instructions=(
            "Manage the authenticated user's BrainBuddy tasks. Find a task before "
            "deleting it; never invent IDs. delete_task cancels an open task and "
            "removes it from active lists. Use a unique idempotency_key per mutation "
            "and reuse it with identical arguments when retrying."
        ),
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=config.mcp_allowed_hosts,
            allowed_origins=[],
        ),
    )

    async def run(tool: str, operation: Callable[[str], _Result]) -> _Result:
        token = get_access_token()
        if token is None:
            raise ToolError("Authentication required.")

        def execute() -> _Result:
            # Recheck revocation in the worker immediately before the operation.
            user = container.auth_service.get_user_for_token(token.token)
            if user is None:
                raise ToolError("Authentication required; sign in again.")
            if not container.feature_flag_service.is_effective("task_mcp", user):
                raise ToolError("Task MCP is unavailable for this account.")
            return operation(user.id)

        try:
            result = await to_thread.run_sync(execute)
        except (BrainBuddyError, ToolError) as exc:
            logger.warning(
                "mcp_tool_failed tool=%s reason=%s", tool, type(exc).__name__
            )
            raise ToolError(str(exc)) from None
        except Exception as exc:
            logger.error("mcp_tool_failed tool=%s reason=%s", tool, type(exc).__name__)
            raise ToolError(
                "Task operation unavailable. Retry mutations with the same "
                "idempotency_key and arguments."
            ) from None
        logger.info("mcp_tool_succeeded tool=%s", tool)
        return result

    @server.tool(annotations=_READ)
    async def list_tasks(
        q: str | None = None,
        state: TaskState | None = None,
        include_completed: bool = False,
        include_cancelled: bool = False,
        cursor: str | None = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> TaskListResponse:
        """Find your tasks by title; follow next_cursor while has_more is true."""

        def execute(owner_id: str) -> TaskListResponse:
            items, next_cursor, has_more, counts = container.task_service.list_tasks(
                owner_id=owner_id,
                state=state,
                project_id=None,
                tag_id=None,
                unassigned_project=False,
                include_completed=include_completed,
                include_cancelled=include_cancelled,
                q=q,
                cursor=cursor,
                limit=limit,
            )
            return TaskListResponse(
                items=[_to_response(task) for task in items],
                next_cursor=next_cursor,
                has_more=has_more,
                counts_by_state=TaskCounts(**counts),
            )

        return await run("list_tasks", execute)

    @server.tool(annotations=_READ)
    async def get_task(task_id: _TaskId) -> TaskResponse:
        """Read one of your tasks, including its revision, subtasks and comments."""

        def execute(owner_id: str) -> TaskResponse:
            task, subtasks, comments = container.task_service.get_task_detail(
                task_id, owner_id=owner_id
            )
            return _to_response(task, subtasks=subtasks, comments=comments)

        return await run("get_task", execute)

    @server.tool(annotations=_WRITE)
    async def create_task(
        title: Annotated[str, Field(min_length=1, max_length=500)],
        idempotency_key: _Key,
        details: Annotated[str | None, Field(max_length=20_000)] = None,
        state: OpenTaskState = "inbox",
        due_date: date | None = None,
        priority: TaskPriority = "none",
        project_id: str | None = None,
        tag_ids: list[str] | None = None,
        waiting_for: Annotated[str | None, Field(max_length=500)] = None,
    ) -> TaskResponse:
        """Create your task; default Inbox. Waiting tasks require waiting_for."""
        payload = TaskCreateRequest(
            title=title,
            details=details,
            state=state,
            due_date=due_date,
            priority=priority,
            project_id=project_id,
            tag_ids=tag_ids or [],
            waiting_for=waiting_for,
        )
        return await run(
            "create_task",
            lambda owner_id: _to_response(
                container.task_service.create_task(
                    payload, owner_id=owner_id, idempotency_key=idempotency_key
                )
            ),
        )

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    async def delete_task(
        task_id: _TaskId,
        expected_revision: Annotated[int, Field(ge=1)],
        idempotency_key: _Key,
    ) -> TaskResponse:
        """Soft-delete an open task by cancelling it. It remains recoverable.

        Read the current revision with get_task. A stale revision fails without
        changing the task. Repeat identical arguments/key after a network failure.
        """
        return await run(
            "delete_task",
            lambda owner_id: _to_response(
                container.task_service.transition_task(
                    task_id,
                    TaskTransitionRequest(
                        action="cancel", expected_revision=expected_revision
                    ),
                    owner_id=owner_id,
                    idempotency_key=idempotency_key,
                )
            ),
        )

    return server


def install_task_mcp(app: FastAPI, container: Container, config: AppConfig) -> None:
    """Mount MCP and compose its lifespan with existing startup/shutdown hooks."""
    server = build_task_mcp(container, config)
    mcp_app = server.streamable_http_app()
    mcp_app.add_middleware(RequireAuthMiddleware, required_scopes=["tasks"])
    mcp_app.add_middleware(AuthContextMiddleware)
    mcp_app.add_middleware(
        AuthenticationMiddleware,
        backend=BearerAuthBackend(SessionTokenVerifier(container)),
    )
    app.mount(f"{config.api_prefix}/mcp", mcp_app)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with original_lifespan(application), server.session_manager.run():
            yield

    app.router.lifespan_context = lifespan
