"""SQLite runtime feature-flag store — the sole source of truth (ADR-0019).

One `feature_flags` table on the existing backend data volume holds exactly
one row per **managed** flag (`voice_brain_dump`, `mobile_task_classification`,
`external_agent_relay`) — a mode plus, for `selected_users`, a set of immutable
account IDs. There is no environment fallback and no "deploy default"
inheritance left after the one-time migration below: every managed flag's
SQLite row is the entire answer (DD-15).

Three properties this module exists to hold:

* **Presence is an invariant, not a fallback state** (DD-2). After migration,
  the store is either **healthy** — readable, with a well-formed row for each
  of the three managed flags — or **degraded**: unreadable, missing a row, or
  a row whose `mode` is outside its vocabulary. Every flag resolves to
  ineffective while degraded, every mutation is refused, and the transition
  into that state emits exactly one coarse WARNING.
* **Migration is one-time, transactional, and restart-idempotent** (DD-15).
  A `migration_ledger` row, committed in the same transaction as the seeded
  flag rows, guards every construction after the first — mirroring
  `TaskRepository._migrate_legacy_json_once`. Per flag, the pre-correction
  JSON overlay's entry wins when it is present, well-formed, and for a flag
  the overlay ever wrote (`voice_brain_dump`/`mobile_task_classification`
  only); otherwise the deploy-staged environment baseline supplies it,
  resolving `internal` to `selected_users` by resolving each configured
  internal-user email to its current account id and skipping one that does
  not resolve. `external_agent_relay` always comes from the environment
  baseline, never the legacy JSON. A failure before the migration transaction
  commits leaves neither a ledger row nor partial flag rows, and never
  mutates the legacy JSON file or the environment.
* **Erasure reaches every managed flag's cohort** (DD-9, DD-13).
  :meth:`scrub_user` removes a purged account ID from each managed flag's
  `selected_users` set and raises rather than pretending to have scrubbed a
  store it never read.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from app.core.config import FeatureFlagState, ManagedFlagMigrationSeed
from app.core.logging import get_correlation_id
from app.exceptions import RepositoryError, StorageUnavailableError
from app.utils.file_ops import atomic_write
from app.utils.time import utcnow

from .base import BaseRepository

logger = logging.getLogger(__name__)

DB_FILENAME = "feature_flags.sqlite3"
_LEGACY_DOCUMENT_PARTS: tuple[str, ...] = ("feature-flags", "runtime.json")
_MIGRATION_LEDGER_ID = "adr-0019-sqlite-v1"

MIGRATION_COMPLETE_MARKER_PARTS: tuple[str, ...] = (
    "feature-flags",
    "sqlite-migration-complete.json",
)
"""Where the durable migration-complete marker lives, beside the legacy
document and **outside** `feature_flags.sqlite3`.

The migration ledger is a row inside the database file, so deleting or
recreating that file used to be indistinguishable from a first start:
migration re-ran and the legacy JSON overlay re-seeded cohorts that GDPR
erasure had already scrubbed. This marker is the durable answer to "has the
one-time migration already happened on this volume?", and once it exists the
legacy document and the deploy-staged environment are never read again — a
database missing its rows initializes fail-closed OFF instead (DD-9, DD-15).

It carries no account ID, no email and no environment value: only the
migration id and when it completed (010-SC-007).
"""

MANAGED_FLAGS: tuple[str, ...] = (
    "voice_brain_dump",
    "mobile_task_classification",
    "external_agent_relay",
    "task_title_autocomplete",
)
"""The three runtime-manageable flags after ADR-0019 (DD-1, DD-15, DD-16).

`admin_portal` is not excluded — it does not exist as a flag at all (DD-14).
`delivery_canary` stays a separate, environment-owned release-smoke input.
"""

_ADR_0019_MANAGED_FLAGS: frozenset[str] = frozenset(
    {"voice_brain_dump", "mobile_task_classification", "external_agent_relay"}
)

_LEGACY_JSON_MANAGED_FLAGS: frozenset[str] = frozenset(
    {"voice_brain_dump", "mobile_task_classification"}
)
"""Flags the pre-correction JSON overlay ever wrote. `external_agent_relay`
did not exist as a managed flag before ADR-0019, so a same-named key in a
legacy document must never be read by migration (DD-15)."""

_MODE_FIELD = "mode"
_SELECTED_USERS_FIELD = "selected_users"

_REASON_UNREADABLE = "unreadable"
_REASON_INVALID_MODE = "invalid_mode"

ResolveAccountId = Callable[[str], str | None]
LoadMigrationSeed = Callable[[], ManagedFlagMigrationSeed]

_ACCOUNT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
"""Exact grammar an opaque account ID must match — never an email or display
name — enforced at every boundary a cohort crosses (DD-9, 010-SC-007)."""


def _is_valid_account_id(value: str) -> bool:
    return isinstance(value, str) and _ACCOUNT_ID_PATTERN.fullmatch(value) is not None


def _is_canonical_cohort(cohort: tuple[str, ...]) -> bool:
    """Sorted, unique, and every member a well-formed account ID.

    This is the on-disk cohort shape the write path enforces (010-SC-007):
    not just "no emails", but no duplicates and one deterministic order, so
    a stored row can never require the reader to defensively re-normalize
    it.
    """

    if not all(_is_valid_account_id(item) for item in cohort):
        return False
    if len(set(cohort)) != len(cohort):
        return False
    return list(cohort) == sorted(cohort)


class FlagMode(str, Enum):
    """The three runtime states one managed flag may hold."""

    OFF = "off"
    ON = "on"
    SELECTED_USERS = "selected_users"


class DegradedRuntimeFlagsError(RepositoryError):
    """Raised when a mutation is attempted against an unreadable store.

    Every mutation is refused while degraded (FR-004) rather than writing
    over rows the system could not safely read — including
    :meth:`FeatureFlagOverrideRepository.scrub_user`, whose caller turns this
    into DD-13's fail-closed purge ordering.
    """

    def __init__(self) -> None:
        super().__init__(
            "The runtime feature-flag store could not be read; "
            "changes are refused until it is repaired."
        )


class ManagedFlagMigrationError(RepositoryError):
    """Raised when the deploy-staged managed-flag input cannot seed migration.

    Only reachable on a genuine first start — no ledger row and no durable
    marker — because that is the only moment the input is parsed at all
    (DD-15). It fails the construction closed, leaving no rows, no ledger and
    no marker, so a retry with corrected input still migrates exactly once.
    """


class InvalidAccountCohortError(RepositoryError):
    """Raised when a cohort about to be persisted is not canonical.

    The write path enforces the account-ID privacy invariant itself, not
    only migration/read (010-SC-007): an invalid member, a duplicate, or
    non-sorted order is refused before any SQL executes, so the enclosing
    transaction rolls back and the store never gains a row it did not
    already accept on read.
    """

    def __init__(self) -> None:
        super().__init__("Refusing to persist a non-canonical account cohort.")


@dataclass(frozen=True, slots=True)
class FlagOverride:
    """One managed flag's stored entry: a mode plus its retained cohort.

    The cohort is retained across a mode change to `off`/`on` (DD-6), so it
    is stored independently of whether the mode currently consults it.
    """

    mode: FlagMode
    selected_users: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class RuntimeOverlay:
    """What one read of the store says, and whether it could be read at all."""

    degraded: bool
    flags: Mapping[str, FlagOverride]


MutationFn = Callable[[dict[str, FlagOverride]], Mapping[str, FlagOverride]]


def _parse_legacy_entry(payload: Any) -> FlagOverride | None:
    """Parse one legacy JSON entry, returning `None` on anything malformed.

    DD-15 requires the legacy entry to be well-formed, not merely present,
    before it beats the environment baseline. A single cohort member outside
    the account-ID grammar — an email, most sensitively — invalidates the
    *whole* entry rather than being dropped in isolation: partially trusting
    a malformed legacy record is itself a privacy risk (010-SC-007). Valid
    duplicates canonicalize to one ID each, in sorted order.
    """

    if not isinstance(payload, dict):
        return None
    raw_mode = payload.get(_MODE_FIELD)
    if not isinstance(raw_mode, str):
        return None
    try:
        mode = FlagMode(raw_mode)
    except ValueError:
        return None
    raw_cohort = payload.get(_SELECTED_USERS_FIELD, [])
    if not isinstance(raw_cohort, list) or not all(
        isinstance(item, str) and _is_valid_account_id(item) for item in raw_cohort
    ):
        return None
    return FlagOverride(mode=mode, selected_users=tuple(sorted(set(raw_cohort))))


class FeatureFlagOverrideRepository(BaseRepository):
    """SQLite-backed store for the three managed flags (ADR-0019, DD-15)."""

    _process_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        root: Path,
        *,
        legacy_states: Mapping[str, FeatureFlagState] | None = None,
        legacy_internal_users: frozenset[str] = frozenset(),
        load_migration_seed: LoadMigrationSeed | None = None,
        resolve_account_id: ResolveAccountId | None = None,
    ) -> None:
        super().__init__(root)
        self.db_path = self.resolve(DB_FILENAME)
        self.migration_marker_path = self.resolve(*MIGRATION_COMPLETE_MARKER_PARTS)
        self._legacy_document_path = self.resolve(*_LEGACY_DOCUMENT_PARTS)
        # A callback, not a value: the deploy-staged baseline is parsed only
        # inside the first-migration transaction, after the ledger and marker
        # checks have both come back empty (DD-15). `legacy_states` /
        # `legacy_internal_users` stay as the already-parsed shorthand.
        self._load_migration_seed: LoadMigrationSeed = load_migration_seed or (
            lambda: ManagedFlagMigrationSeed(
                states=dict(legacy_states or {}),
                internal_users=legacy_internal_users,
            )
        )
        self._resolve_account_id = resolve_account_id or (lambda email: None)
        # Guards `_last_read_healthy` so the check/set/log transition below
        # is atomic — two threads reading a store that just went degraded
        # must never both observe "was healthy" and both warn (FR-004).
        self._health_lock = threading.Lock()
        # Deliberately starts unset, not healthy: a process whose very first
        # read is already degraded must still emit the transition WARNING
        # once (FR-004).
        self._last_read_healthy: bool | None = None
        self._ready = False
        # A corrupt, locked or otherwise unreadable store must not abort
        # application startup: it degrades the repository instead, which
        # already means every flag ineffective and every mutation refused
        # (FR-004). The file is left exactly as found — never overwritten,
        # quarantined or deleted — and `_ensure_ready` retries on each
        # later call so an operator repair recovers without a restart.
        #
        # `ManagedFlagMigrationError` deliberately escapes: unusable
        # *storage* is a degradation, unusable *deploy input* on a first
        # start is a configuration failure that must stop the boot.
        with suppress(sqlite3.Error, OSError):
            self._prepare()

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------

    def _prepare(self) -> None:
        self._initialize_database()
        self._migrate_once()
        self._ready = True

    def _ensure_ready(self) -> bool:
        """Whether the store is initialized, retrying a failed preparation.

        Recovery, not permissive fallback: this re-runs the very same
        initialization and one-time migration the constructor runs, so a
        repository that degraded on a corrupt file starts reading healthily
        again once the file is repaired or replaced — and stays degraded for
        as long as it is not.
        """

        if self._ready:
            return True
        try:
            self._prepare()
        except (sqlite3.Error, OSError, ManagedFlagMigrationError):
            return False
        return True

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------

    @contextmanager
    def _owned_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
        finally:
            conn.close()

    def _initialize_database(self) -> None:
        with self._owned_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS feature_flags ("
                    "flag TEXT PRIMARY KEY, "
                    "mode TEXT NOT NULL, "
                    "selected_users TEXT NOT NULL"
                    ")"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS migration_ledger ("
                    "id TEXT PRIMARY KEY, "
                    "migrated_at TEXT NOT NULL, "
                    "payload TEXT NOT NULL"
                    ")"
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    # ------------------------------------------------------------------
    # One-time migration
    # ------------------------------------------------------------------

    def _migrate_once(self) -> None:
        """Seed the three managed rows exactly once per volume.

        Three cases, all decided inside one `BEGIN IMMEDIATE` transaction so
        concurrent first starts cannot both migrate (DD-15):

        * a ledger row already exists — nothing to do, but the durable marker
          is backfilled afterwards, which closes the commit-then-marker crash
          window and stops an old store from being one `rm` away from
          re-migrating;
        * no ledger row but the marker exists — the database was deleted or
          recreated after migration. Neither the legacy document nor the
          deploy-staged environment may be read again, so the missing rows
          initialize fail-closed OFF;
        * neither — a genuine first start. Only here is the managed
          environment input parsed at all.
        """

        with self._process_lock, self._owned_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                seen = conn.execute(
                    "SELECT 1 FROM migration_ledger WHERE id = ?",
                    (_MIGRATION_LEDGER_ID,),
                ).fetchone()
                if seen is None:
                    self._seed_managed_rows(conn)
                    conn.execute(
                        "INSERT INTO migration_ledger (id, migrated_at, payload) "
                        "VALUES (?, ?, ?)",
                        (
                            _MIGRATION_LEDGER_ID,
                            utcnow().isoformat(),
                            json.dumps({"managed_flags": list(MANAGED_FLAGS)}),
                        ),
                    )
                else:
                    self._upgrade_adr_0019_store(conn)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        self._write_migration_marker()

    def _seed_managed_rows(self, conn: sqlite3.Connection) -> None:
        if self._migration_marker_exists():
            # Post-marker re-initialization: fail closed, never re-migrate.
            for flag in MANAGED_FLAGS:
                self._upsert_row(conn, flag, FlagOverride(mode=FlagMode.OFF))
            return
        seed = self._load_seed()
        legacy_document = self._read_legacy_document()
        for flag in MANAGED_FLAGS:
            entry = (
                FlagOverride(mode=FlagMode.OFF)
                if flag == "task_title_autocomplete"
                else self._seed_entry(flag, legacy_document, seed)
            )
            self._upsert_row(conn, flag, entry)

    def _upgrade_adr_0019_store(self, conn: sqlite3.Connection) -> None:
        """Add the fourth row only to a complete, healthy ADR-0019 store."""
        rows = conn.execute(
            "SELECT flag, mode, selected_users FROM feature_flags"
        ).fetchall()
        if {row["flag"] for row in rows} != _ADR_0019_MANAGED_FLAGS:
            return
        for row in rows:
            try:
                mode = FlagMode(row["mode"])
                raw_cohort = json.loads(row["selected_users"])
            except (TypeError, ValueError, json.JSONDecodeError):
                return
            if not isinstance(raw_cohort, list):
                return
            cohort = tuple(raw_cohort)
            if not _is_canonical_cohort(cohort):
                return
            if mode is not FlagMode.SELECTED_USERS and cohort:
                return
        self._upsert_row(
            conn, "task_title_autocomplete", FlagOverride(mode=FlagMode.OFF)
        )

    def _load_seed(self) -> ManagedFlagMigrationSeed:
        try:
            return self._load_migration_seed()
        except ValueError as exc:
            raise ManagedFlagMigrationError(str(exc)) from exc

    def _migration_marker_exists(self) -> bool:
        return self.migration_marker_path.is_file()

    def _write_migration_marker(self) -> None:
        """Record that migration completed, atomically and without any PII.

        Written after the transaction commits, so it can only ever claim a
        migration the ledger already proves. If the process dies in between,
        the next construction sees the ledger and backfills it here.
        """

        if self._migration_marker_exists():
            return
        atomic_write(
            self.migration_marker_path,
            json.dumps(
                {
                    "migration_id": _MIGRATION_LEDGER_ID,
                    "completed_at": utcnow().isoformat(),
                },
                indent=2,
            )
            + "\n",
        )

    def _read_legacy_document(self) -> dict[str, Any]:
        """Best-effort, one-time-only read of the pre-correction JSON overlay.

        Never deletes, renames or mutates the file. A missing or unparseable
        document simply supplies no legacy entries; every flag falls back to
        the environment baseline (DD-15).
        """

        try:
            text = self._legacy_document_path.read_text(encoding="utf-8")
            payload = json.loads(text)
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _seed_entry(
        self,
        flag: str,
        legacy_document: dict[str, Any],
        seed: ManagedFlagMigrationSeed,
    ) -> FlagOverride:
        if flag in _LEGACY_JSON_MANAGED_FLAGS:
            parsed = _parse_legacy_entry(legacy_document.get(flag))
            if parsed is not None:
                return parsed
        return self._environment_baseline_entry(flag, seed)

    def _environment_baseline_entry(
        self, flag: str, seed: ManagedFlagMigrationSeed
    ) -> FlagOverride:
        state = seed.states.get(flag, FeatureFlagState.OFF)
        if state is FeatureFlagState.ON:
            return FlagOverride(mode=FlagMode.ON)
        if state is FeatureFlagState.OFF:
            return FlagOverride(mode=FlagMode.OFF)
        resolved: set[str] = set()
        for email in sorted(seed.internal_users):
            account_id = self._resolve_account_id(email)
            if account_id is not None and _is_valid_account_id(account_id):
                resolved.add(account_id)
        return FlagOverride(
            mode=FlagMode.SELECTED_USERS, selected_users=tuple(sorted(resolved))
        )

    @staticmethod
    def _upsert_row(conn: sqlite3.Connection, flag: str, entry: FlagOverride) -> None:
        """Write one row, refusing before SQL runs if the cohort is not
        canonical (010-SC-007) — the write path is the last line of defense,
        not merely migration/read, so an invalid mutation rolls its whole
        transaction back rather than persisting anything."""

        if not _is_canonical_cohort(entry.selected_users):
            raise InvalidAccountCohortError()
        conn.execute(
            "INSERT INTO feature_flags (flag, mode, selected_users) VALUES (?, ?, ?) "
            "ON CONFLICT(flag) DO UPDATE SET "
            "mode = excluded.mode, selected_users = excluded.selected_users",
            (flag, entry.mode.value, json.dumps(list(entry.selected_users))),
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def read(self) -> RuntimeOverlay:
        """The current overlay, never raising for a store it cannot read."""

        if not self._ensure_ready():
            return self._note_degraded(_REASON_UNREADABLE)
        try:
            with self._owned_connection() as conn:
                overlay = self._load(conn)
        except (sqlite3.Error, OSError):
            return self._note_degraded(_REASON_UNREADABLE)
        if overlay.degraded:
            return self._note_degraded(_REASON_INVALID_MODE)
        self._note_healthy()
        return overlay

    def _load(self, conn: sqlite3.Connection) -> RuntimeOverlay:
        """Pure read of the three rows; degraded is a return value, not a log."""

        rows = conn.execute(
            "SELECT flag, mode, selected_users FROM feature_flags"
        ).fetchall()
        present = {row["flag"]: row for row in rows}
        if set(present) != set(MANAGED_FLAGS):
            return RuntimeOverlay(degraded=True, flags={})
        flags: dict[str, FlagOverride] = {}
        for flag in MANAGED_FLAGS:
            row = present[flag]
            try:
                mode = FlagMode(row["mode"])
                raw_cohort = json.loads(row["selected_users"])
            except (ValueError, TypeError):
                return RuntimeOverlay(degraded=True, flags={})
            if not isinstance(raw_cohort, list) or not all(
                isinstance(item, str) for item in raw_cohort
            ):
                return RuntimeOverlay(degraded=True, flags={})
            cohort = tuple(raw_cohort)
            if not _is_canonical_cohort(cohort):
                return RuntimeOverlay(degraded=True, flags={})
            flags[flag] = FlagOverride(mode=mode, selected_users=cohort)
        return RuntimeOverlay(degraded=False, flags=flags)

    def _note_healthy(self) -> None:
        with self._health_lock:
            self._last_read_healthy = True

    def _note_degraded(self, reason: str) -> RuntimeOverlay:
        """Record the degraded read, warning once per transition into it.

        The check, the log call and the state flip happen under one lock so
        two threads racing into this method together can never both observe
        "was healthy" and both emit the WARNING (FR-004) — exactly one
        coarse WARNING per healthy/unset-to-degraded transition, per
        process.
        """

        with self._health_lock:
            if self._last_read_healthy is not False:
                logger.warning(
                    "Runtime feature-flag store unusable: correlation=%s reason=%s",
                    get_correlation_id(),
                    reason,
                )
            self._last_read_healthy = False
        return RuntimeOverlay(degraded=True, flags={})

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def mutate(self, apply: MutationFn) -> RuntimeOverlay:
        """Apply one targeted change inside one `BEGIN IMMEDIATE` transaction.

        SQLite's own locking (plus a busy timeout) is the concurrency
        primitive — the same pattern `TaskRepository.command_lock` already
        uses on this volume (DD-15); no separate file lock.

        A mid-transaction `sqlite3.Error` (disk full, EIO, a lock timeout) is
        translated into `StorageUnavailableError`, mirroring
        `TaskRepository._sqlite_guard`: the caller sees the app's own 5xx
        contract rather than a raw driver exception with no registered
        handler (ADR-0019 §6's audit obligation still requires the failure to
        surface, just through the app's own error type).
        """

        if not self._ensure_ready():
            self._note_degraded(_REASON_UNREADABLE)
            raise DegradedRuntimeFlagsError()
        with self._process_lock:
            try:
                conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
            except sqlite3.Error as exc:
                self._note_degraded(_REASON_UNREADABLE)
                raise DegradedRuntimeFlagsError() from exc
            try:
                try:
                    conn.row_factory = sqlite3.Row
                    conn.execute("PRAGMA busy_timeout = 5000")
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        overlay = self._load(conn)
                        if overlay.degraded:
                            raise DegradedRuntimeFlagsError()
                        updated = dict(apply(dict(overlay.flags)))
                        for flag in MANAGED_FLAGS:
                            self._upsert_row(conn, flag, updated[flag])
                        conn.commit()
                    except BaseException:
                        conn.rollback()
                        raise
                except sqlite3.Error as exc:
                    raise StorageUnavailableError(
                        "Runtime feature-flag store is temporarily unavailable; "
                        "retry the request."
                    ) from exc
            finally:
                conn.close()
        self._note_healthy()
        return RuntimeOverlay(degraded=False, flags=updated)

    def scrub_user(self, account_id: str) -> int:
        """Erase one account ID from every managed flag's cohort.

        GDPR erasure support, mirroring `InviteRepository.scrub_user`.
        Idempotent. Raises :class:`DegradedRuntimeFlagsError` rather than
        silently completing when the store cannot be read (DD-9, DD-13), so
        `AccountService.purge_account` halts before deleting the account
        record and the maintenance sweep retries.

        Erasure reaches the retained legacy JSON artifact too. That file is no
        longer a migration or runtime source once the marker exists, but it is
        kept on the volume so an old image can still be rolled back onto it —
        and a rollback artifact that still names a purged account is a privacy
        leak, not a compatibility feature. The returned count stays the number
        of *managed flags* whose SQLite cohort changed.
        """

        if not self._ensure_ready():
            self._note_degraded(_REASON_UNREADABLE)
            raise DegradedRuntimeFlagsError()
        with self._process_lock:
            try:
                conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
            except sqlite3.Error as exc:
                self._note_degraded(_REASON_UNREADABLE)
                raise DegradedRuntimeFlagsError() from exc
            removed = 0
            try:
                try:
                    conn.row_factory = sqlite3.Row
                    conn.execute("PRAGMA busy_timeout = 5000")
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        overlay = self._load(conn)
                        if overlay.degraded:
                            raise DegradedRuntimeFlagsError()
                        for flag, entry in overlay.flags.items():
                            if account_id not in entry.selected_users:
                                continue
                            removed += 1
                            trimmed = FlagOverride(
                                mode=entry.mode,
                                selected_users=tuple(
                                    member
                                    for member in entry.selected_users
                                    if member != account_id
                                ),
                            )
                            self._upsert_row(conn, flag, trimmed)
                        conn.commit()
                    except BaseException:
                        conn.rollback()
                        raise
                except sqlite3.Error as exc:
                    raise StorageUnavailableError(
                        "Runtime feature-flag store is temporarily unavailable; "
                        "retry the request."
                    ) from exc
            finally:
                conn.close()
            try:
                self._scrub_legacy_document(account_id)
            except OSError as exc:
                # Fail closed like every other erasure step: the caller must
                # not go on to delete the account while a retained artifact
                # may still name it (DD-13).
                raise StorageUnavailableError(
                    "The legacy runtime feature-flag artifact could not be "
                    "scrubbed; retry the purge."
                ) from exc
        self._note_healthy()
        return removed

    def _scrub_legacy_document(self, account_id: str) -> None:
        """Remove one purged account ID from the retained legacy artifact.

        Serialized by the caller's `_process_lock` and committed with the same
        atomic temp-file replace every other document write on this volume
        uses, so a reader never observes a half-rewritten file.

        A legacy document that cannot be parsed cannot be surgically rewritten
        — and it is no longer authoritative for anything, so there is nothing
        to preserve in it. If such a document still names the purged account
        it is removed outright rather than left on the volume; if it does not,
        it is left untouched.
        """

        try:
            text = self._legacy_document_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            self._discard_leaking_legacy_document(text, account_id)
            return

        scrubbed = {
            flag: _without_cohort_member(entry, account_id)
            for flag, entry in payload.items()
        }
        if scrubbed == payload:
            return
        rewritten = json.dumps(scrubbed, indent=2) + "\n"
        # Belt and braces: a purged ID parked somewhere the structured scrub
        # above does not reach must still not survive on the volume.
        if self._discard_leaking_legacy_document(rewritten, account_id):
            return
        atomic_write(self._legacy_document_path, rewritten)

    def _discard_leaking_legacy_document(self, text: str, account_id: str) -> bool:
        if account_id not in text:
            return False
        logger.warning(
            "Discarding the legacy runtime feature-flag artifact: it still "
            "names a purged account and cannot be scrubbed in place "
            "(correlation=%s)",
            get_correlation_id(),
        )
        self._legacy_document_path.unlink(missing_ok=True)
        return True


def _without_cohort_member(entry: Any, account_id: str) -> Any:
    """One legacy entry with `account_id` dropped from its cohort, if any."""

    if not isinstance(entry, dict):
        return entry
    cohort = entry.get(_SELECTED_USERS_FIELD)
    if not isinstance(cohort, list):
        return entry
    return {
        **entry,
        _SELECTED_USERS_FIELD: [member for member in cohort if member != account_id],
    }


__all__ = [
    "DegradedRuntimeFlagsError",
    "FeatureFlagOverrideRepository",
    "FlagMode",
    "FlagOverride",
    "InvalidAccountCohortError",
    "MANAGED_FLAGS",
    "MIGRATION_COMPLETE_MARKER_PARTS",
    "ManagedFlagMigrationError",
    "RuntimeOverlay",
]
