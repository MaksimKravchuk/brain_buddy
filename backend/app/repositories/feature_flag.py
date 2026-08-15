"""Durable runtime overlay for the two runtime-manageable rollout flags.

One server-owned JSON document on the existing data volume
(`{data_dir}/feature-flags/runtime.json`) records, per **managed** flag, a mode
of `off`/`on`/`selected_users` and — for `selected_users` — a set of immutable
account IDs (010-FR-001, DD-1, DD-5). It holds no email address, display name,
credential, token or member content, and nothing here can put one there: the
pure mutation function only ever sees :class:`FlagOverride`, whose two fields
are a closed mode vocabulary and an account-ID tuple.

Three properties this module exists to hold:

* **Absence is healthy, corruption is degraded** (010-FR-004, DD-2). A missing
  document means every flag resolves from the deploy baseline and the very next
  mutation creates the file. A document that exists but cannot be parsed means
  every flag *still* resolves from the deploy baseline, but every mutation is
  refused rather than overwriting bytes nobody could read — and the transition
  into that state emits exactly one coarse WARNING.
* **Forward compatibility is preservation, not tolerance of nonsense** (DD-8).
  An entry naming a flag this build does not declare, an entry naming a flag it
  declares but does not manage, and an unrecognized field inside a managed
  entry are all ignored for evaluation and carried through every write
  value-intact. A *recognized* field holding a value outside its vocabulary is
  not forward compatibility — it is the document failing to parse as this
  build's schema, and is degraded.
* **Erasure reaches every parseable copy** (DD-9, DD-13). :meth:`scrub_user`
  removes a purged account ID from any `selected_users` array it can parse,
  declared or not — the one narrow exception to the preservation rule above —
  and raises rather than pretending to have scrubbed a document it never read.
"""

from __future__ import annotations

import fcntl
import json
import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, cast

from app.core.logging import get_correlation_id
from app.exceptions import RepositoryError
from app.utils.file_ops import atomic_write, ensure_directory

from .base import BaseRepository

logger = logging.getLogger(__name__)

FEATURE_FLAGS_DIRNAME = "feature-flags"
RUNTIME_DOCUMENT_FILENAME = "runtime.json"
RUNTIME_LOCK_FILENAME = "runtime.json.lock"

MANAGED_FLAGS: tuple[str, ...] = ("voice_brain_dump", "mobile_task_classification")
"""The runtime-manageable subset of ``KNOWN_FEATURE_FLAGS`` (DD-1).

Deliberately not the whole set: ``admin_portal`` would be a self-lockout,
``delivery_canary`` is a production release-smoke input, and
``external_agent_relay``'s secret box is decided once at container construction
and cannot be re-entered per request.
"""

_MODE_FIELD = "mode"
_SELECTED_USERS_FIELD = "selected_users"

_REASON_UNREADABLE = "unreadable"
_REASON_MALFORMED = "malformed"


class FlagMode(str, Enum):
    """The three runtime-override states one managed flag may hold."""

    OFF = "off"
    ON = "on"
    SELECTED_USERS = "selected_users"


class DegradedRuntimeFlagsError(RepositoryError):
    """Raised when a mutation is attempted against an unparseable document.

    Every mutation is refused while degraded (010-FR-004) rather than
    overwriting a document the system could not safely read — including
    :meth:`FeatureFlagOverrideRepository.scrub_user`, whose caller turns this
    into DD-13's fail-closed purge ordering.
    """

    def __init__(self) -> None:
        super().__init__(
            "The runtime feature-flag document could not be read; "
            "changes are refused until it is repaired."
        )


@dataclass(frozen=True, slots=True)
class FlagOverride:
    """One managed flag's runtime entry: a mode plus its retained cohort.

    The cohort is retained across a mode change to ``off``/``on`` (DD-6), so it
    is stored independently of whether the mode currently consults it.
    """

    mode: FlagMode
    selected_users: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class RuntimeOverlay:
    """What one read of the document says, and whether it could be read at all."""

    degraded: bool
    flags: Mapping[str, FlagOverride]


MutationFn = Callable[[dict[str, FlagOverride]], Mapping[str, FlagOverride]]


def _parse_entry(payload: Any) -> FlagOverride:
    """Parse one managed flag's entry, raising on anything outside the schema."""

    if not isinstance(payload, dict):
        raise ValueError("managed entry is not an object")
    raw_mode = payload.get(_MODE_FIELD)
    if not isinstance(raw_mode, str):
        raise ValueError("managed entry has no mode")
    try:
        mode = FlagMode(raw_mode)
    except ValueError as exc:
        raise ValueError("managed entry mode is outside the known vocabulary") from exc
    raw_cohort = payload.get(_SELECTED_USERS_FIELD, [])
    if not isinstance(raw_cohort, list) or not all(
        isinstance(item, str) for item in raw_cohort
    ):
        raise ValueError("managed entry cohort is not an array of account ids")
    return FlagOverride(mode=mode, selected_users=tuple(cast(list[str], raw_cohort)))


def _scrub_cohorts(payload: Any, account_id: str) -> int:
    """Remove ``account_id`` from every ``selected_users`` array reachable here.

    Walks the whole parsed document, not only the two managed entries: DD-9
    requires erasure to reach a cohort inside an entry this build does not
    otherwise recognize, which DD-8 would otherwise carry through every write
    untouched. Nothing else about such an entry is altered.
    """

    removed = 0
    if isinstance(payload, dict):
        for key, value in payload.items():
            if (
                key == _SELECTED_USERS_FIELD
                and isinstance(value, list)
                and account_id in value
            ):
                payload[key] = [item for item in value if item != account_id]
                removed += 1
                continue
            removed += _scrub_cohorts(value, account_id)
    elif isinstance(payload, list):
        for item in payload:
            removed += _scrub_cohorts(item, account_id)
    return removed


class FeatureFlagOverrideRepository(BaseRepository):
    """Locked read-modify-write access to the one runtime rollout document."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.flags_dir = ensure_directory(self.resolve(FEATURE_FLAGS_DIRNAME))
        self.document_path = self.flags_dir / RUNTIME_DOCUMENT_FILENAME
        self._lock_path = self.flags_dir / RUNTIME_LOCK_FILENAME
        # Deliberately starts unset, not healthy: a process whose very first
        # read is already degraded must still emit the transition WARNING once
        # (010-FR-004).
        self._last_read_healthy: bool | None = None
        self._last_healthy_override_count = 0

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def read(self) -> RuntimeOverlay:
        """The current overlay, never raising for a document it cannot parse."""

        overlay, _raw = self._read_document()
        return overlay

    def _read_document(self) -> tuple[RuntimeOverlay, dict[str, Any]]:
        if not self.document_path.exists():
            self._note_healthy(0)
            return RuntimeOverlay(degraded=False, flags={}), {}
        try:
            text = self.document_path.read_text(encoding="utf-8")
        except OSError:
            return self._note_degraded(_REASON_UNREADABLE), {}
        try:
            payload = json.loads(text)
        except (ValueError, UnicodeDecodeError):
            return self._note_degraded(_REASON_MALFORMED), {}
        if not isinstance(payload, dict):
            return self._note_degraded(_REASON_MALFORMED), {}
        flags: dict[str, FlagOverride] = {}
        for name in MANAGED_FLAGS:
            if name not in payload:
                continue
            try:
                flags[name] = _parse_entry(payload[name])
            except ValueError:
                return self._note_degraded(_REASON_MALFORMED), {}
        self._note_healthy(len(flags))
        return RuntimeOverlay(degraded=False, flags=flags), cast(
            dict[str, Any], payload
        )

    def _note_healthy(self, override_count: int) -> None:
        self._last_read_healthy = True
        self._last_healthy_override_count = override_count

    def _note_degraded(self, reason: str) -> RuntimeOverlay:
        """Record the degraded read, warning once per transition into it."""

        if self._last_read_healthy is not False:
            logger.warning(
                "Runtime feature-flag document unusable: correlation=%s reason=%s "
                "overrides_inactive=%s",
                get_correlation_id(),
                reason,
                self._last_healthy_override_count,
            )
        self._last_read_healthy = False
        return RuntimeOverlay(degraded=True, flags={})

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Serialize writers with an advisory `flock` on a sibling lock file.

        Correct for the single backend process on a single Fly machine this
        feature assumes (plan.md, ADR-0018). A scale-out would give each machine
        its own volume and its own document, so the failure mode to revisit is
        divergence, not a lost update.
        """

        with self._lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def mutate(self, apply: MutationFn) -> RuntimeOverlay:
        """Apply one targeted change under the lock and commit it atomically.

        The pure function sees only the *known* portion of the document; the
        rest is carried through unchanged (DD-8).
        """

        with self._locked():
            overlay, payload = self._read_document()
            if overlay.degraded:
                raise DegradedRuntimeFlagsError()
            updated = dict(apply(dict(overlay.flags)))
            self._commit(payload, updated)
            return RuntimeOverlay(degraded=False, flags=updated)

    def clear(self, flag: str) -> RuntimeOverlay:
        """Delete one managed flag's whole runtime entry, cohort included (DD-3)."""

        def _drop(current: dict[str, FlagOverride]) -> dict[str, FlagOverride]:
            current.pop(flag, None)
            return current

        return self.mutate(_drop)

    def scrub_user(self, account_id: str) -> int:
        """Erase one account ID from every parseable cohort; return the count.

        GDPR erasure support, mirroring :meth:`InviteRepository.scrub_user`.
        Idempotent. Raises :class:`DegradedRuntimeFlagsError` rather than
        silently completing when the document cannot be parsed (DD-13), so
        ``AccountService.purge_account`` halts before deleting the account
        record and the maintenance sweep retries.
        """

        with self._locked():
            overlay, payload = self._read_document()
            if overlay.degraded:
                raise DegradedRuntimeFlagsError()
            removed = _scrub_cohorts(payload, account_id)
            if removed:
                self._write(payload)
            return removed

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _commit(
        self, payload: dict[str, Any], updated: Mapping[str, FlagOverride]
    ) -> None:
        for name in MANAGED_FLAGS:
            entry = updated.get(name)
            if entry is None:
                payload.pop(name, None)
                continue
            existing = payload.get(name)
            merged: dict[str, Any] = (
                dict(existing) if isinstance(existing, dict) else {}
            )
            merged[_MODE_FIELD] = entry.mode.value
            merged[_SELECTED_USERS_FIELD] = sorted(set(entry.selected_users))
            payload[name] = merged
        self._write(payload)

    def _write(self, payload: dict[str, Any]) -> None:
        atomic_write(
            self.document_path,
            json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=False) + "\n",
        )


__all__ = [
    "DegradedRuntimeFlagsError",
    "FEATURE_FLAGS_DIRNAME",
    "FeatureFlagOverrideRepository",
    "FlagMode",
    "FlagOverride",
    "MANAGED_FLAGS",
    "RUNTIME_DOCUMENT_FILENAME",
    "RuntimeOverlay",
]
