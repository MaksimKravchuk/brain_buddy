"""Operational CLI for the Brain Buddy backend.

Run via ``python -m app.cli <command>`` inside the backend container.
``create-invite`` mints a one-shot invite code that unlocks signup on
``POST /api/auth/signup``; ``purge-due-accounts`` hard-deletes accounts
whose deletion grace period has elapsed (the maintenance sweep does the
same on a timer — this is the manual/ops entrypoint). ``review-metrics``
prints the weekly-review read-out (spec 020): aggregates only.
"""

from __future__ import annotations

import secrets
import statistics
import uuid
from datetime import date, datetime, timedelta

import typer

from app.container import build_container
from app.core import get_config
from app.core.config import AppConfig, AppEnvironment
from app.modules.tasks.review_flow import ReviewMetrics
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


# Minimum samples confirmed by the owner on 2026-10-06 (plan "Post-release
# acceptance"): below them a figure reads "insufficient".
SC003_MIN_ANSWERED = 6
SC004_MIN_REVIEWS = 4
SC005_MIN_SHOWN = 20


def _share(part: int, whole: int, what: str, minimum: int | None) -> str:
    """``71% (5 of 7 <what>; n=7)``; below ``minimum`` (or none) not a share."""

    if minimum is not None and whole < minimum:
        return f"insufficient (n={whole} {what}; minimum {minimum})"
    if whole == 0:
        return "none (n=0)"
    return f"{100 * part / whole:.0f}% ({part} of {whole} {what}; n={whole})"


def _median_minutes(seconds: list[int]) -> str:
    if len(seconds) < SC004_MIN_REVIEWS:
        return (
            f"insufficient (n={len(seconds)} completed reviews; "
            f"minimum {SC004_MIN_REVIEWS})"
        )
    return f"{statistics.median(seconds) / 60:.1f} (n={len(seconds)} completed reviews)"


def format_review_metrics(metrics: ReviewMetrics, since: date) -> list[str]:
    """The read-out lines: aggregates with their sample sizes, nothing else."""

    return [
        f"review-metrics since {since.isoformat()} ({metrics.weeks} weeks)",
        "SC-001 weeks with a counted review: "
        f"{metrics.weeks_with_counted_review} of {metrics.weeks} "
        f"(n={metrics.weeks} weeks)",
        'SC-003 clear start "yes": '
        + _share(
            metrics.answered_yes,
            metrics.answered_reviews,
            "answered reviews",
            SC003_MIN_ANSWERED,
        ),
        "SC-004 median active minutes, quick: "
        + _median_minutes(metrics.active_seconds_quick),
        "SC-004 median active minutes, full: "
        + _median_minutes(metrics.active_seconds_full),
        "SC-005 cloud proposals accepted: "
        + _share(
            metrics.cloud_accepted,
            metrics.shown_requests,
            "shown requests",
            SC005_MIN_SHOWN,
        ),
        "SC-005 on-device proposals accepted, upper bound: "
        + _share(
            metrics.device_accepted,
            metrics.device_decisions,
            "decisions with on-device proposals",
            None,
        ),
        "Parks returned: "
        + _share(metrics.parks_returned, metrics.parks, "parks", None),
    ]


@app.command("review-metrics")
def review_metrics(
    owner: str = typer.Option(..., help="The owner's user id."),
    since: datetime = typer.Option(
        ..., formats=["%Y-%m-%d"], help="First day (UTC) of the read-out window."
    ),
) -> None:
    """Spec 020 real-use read-out: content-free aggregates with sample sizes.

    Read-only; run weekly in the production backend container (plan
    "Post-release acceptance"). Prints no title, note, reason or id.
    """

    container = build_container(get_config())
    flow = container.review_flow_service
    first_day = since.date()
    if first_day > flow.clock().date():
        typer.echo("--since must not be in the future.", err=True)
        raise typer.Exit(code=2)
    metrics = flow.metrics(owner, since=first_day)
    for line in format_review_metrics(metrics, first_day):
        typer.echo(line)


if __name__ == "__main__":  # pragma: no cover
    app()
