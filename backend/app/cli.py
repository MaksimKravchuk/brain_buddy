"""Operational CLI for the Brain Buddy backend.

Run via ``python -m app.cli <command>`` inside the backend container.
``create-invite`` mints a one-shot invite code that unlocks signup on
``POST /api/auth/signup``; ``purge-due-accounts`` hard-deletes accounts
whose deletion grace period has elapsed (the maintenance sweep does the
same on a timer — this is the manual/ops entrypoint).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

import typer

from app.container import build_container
from app.core import get_config
from app.core.config import AppConfig, AppEnvironment
from app.schemas.auth import Invite
from app.schemas.review import ExplainerAcknowledgeRequest
from app.schemas.tasks import TaskCreateRequest
from app.utils.time import utcnow

app = typer.Typer(help="Brain Buddy operational commands.")


@app.callback()
def _main() -> None:
    """Brain Buddy operational CLI.

    Kept as an explicit callback so Typer stays in multi-command mode even
    when only one subcommand is registered. Without this, Typer would
    collapse the single `create-invite` command into a no-name entrypoint
    and reject the literal ``create-invite`` argument from the CLI.
    """


def _generate_invite_code() -> str:
    # URL-safe, filesystem-safe, 256 bits of entropy.
    return secrets.token_urlsafe(32)


@app.command("create-invite")
def create_invite() -> None:
    """Mint a new invite code and print it to stdout."""

    config = get_config()
    container = build_container(config)

    code = _generate_invite_code()
    invite = Invite(code=code, created_at=utcnow())
    container.invite_repo.create(invite)
    typer.echo(code)


@app.command("purge-due-accounts")
def purge_due_accounts() -> None:
    """Hard-delete accounts whose deletion grace period has elapsed."""

    config = get_config()
    container = build_container(config)

    purged = container.account_service.purge_due_accounts()
    typer.echo(f"Purged {purged} account(s).")


def _require_test_environment() -> AppConfig:
    """The review seams exist for the TEST stack only (spec 020, research R21)."""

    config = get_config()
    if config.environment is not AppEnvironment.TEST:
        typer.echo("This command runs only when BRAIN_BUDDY_ENV=test.", err=True)
        raise typer.Exit(code=2)
    return config


@app.command("review-seed-aged-task")
def review_seed_aged_task(
    email: str = typer.Option(..., help="Account that owns the task."),
    days: int = typer.Option(..., min=0, help="Age of the formulation in days."),
    title: str = typer.Option("Renovate the bathroom", help="Task title."),
) -> None:
    """TEST only: a Next task whose formulation started DAYS ago; prints its id.

    The owner is activated first (the explainer acknowledgement) when it is
    not yet, so the seeded age is not clamped away (FR-016).
    """

    container = build_container(_require_test_environment())
    user = container.user_repo.get_by_email(email)
    if user is None:
        typer.echo("No account with that email.", err=True)
        raise typer.Exit(code=1)
    review = container.review_service
    if review.settings_for(user.id).activated_at is None:
        review.acknowledge_explainer(
            ExplainerAcknowledgeRequest(),
            owner_id=user.id,
            idempotency_key=f"cli-review-activate-{uuid.uuid4()}",
        )
    task = container.task_service.create_task(
        TaskCreateRequest(title=title, state="next"),
        owner_id=user.id,
        idempotency_key=f"cli-review-seed-{uuid.uuid4()}",
    )
    started = container.task_service.clock() - timedelta(days=days)
    with container.task_repo.command_lock(user.id):
        container.task_repo.save(
            task.model_copy(update={"formulation_started_at": started})
        )
    typer.echo(task.id)


@app.command("review-run-sweep")
def review_run_sweep() -> None:
    """TEST only: one weekly-review maintenance sweep run; prints its counts."""

    container = build_container(_require_test_environment())
    # The same call ``app.main._run_review_maintenance_sweep`` wraps; importing
    # ``app.main`` here would build a second ASGI app and run its startup sweep.
    try:
        result = container.review_service.run_maintenance_sweep()
    except Exception as exc:  # noqa: BLE001 - reported by type, never by text
        typer.echo(f"Review sweep failed: {type(exc).__name__}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(
        f"owners={result.owners} parked={result.parked} repaired={result.repaired} "
        f"closed={result.closed} gap_floors={result.gap_floors} "
        f"snapshots_nulled={result.snapshots_nulled}"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
