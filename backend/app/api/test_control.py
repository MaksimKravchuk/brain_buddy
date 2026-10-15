"""Test control API (spec 027, contracts/test-control.md; the 027-FR-022 seam).

Black-box suites seed data and run sweeps only through ``/api/__test__/``. The
prefix is mounted by ``install_test_control`` solely when ``BRAIN_BUDDY_ENV=test``
and a token is configured; everywhere else it is not routed at all (404 like any
unknown path). Every operation needs ``X-Test-Control-Token``.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.api.dependencies import get_container
from app.cli import seed_aged_task
from app.container import Container
from app.core.config import AppConfig, AppEnvironment
from app.exceptions import NotFoundError
from app.schemas.auth import Invite
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

CONTROL_HEADER = "X-Test-Control-Token"
_OPERATOR = "test-control"
TEST_CONTROL_PREFIX = "/__test__"


def require_test_control_token(
    request: Request,
    token: Annotated[str | None, Header(alias=CONTROL_HEADER)] = None,
) -> None:
    """Constant-time comparison against the configured secret; fail closed."""

    config: AppConfig = request.app.state.config
    expected = config.test_control_token
    if (
        config.environment is not AppEnvironment.TEST
        or expected is None
        or token is None
        or not hmac.compare_digest(
            token.encode("utf-8"), expected.get_secret_value().encode("utf-8")
        )
    ):
        raise HTTPException(status_code=401, detail="Test control token required.")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvitesRequest(_Body):
    count: int = Field(default=1, ge=1, le=100)


class AdminRequest(_Body):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class FlagRequest(_Body):
    mode: Literal["off", "on", "selected"]
    owners: list[EmailStr] = Field(default_factory=list)


class AgedTaskRequest(_Body):
    owner_email: EmailStr
    days: int = Field(ge=0, le=3650)
    title: str = Field(default="Renovate the bathroom", min_length=1, max_length=500)


router = APIRouter(
    prefix=TEST_CONTROL_PREFIX,
    tags=["test-control"],
    dependencies=[Depends(require_test_control_token)],
)


def _owner_id(container: Container, email: str) -> str:
    user = container.user_repo.get_by_email(email)
    if user is None:
        raise NotFoundError("account", "unknown")
    return user.id


@router.post("/invites")
def mint_invites(
    body: InvitesRequest, container: Container = Depends(get_container)
) -> dict[str, list[str]]:
    codes = [secrets.token_urlsafe(32) for _ in range(body.count)]
    for code in codes:
        container.invite_repo.create(Invite(code=code, created_at=utcnow()))
    return {"codes": codes}


@router.post("/admin", status_code=201)
def seed_admin(
    body: AdminRequest, container: Container = Depends(get_container)
) -> dict[str, str]:
    user = container.auth_service.seed_admin(
        email=str(body.email), password=body.password
    )
    return {"id": user.id, "email": user.email}


@router.put("/flags/{key}")
def set_flag(
    key: str, body: FlagRequest, container: Container = Depends(get_container)
) -> dict[str, object]:
    service = container.feature_flag_service
    wanted = {_owner_id(container, str(email)): str(email) for email in body.owners}
    service.set_mode(
        key,
        "selected_users" if body.mode == "selected" else body.mode,
        operator_id=_OPERATOR,
    )
    if body.mode == "selected":
        # Replace the cohort: the operation is idempotent under its inputs.
        view = next(
            f for f in service.describe(operator_id=_OPERATOR).flags if f.name == key
        )
        for member in view.selected_users:
            if member.account_id not in wanted:
                service.remove_selected_user(
                    key, member.account_id, operator_id=_OPERATOR
                )
        for email in wanted.values():
            service.add_selected_user(key, operator_id=_OPERATOR, email=email)
    return {"key": key, "mode": body.mode, "owners": len(wanted)}


def _sweep_review(container: Container) -> dict[str, int]:
    result = container.review_service.run_maintenance_sweep()
    return {
        "owners": result.owners,
        "parked": result.parked,
        "repaired": result.repaired,
        "closed": result.closed,
        "gap_floors": result.gap_floors,
        "snapshots_nulled": result.snapshots_nulled,
    }


def _sweep_retention(container: Container) -> dict[str, int]:
    return {
        "sync": container.sync_retention.run_retention_sweep(),
        "crt_receipts": container.crt_command_repo.purge_expired(),
    }


def _sweep_purge(container: Container) -> dict[str, int]:
    return {"accounts": container.account_service.purge_due_accounts()}


def _sweep_voice(container: Container) -> dict[str, int]:
    voice = container.voice_brain_dump_service
    return {
        "recovered_leases": voice.recover_due_provider_leases(),
        "advanced_runs": voice.run_due_brain_dump_provider_runs(),
        "resumed_commits": voice.recover_committing_operations(),
        "purged_raw_audio": voice.purge_expired_raw_audio(),
        "purged_working_artifacts": voice.purge_expired_working_artifacts(),
    }


def _sweep_agents(container: Container) -> dict[str, int]:
    return {"expired_runs": container.agent_relay_service.run_retention_sweep()}


_SWEEPS = {
    "review": _sweep_review,
    "retention": _sweep_retention,
    "purge": _sweep_purge,
    "voice": _sweep_voice,
    "agents": _sweep_agents,
}


@router.post("/sweeps/{name}")
def run_sweep(
    name: str, container: Container = Depends(get_container)
) -> dict[str, int]:
    sweep = _SWEEPS.get(name)
    if sweep is None:
        raise NotFoundError("sweep", name)
    return sweep(container)


@router.post("/review/aged-task", status_code=201)
def post_aged_task(
    body: AgedTaskRequest, container: Container = Depends(get_container)
) -> dict[str, str]:
    owner_id = _owner_id(container, str(body.owner_email))
    task_id = seed_aged_task(
        container, owner_id=owner_id, days=body.days, title=body.title
    )
    return {"task_id": task_id}


@router.get("/owners/{email}/tasks")
def owner_tasks(
    email: str, container: Container = Depends(get_container)
) -> dict[str, list[dict[str, object]]]:
    owner_id = _owner_id(container, email)
    tasks = container.task_repo.list_for_owner(owner_id=owner_id)
    return {
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "state": task.state,
                "revision": task.revision,
            }
            for task in tasks
        ]
    }


@router.post("/reconcile")
def reconcile(container: Container = Depends(get_container)) -> dict[str, int]:
    """Python-side counters: pending CRT command receipts brought to a verdict."""

    return {"reconciled": container.crt_command_service.reconcile_pending_commands()}


def install_test_control(app: FastAPI, config: AppConfig) -> bool:
    """Mount the router only in the test environment, and only with a token."""

    if config.environment is not AppEnvironment.TEST:
        logger.info("Test control is disabled.")
        return False
    if config.test_control_token is None:
        logger.warning(
            "Test control is disabled: BRAIN_BUDDY_TEST_CONTROL_TOKEN is not set."
        )
        return False
    app.include_router(router, prefix=config.api_prefix)
    logger.warning("Test control is ENABLED (BRAIN_BUDDY_ENV=test).")
    return True
