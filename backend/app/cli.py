"""Operational CLI for the Brain Buddy backend.

Run via ``python -m app.cli <command>`` inside the backend container.
``create-invite`` mints a one-shot invite code that unlocks signup on
``POST /api/auth/signup``; ``purge-due-accounts`` hard-deletes accounts
whose deletion grace period has elapsed (the maintenance sweep does the
same on a timer — this is the manual/ops entrypoint).
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict

import typer

from app.container import build_container
from app.core import get_config
from app.exceptions import BrainBuddyError
from app.schemas.auth import Invite
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


if __name__ == "__main__":  # pragma: no cover
    app()
