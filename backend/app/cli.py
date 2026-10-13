"""Operational CLI for the Brain Buddy backend.

Run via ``python -m app.cli <command>`` inside the backend container.
``create-invite`` mints a one-shot invite code that unlocks signup on
``POST /api/auth/signup``; ``purge-due-accounts`` hard-deletes accounts
whose deletion grace period has elapsed (the maintenance sweep does the
same on a timer — this is the manual/ops entrypoint). ``review-metrics``
prints the weekly-review read-out (spec 020): aggregates only.
``sync-restore-control-plane`` finishes a task-DB restore (spec 026 PR-52).
"""

from __future__ import annotations

import json
import secrets
import statistics
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta

import typer

from app.container import Container, build_container
from app.core import get_config
from app.core.config import AppConfig, AppEnvironment
from app.exceptions import BrainBuddyError
from app.modules.tasks.review_flow import ReviewMetrics
from app.modules.tasks.sync.control_ledger import LedgerIncomplete
from app.modules.tasks.sync.restore import (
    RestoreNotReady,
    reopen,
    restore_control_plane,
)
from app.schemas.auth import Invite
from app.schemas.review import ExplainerAcknowledgeRequest
from app.schemas.tasks import TaskCreateRequest
from app.services.auth_migration import AuthMigration
from app.services.auth_secret_box import AuthSecretBox, AuthSecretError
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


@app.command("migrate-auth")
def migrate_auth(
    writers_stopped: bool = typer.Option(
        False,
        "--writers-stopped",
        help="Acknowledge every legacy authentication writer is stopped.",
    ),
) -> None:
    """Validate and import legacy accounts/sessions; resume committed cleanup."""
    config = get_config()
    try:
        secret_box = AuthSecretBox.from_settings(config.modern_auth)
    except AuthSecretError:
        secret_box = None
    migration = AuthMigration(config.data_dir, secret_box)
    try:
        result = migration.migrate(writers_stopped=writers_stopped)
    except BrainBuddyError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(asdict(result), sort_keys=True))


class _ContainerRestoreEffects:
    """Restore-time purge and session revocation through the real services."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def purge_owner(self, owner_id: str) -> None:
        self._container.account_service.purge_account(owner_id)

    def revoke_sessions(self, owner_id: str) -> None:
        self._container.session_repo.delete_all_for_user(owner_id)


@app.command("sync-restore-control-plane")
def sync_restore_control_plane(
    backup_taken_at: str | None = typer.Option(
        None, help="UTC time of the restored task backup (ISO 8601, with offset)."
    ),
    writers_stopped: bool = typer.Option(
        False, "--writers-stopped", help="Acknowledge the backend is stopped."
    ),
    reopen_access: bool = typer.Option(
        False, "--reopen", help="Admit owners again after replay."
    ),
    external_effects_reconciled: bool = typer.Option(
        False,
        "--external-effects-reconciled",
        help="With --reopen: provider/mail effects were reconciled separately.",
    ),
) -> None:
    """Replay the control ledger over a restored task DB, or reopen access.

    Run once with --backup-taken-at right after restoring tasks.sqlite3 and
    again with --reopen --external-effects-reconciled when reconciliation is
    done. Access stays closed if completeness cannot be proven.
    """

    if not writers_stopped:
        typer.echo("Refusing: pass --writers-stopped.", err=True)
        raise typer.Exit(2)
    container = build_container(get_config())
    db_path = container.task_repo.db_path
    ledger = container.control_ledger
    try:
        if reopen_access:
            reopen(
                db_path,
                ledger,
                external_effects_reconciled=external_effects_reconciled,
            )
            typer.echo("Access reopened.")
            return
        try:
            taken = datetime.fromisoformat(backup_taken_at or "")
        except ValueError:
            taken = None
        if taken is None or taken.tzinfo is None:
            typer.echo("--backup-taken-at needs an ISO time with offset.", err=True)
            raise typer.Exit(2)
        report = restore_control_plane(
            db_path,
            ledger,
            _ContainerRestoreEffects(container),
            backup_taken_at=taken,
            now=utcnow(),
        )
    except (LedgerIncomplete, RestoreNotReady) as error:
        typer.echo(f"Access stays closed: {error}", err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(asdict(report), sort_keys=True))


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
    # The backdate is a Tasks write: through the review service it publishes with
    # the unit when the sync boundary is wired (spec 026 PR-29), and is otherwise
    # the plain owner-locked save.
    container.review_service.internal_write(
        user.id,
        "internal.test_seed_aged_task",
        f"cli-review-seed-age-{uuid.uuid4()}",
        lambda: container.task_repo.save(
            task.model_copy(update={"formulation_started_at": started})
        ),
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


def _sc005_cloud_label(metrics: ReviewMetrics, since: date) -> str:
    """Names the window the cloud share used when it is shorter than ``since``."""

    if metrics.sc005_since == since:
        return "SC-005 cloud proposals accepted: "
    return (
        f"SC-005 cloud proposals accepted since {metrics.sc005_since.isoformat()} "
        "(navigator usage is kept 35 days): "
    )


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
        _sc005_cloud_label(metrics, since)
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
