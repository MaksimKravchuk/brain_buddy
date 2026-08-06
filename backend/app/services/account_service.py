"""Self-serve account management: profile, credentials, and GDPR data rights.

Password hashing and verification stay inside `AuthService` — this service
only orchestrates re-auth checks, repository writes, and session revocation.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import zipfile
from contextlib import suppress
from datetime import datetime, timedelta
from typing import IO, Any

from app.exceptions import (
    ConflictError,
    NotFoundError,
    ReauthFailedError,
    ValidationFailure,
)
from app.modules.tasks import TaskRepository
from app.repositories import (
    InviteRepository,
    SessionRepository,
    UserRepository,
    ValidationRepository,
    VersionRepository,
)
from app.repositories.validation import VALIDATION_DIRNAME
from app.repositories.version import _slugify_version_id
from app.schemas.auth import User
from app.services.auth_service import ACCOUNT_DELETION_GRACE, AuthService
from app.services.tree_service import TreeService
from app.utils.time import utcnow
from app.workflows.voice_brain_dump.repository import OperationRepository

# Accounts below this size are zipped fully in memory; anything larger
# (voice-heavy accounts with raw audio) spools to a temp file on disk.
_EXPORT_SPOOL_MAX_BYTES = 8 * 1024 * 1024

logger = logging.getLogger(__name__)

DELETION_GRACE = ACCOUNT_DELETION_GRACE

# The one message every failed email change returns. A conflicting address
# must be indistinguishable from any other rejection, or the endpoint becomes
# an account-enumeration oracle.
_EMAIL_REJECTED_MESSAGE = "That email address can't be used."


class AccountService:
    """Coordinate account reads and mutations for the authenticated owner."""

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        session_repo: SessionRepository,
        invite_repo: InviteRepository,
        tree_service: TreeService,
        version_repo: VersionRepository,
        validation_repo: ValidationRepository,
        task_repo: TaskRepository,
        voice_operation_repo: OperationRepository,
        auth_service: AuthService,
        deletion_grace: timedelta = DELETION_GRACE,
    ) -> None:
        self.user_repo = user_repo
        self.session_repo = session_repo
        self.invite_repo = invite_repo
        self.tree_service = tree_service
        self.version_repo = version_repo
        self.validation_repo = validation_repo
        self.task_repo = task_repo
        self.voice_operation_repo = voice_operation_repo
        self.auth_service = auth_service
        self.deletion_grace = deletion_grace

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_current_password(self, user: User, raw: str) -> None:
        if not self.auth_service.verify_password(user, raw):
            raise ReauthFailedError()

    def purge_at_for(self, user: User) -> datetime | None:
        if user.deletion_requested_at is None:
            return None
        return user.deletion_requested_at + self.deletion_grace

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_account(self, user: User) -> User:
        """Return a fresh read of the caller's account record."""

        fresh = self.user_repo.get_by_id(user.id)
        return fresh if fresh is not None else user

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def update_profile(self, user: User, *, display_name: str) -> User:
        """Set (or clear, via empty string) the display name."""

        cleaned = display_name.strip()
        updated = user.model_copy(update={"display_name": cleaned or None})
        self.user_repo.save(updated)
        return updated

    def change_email(
        self, user: User, *, new_email: str, current_password: str
    ) -> User:
        """Move the account to a new address after re-checking the password.

        A conflict with another account is collapsed into the same generic
        `ValidationFailure` as any other rejection (see module note).
        """

        self._require_current_password(user, current_password)
        try:
            return self.user_repo.update_email(user.id, new_email)
        except ConflictError as exc:
            raise ValidationFailure(_EMAIL_REJECTED_MESSAGE) from exc

    def change_password(
        self,
        user: User,
        *,
        current_password: str,
        new_password: str,
        keep_token_hash: str | None,
    ) -> None:
        """Rotate the password and revoke every other session.

        The caller's own session (`keep_token_hash`) survives so the change
        doesn't log the user out of the device they made it from.
        """

        self._require_current_password(user, current_password)
        self.auth_service.validate_password_format(new_password)
        updated = user.model_copy(
            update={"password_hash": self.auth_service.hash_password(new_password)}
        )
        self.user_repo.save(updated)
        revoked = self.session_repo.delete_all_for_user(user.id, keep=keep_token_hash)
        logger.info(
            "Password changed for %s; revoked %s other session(s)", user.id, revoked
        )

    # ------------------------------------------------------------------
    # Data export (GDPR access & portability)
    # ------------------------------------------------------------------

    def export_account_data(self, user: User) -> tuple[str, IO[bytes]]:
        """Assemble everything the account owns into one ZIP archive.

        Returns ``(filename, stream)`` with the stream rewound and ready to
        send. JSON documents are pretty-printed for human readability; raw
        voice audio (if still inside its retention window) is copied in as
        the original binary chunks. Secrets — the password hash, session
        records — and transient idempotency records are deliberately
        excluded; the manifest says so.
        """

        now = utcnow()
        filename = f"brain-buddy-export-{user.id}-{now:%Y%m%d}.zip"
        spool: IO[bytes] = tempfile.SpooledTemporaryFile(  # noqa: SIM115 - returned
            max_size=_EXPORT_SPOOL_MAX_BYTES
        )
        with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as archive:

            def write_json(name: str, payload: Any) -> None:
                archive.writestr(
                    name,
                    json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
                )

            account = user.model_dump(mode="json")
            account.pop("password_hash", None)
            write_json("account.json", account)

            tree_count = 0
            for entry in self.tree_service.list_trees(owner_id=user.id):
                tree_count += 1
                tree = self.tree_service.get_tree_for_owner(entry.id, owner_id=user.id)
                write_json(f"trees/{entry.id}/tree.json", tree.model_dump(mode="json"))
                for version in self.version_repo.list_for_tree(entry.id):
                    slug = _slugify_version_id(version.id)
                    write_json(
                        f"trees/{entry.id}/versions/{slug}.json",
                        version.model_dump(mode="json"),
                    )
                validation_dir = self.validation_repo.resolve(
                    entry.id, VALIDATION_DIRNAME
                )
                if validation_dir.is_dir():
                    for history_path in sorted(validation_dir.glob("*.json")):
                        node_id = history_path.stem
                        entries = self.validation_repo.load_history(entry.id, node_id)
                        write_json(
                            f"trees/{entry.id}/validation/{node_id}.json",
                            [item.model_dump(mode="json") for item in entries],
                        )

            tasks = self.task_repo.list_for_owner(owner_id=user.id)
            write_json(
                "tasks/tasks.json", [task.model_dump(mode="json") for task in tasks]
            )
            write_json(
                "tasks/projects.json",
                [
                    project.model_dump(mode="json")
                    for project in self.task_repo.list_projects_for_owner(
                        owner_id=user.id
                    )
                ],
            )
            write_json(
                "tasks/tags.json",
                [
                    tag.model_dump(mode="json")
                    for tag in self.task_repo.list_tags_for_owner(owner_id=user.id)
                ],
            )
            subtasks: list[Any] = []
            comments: list[Any] = []
            for task in tasks:
                subtasks.extend(
                    item.model_dump(mode="json")
                    for item in self.task_repo.list_subtasks(
                        owner_id=user.id, task_id=task.id
                    )
                )
                comments.extend(
                    item.model_dump(mode="json")
                    for item in self.task_repo.list_comments(
                        owner_id=user.id, task_id=task.id
                    )
                )
            write_json("tasks/subtasks.json", subtasks)
            write_json("tasks/comments.json", comments)

            operations = self.voice_operation_repo.list_brain_dump_operations_for_owner(
                owner_id=user.id
            )
            write_json(
                "voice/operations.json",
                [operation.model_dump(mode="json") for operation in operations],
            )
            audio_chunks = 0
            for operation in operations:
                for chunk in operation.audio_chunks:
                    chunk_path = self.voice_operation_repo.brain_dump_audio_chunk_path(
                        user.id, operation.id, chunk.chunk_number, chunk.sha256
                    )
                    if not chunk_path.is_file():
                        continue
                    audio_chunks += 1
                    member = (
                        f"voice/audio/{operation.id}/"
                        f"{chunk.chunk_number:06d}-{chunk.sha256}.bin"
                    )
                    with (
                        chunk_path.open("rb") as source,
                        archive.open(member, "w") as target,
                    ):
                        shutil.copyfileobj(source, target)

            write_json(
                "export_manifest.json",
                {
                    "generated_at": now.isoformat(),
                    "format": "brain-buddy-account-export/v1",
                    "account_id": user.id,
                    "counts": {
                        "trees": tree_count,
                        "tasks": len(tasks),
                        "voice_operations": len(operations),
                        "voice_audio_chunks": audio_chunks,
                    },
                    "excluded": [
                        "password hash (secret, not portable personal data)",
                        "session records (revoked secrets)",
                        "idempotency records (transient request-dedup copies "
                        "of data already exported)",
                    ],
                },
            )

        spool.seek(0)
        logger.info("Assembled account export for %s", user.id)
        return filename, spool

    # ------------------------------------------------------------------
    # Deletion lifecycle (GDPR erasure with a cancellable grace period)
    # ------------------------------------------------------------------

    def request_deletion(self, user: User, *, current_password: str) -> User:
        """Schedule the account for purge and revoke every session.

        Idempotent: a repeat request keeps the original timestamp so the
        purge date never moves later. Logging back in before `purge_at`
        cancels the deletion (see `AuthService.login`).
        """

        self._require_current_password(user, current_password)
        if user.deletion_requested_at is None:
            user = user.model_copy(update={"deletion_requested_at": utcnow()})
            self.user_repo.save(user)
        revoked = self.session_repo.delete_all_for_user(user.id)
        logger.info(
            "Account deletion requested for %s (purge at %s); revoked %s session(s)",
            user.id,
            self.purge_at_for(user),
            revoked,
        )
        return user

    def purge_due_accounts(self, *, now: datetime | None = None) -> int:
        """Hard-delete every account whose grace period has elapsed."""

        current = now if now is not None else utcnow()
        purged = 0
        for user in self.user_repo.list_users():
            if user.deletion_requested_at is None:
                continue
            if user.deletion_requested_at + self.deletion_grace > current:
                continue
            self.purge_account(user.id)
            purged += 1
        return purged

    def purge_account(self, user_id: str) -> None:
        """Erase every trace of an account. Idempotent and crash-safe.

        The user record is deleted last: if any earlier step dies, the
        account is still past-due on the next sweep pass and the whole purge
        re-runs. Every step tolerates already-deleted data.
        """

        self.session_repo.delete_all_for_user(user_id)
        self.voice_operation_repo.delete_all_for_owner(owner_id=user_id)
        self.task_repo.delete_all_for_owner(owner_id=user_id)
        for entry in self.tree_service.list_trees(owner_id=user_id):
            with suppress(NotFoundError):
                self.tree_service.delete_tree(entry.id, owner_id=user_id)
        self.invite_repo.scrub_user(user_id)
        self.user_repo.delete(user_id)
        logger.info("Purged account %s and all owned data", user_id)


__all__ = ["AccountService", "DELETION_GRACE"]
