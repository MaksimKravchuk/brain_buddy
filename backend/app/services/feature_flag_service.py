"""Resolve effective rollout flags from the runtime overlay, then the baseline.

**Overlay, do not replace.** :class:`FeatureFlagSettings` keeps computing exactly
what it computes today. This service asks the runtime document whether a
**managed** flag has an entry and, only when it does, answers from that entry
alone — never blending the two sources (010-FR-003). Everything else, including
`delivery_canary` and `external_agent_relay`, falls through to the environment
computation untouched (010-FR-002, DD-1). Delete the overlay and the old answer
is what remains, which is what makes 010-SC-003 provable by construction.

Every operator mutation emits exactly one dedicated, content-free record, and
every cohort-resolving read emits exactly one aggregate record (010-FR-006,
DD-10). A mutation's returned view deliberately does **not** emit the aggregate
record: that would make a mutation produce two of this feature's own records
where FR-006 requires one.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from app.core.config import AppConfig
from app.core.logging import get_correlation_id
from app.exceptions import BrainBuddyError, ValidationFailure
from app.repositories import UserRepository
from app.repositories.feature_flag import (
    MANAGED_FLAGS,
    DegradedRuntimeFlagsError,
    FeatureFlagOverrideRepository,
    FlagMode,
    FlagOverride,
    MutationFn,
    RuntimeOverlay,
)
from app.schemas.auth import User
from app.services.admin_service import ACCOUNT_ID_PATTERN, AdminService

logger = logging.getLogger(__name__)

SOURCE_RUNTIME = "runtime"
SOURCE_DEPLOY_DEFAULT = "deploy_default"

#: Placeholder used wherever a record has no attributable account id. Mirrors
#: `AdminService.find_account`'s own "-" so the two records read alike.
_NO_ACCOUNT = "-"


class SelectedUserNotFoundError(BrainBuddyError):
    """An add named no existing account: refused, and nobody is added (DD-7).

    Deliberately its own type rather than `NotFoundError`, whose payload echoes
    the submitted identifier back to the caller — the submitted key may be an
    email, which must never be reflected.
    """

    def __init__(self) -> None:
        super().__init__("No account found.")


@dataclass(frozen=True, slots=True)
class SelectedUserView:
    """One cohort row: the stored ID, plus the email resolved live at read time.

    `email` is `None` when the stored ID no longer resolves to an account. The
    row still renders and stays removable until purge scrubs it (010-FR-007).
    """

    account_id: str
    email: str | None


@dataclass(frozen=True, slots=True)
class ManagedFlagView:
    """One managed flag as the operator screen needs it (DD-3's three fields)."""

    name: str
    override_mode: FlagMode | None
    source: str
    deploy_default_state: str
    selected_users: tuple[SelectedUserView, ...]


@dataclass(frozen=True, slots=True)
class RuntimeFlagsView:
    """The operator view of every managed flag, plus the store's health."""

    degraded: bool
    flags: tuple[ManagedFlagView, ...]


class FeatureFlagService:
    """The single authority for whether a managed flag is effective for a user."""

    def __init__(
        self,
        *,
        repository: FeatureFlagOverrideRepository,
        config: AppConfig,
        user_repo: UserRepository,
        admin_service: AdminService,
    ) -> None:
        self.repository = repository
        self.config = config
        self.user_repo = user_repo
        self.admin_service = admin_service
        self._cached: RuntimeOverlay | None = None
        self._cache_key: tuple[int, int] | None = None

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def effective_flags(self, user: User) -> dict[str, bool]:
        """The member-facing flag payload, with managed flags overlaid.

        The key set is exactly `KNOWN_FEATURE_FLAGS`, unchanged (010-FR-008):
        this only replaces two values inside the dict the config already built.
        """

        resolved = self.config.feature_flags.effective_flags(user.email)
        overlay = self._overlay()
        for name in MANAGED_FLAGS:
            entry = overlay.flags.get(name)
            if entry is not None:
                resolved[name] = _entry_admits(entry, user)
        return resolved

    def is_effective(self, name: str, user: User) -> bool:
        """Whether one flag is effective for one user. Fail closed if unknown."""

        return self.effective_flags(user).get(name, False)

    # ------------------------------------------------------------------
    # Operator reads
    # ------------------------------------------------------------------

    def describe(self, *, operator_id: str) -> RuntimeFlagsView:
        """The operator view, plus the one aggregate audit record (DD-10)."""

        view = self._view(self._overlay())
        resolved = sum(
            1
            for flag in view.flags
            for member in flag.selected_users
            if member.email is not None
        )
        logger.info(
            "Runtime flag read: operator=%s correlation=%s flags=%s "
            "resolved_accounts=%s",
            operator_id,
            get_correlation_id(),
            len(view.flags),
            resolved,
        )
        return view

    # ------------------------------------------------------------------
    # Operator mutations
    # ------------------------------------------------------------------

    def set_mode(
        self, flag: str, mode: FlagMode | str, *, operator_id: str
    ) -> RuntimeFlagsView:
        """Put one managed flag into one of the three runtime-override modes."""

        action = "set_mode"
        self._require_managed(flag, operator_id=operator_id, action=action)
        resolved_mode = self._require_mode(flag, mode, operator_id=operator_id)

        def _apply(current: dict[str, FlagOverride]) -> dict[str, FlagOverride]:
            existing = current.get(flag)
            # DD-6: a cohort is retained, not cleared, by a mode change.
            retained = existing.selected_users if existing is not None else ()
            current[flag] = FlagOverride(mode=resolved_mode, selected_users=retained)
            return current

        try:
            overlay = self._mutate(_apply)
        except DegradedRuntimeFlagsError:
            self._record(
                action, flag=flag, operator_id=operator_id, outcome="refused_degraded"
            )
            raise
        except OSError:
            self._record(
                action, flag=flag, operator_id=operator_id, outcome="write_failed"
            )
            raise
        self._record(action, flag=flag, operator_id=operator_id)
        return self._view(overlay)

    def clear_override(self, flag: str, *, operator_id: str) -> RuntimeFlagsView:
        """Delete one managed flag's whole runtime entry, cohort included (DD-3)."""

        action = "clear_override"
        self._require_managed(flag, operator_id=operator_id, action=action)

        try:
            overlay = self.repository.clear(flag)
        except DegradedRuntimeFlagsError:
            self._record(
                action, flag=flag, operator_id=operator_id, outcome="refused_degraded"
            )
            raise
        except OSError:
            self._record(
                action, flag=flag, operator_id=operator_id, outcome="write_failed"
            )
            raise
        self._invalidate()
        self._record(action, flag=flag, operator_id=operator_id)
        return self._view(overlay)

    def add_selected_user(
        self,
        flag: str,
        *,
        operator_id: str,
        account_id: str | None = None,
        email: str | None = None,
    ) -> RuntimeFlagsView:
        """Add one exactly-matched account to a SELECTED_USERS cohort (010-FR-007)."""

        action = "add_selected_user"
        self._require_managed(flag, operator_id=operator_id, action=action)
        found = self.admin_service.find_account(
            operator_id=operator_id, account_id=account_id, email=email
        )
        if found is None:
            self._record(
                action, flag=flag, operator_id=operator_id, outcome="no_account_found"
            )
            raise SelectedUserNotFoundError()

        def _apply(current: dict[str, FlagOverride]) -> dict[str, FlagOverride]:
            entry = self._selected_users_entry(current, flag)
            # Lock order matches purge (feature-flag lock, then user read):
            # `found` was resolved before this lock was taken, so an account
            # purge racing this add may have scrubbed and deleted it in the
            # meantime. Re-checking existence here, under the same lock the
            # write commits under, is what stops that purge's deletion from
            # being resurrected by this cohort write (010-FR-007, DD-13).
            #
            # `AccountService.purge_account` scrubs this cohort *first* and
            # deletes the user record *last*, so the account can still
            # resolve here even though its membership has already been
            # erased. `deletion_requested_at` is the durable, existing signal
            # that a purge for this account is due or in flight; refusing on
            # it closes that window without a second lock or a tombstone.
            fresh = self.user_repo.get_by_id(found.id)
            if fresh is None or fresh.deletion_requested_at is not None:
                raise SelectedUserNotFoundError()
            current[flag] = FlagOverride(
                mode=entry.mode,
                selected_users=tuple(sorted({*entry.selected_users, found.id})),
            )
            return current

        try:
            overlay = self._mutate(_apply)
        except DegradedRuntimeFlagsError:
            self._record(
                action, flag=flag, operator_id=operator_id, outcome="refused_degraded"
            )
            raise
        except ValidationFailure:
            self._record(
                action,
                flag=flag,
                operator_id=operator_id,
                outcome="refused_mode_not_selected_users",
            )
            raise
        except SelectedUserNotFoundError:
            self._record(
                action, flag=flag, operator_id=operator_id, outcome="no_account_found"
            )
            raise
        except OSError:
            self._record(
                action,
                flag=flag,
                operator_id=operator_id,
                account=found.id,
                outcome="write_failed",
            )
            raise
        self._record(action, flag=flag, operator_id=operator_id, account=found.id)
        return self._view(overlay)

    def remove_selected_user(
        self, flag: str, account_id: str, *, operator_id: str
    ) -> RuntimeFlagsView:
        """Remove one stored account ID. Idempotent by ID, no lookup at all (DD-7)."""

        action = "remove_selected_user"
        self._require_managed(flag, operator_id=operator_id, action=action)
        # The path-supplied id is raw request input, so it is named in a
        # record only when it is account-ID shaped and can never be an email
        # (DD-10).
        record_account = (
            account_id if ACCOUNT_ID_PATTERN.fullmatch(account_id) else None
        )

        def _apply(current: dict[str, FlagOverride]) -> dict[str, FlagOverride]:
            entry = self._selected_users_entry(current, flag)
            current[flag] = FlagOverride(
                mode=entry.mode,
                selected_users=tuple(
                    member for member in entry.selected_users if member != account_id
                ),
            )
            return current

        try:
            overlay = self._mutate(_apply)
        except DegradedRuntimeFlagsError:
            self._record(
                action, flag=flag, operator_id=operator_id, outcome="refused_degraded"
            )
            raise
        except ValidationFailure:
            self._record(
                action,
                flag=flag,
                operator_id=operator_id,
                outcome="refused_mode_not_selected_users",
            )
            raise
        except OSError:
            self._record(
                action,
                flag=flag,
                operator_id=operator_id,
                account=record_account,
                outcome="write_failed",
            )
            raise
        self._record(action, flag=flag, operator_id=operator_id, account=record_account)
        return self._view(overlay)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_managed(self, flag: str, *, operator_id: str, action: str) -> None:
        if flag not in MANAGED_FLAGS:
            self._record(
                action,
                flag=flag,
                operator_id=operator_id,
                outcome="refused_unmanaged_flag",
            )
            raise ValidationFailure(
                f"'{flag}' is not a runtime-manageable feature flag; "
                f"manageable flags are {sorted(MANAGED_FLAGS)}."
            )

    def _require_mode(
        self, flag: str, mode: FlagMode | str, *, operator_id: str
    ) -> FlagMode:
        try:
            return FlagMode(mode)
        except ValueError as exc:
            self._record(
                "set_mode",
                flag=flag,
                operator_id=operator_id,
                outcome="refused_unknown_mode",
            )
            raise ValidationFailure(
                f"'{mode}' is not a feature-flag mode; "
                f"modes are {[item.value for item in FlagMode]}."
            ) from exc

    def _selected_users_entry(
        self, current: dict[str, FlagOverride], flag: str
    ) -> FlagOverride:
        """The flag's entry, iff its *locked, freshly read* mode is SELECTED_USERS.

        Called only from inside a mutate callback, so `current` is the
        snapshot taken under the repository lock rather than the service's
        cached read — a concurrent `set_mode`/`clear_override` racing this
        call is therefore always resolved one way or the other, never
        observed half-applied, and a flag a concurrent `clear_override` just
        removed is a normal refusal rather than a `KeyError` (010-FR-010).
        """

        entry = current.get(flag)
        if entry is None or entry.mode is not FlagMode.SELECTED_USERS:
            raise ValidationFailure(
                f"'{flag}' must be in selected_users mode before its cohort "
                "can be changed."
            )
        return entry

    def _record(
        self,
        action: str,
        *,
        flag: str,
        operator_id: str,
        account: str | None = None,
        outcome: str = "applied",
    ) -> None:
        """One content-free record per operator mutation (010-FR-006, DD-10)."""

        logger.info(
            "Runtime flag mutation: operator=%s correlation=%s flag=%s action=%s "
            "account=%s outcome=%s",
            operator_id,
            get_correlation_id(),
            flag,
            action,
            account or _NO_ACCOUNT,
            outcome,
        )

    def _mutate(self, apply: MutationFn) -> RuntimeOverlay:
        overlay = self.repository.mutate(apply)
        self._invalidate()
        return overlay

    def _invalidate(self) -> None:
        self._cached = None
        self._cache_key = None

    def _stat_key(self) -> tuple[int, int] | None:
        """Modification time and size, the pair a replacement always changes."""

        try:
            stat = os.stat(self.repository.document_path)
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _overlay(self) -> RuntimeOverlay:
        key = self._stat_key()
        if self._cached is not None and self._cache_key == key:
            return self._cached
        overlay = self.repository.read()
        self._cached = overlay
        self._cache_key = key
        return overlay

    def _view(self, overlay: RuntimeOverlay) -> RuntimeFlagsView:
        flags: list[ManagedFlagView] = []
        for name in MANAGED_FLAGS:
            entry = overlay.flags.get(name)
            flags.append(
                ManagedFlagView(
                    name=name,
                    override_mode=entry.mode if entry is not None else None,
                    source=(
                        SOURCE_RUNTIME if entry is not None else SOURCE_DEPLOY_DEFAULT
                    ),
                    deploy_default_state=self.config.feature_flags.states[name].value,
                    selected_users=self._resolve_cohort(entry),
                )
            )
        return RuntimeFlagsView(degraded=overlay.degraded, flags=tuple(flags))

    def _resolve_cohort(
        self, entry: FlagOverride | None
    ) -> tuple[SelectedUserView, ...]:
        """Resolve stored IDs to canonical emails for display only (DD-5).

        Deliberately a plain `UserRepository.get_by_id` read rather than
        `AdminService.find_account`: that method emits one attributed "Admin
        lookup" record per call, so rendering a cohort through it would write
        one lookup record per member per page load for lookups the operator
        never performed (plan.md, DD-10).
        """

        if entry is None:
            return ()
        rows: list[SelectedUserView] = []
        for account_id in entry.selected_users:
            account = self.user_repo.get_by_id(account_id)
            rows.append(
                SelectedUserView(
                    account_id=account_id,
                    email=account.email if account is not None else None,
                )
            )
        return tuple(rows)


def _entry_admits(entry: FlagOverride, user: User) -> bool:
    """Whether one runtime entry makes the flag effective for one user."""

    if entry.mode is FlagMode.ON:
        return True
    if entry.mode is FlagMode.OFF:
        return False
    # Matching is against the *authenticated* user's own immutable id, so a
    # stale id left in a cohort grants nothing to anyone.
    return user.id in entry.selected_users


__all__ = [
    "DegradedRuntimeFlagsError",
    "FeatureFlagService",
    "ManagedFlagView",
    "RuntimeFlagsView",
    "SOURCE_DEPLOY_DEFAULT",
    "SOURCE_RUNTIME",
    "SelectedUserNotFoundError",
    "SelectedUserView",
]
