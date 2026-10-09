"""Value types for the durable job ledger (spec 026 plan section 5, data-model).

A job moves ``queued -> leased -> succeeded``. A retryable failure or an expired
lease returns it to ``queued`` with bounded backoff, exhausted attempts end in
``failed``, cancellation ends in ``cancelled``, and an external effect whose
outcome is unknown ends in ``reconciliation_required``: that last state is never
claimed again until a person resolves it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

#: plan section 7 internal job defaults.
LEASE = timedelta(seconds=60)
HEARTBEAT = timedelta(seconds=20)
MAX_ATTEMPTS = 5
#: Full-jitter ceilings (seconds) after the 1st..5th failed attempt.
BACKOFF_CAPS: tuple[float, ...] = (1.0, 5.0, 30.0, 120.0, 300.0)

SYSTEM_SCOPE = "system"

_SAFE_ERROR_LIMIT = 120
_UNSAFE = re.compile(r"[^A-Za-z0-9_.:\-]")


class JobStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECONCILIATION_REQUIRED = "reconciliation_required"


#: States that occupy a ``(scope, dedup_key)`` identity.
ACTIVE_STATUSES: tuple[JobStatus, ...] = (
    JobStatus.QUEUED,
    JobStatus.LEASED,
    JobStatus.RECONCILIATION_REQUIRED,
)


def safe_error_code(value: str | None) -> str | None:
    """Reduce an error to a short code: no free text, payloads or paths."""

    if not value:
        return None
    return _UNSAFE.sub("_", value)[:_SAFE_ERROR_LIMIT]


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """What an adapter reports back after running one claimed job."""

    uncertain: bool = False
    safe_error: str | None = None


@dataclass(frozen=True, slots=True)
class JobLease:
    """A claimed job. ``fence`` is the only proof of ownership at settle time."""

    job_id: str
    job_type: str
    scope: str
    dedup_key: str
    payload_ref: str | None
    owner: str
    fence: int
    lease_until: datetime
    attempt: int
    max_attempts: int
    effect_id: str


@dataclass(frozen=True, slots=True)
class JobRecord:
    """Read model for inspection and tests; carries no payload content."""

    job_id: str
    job_type: str
    scope: str
    dedup_key: str
    payload_ref: str | None
    run_at: datetime
    status: JobStatus
    attempts: int
    max_attempts: int
    lease_owner: str | None
    lease_until: datetime | None
    fence: int
    effect_id: str
    last_error: str | None
    correlation_id: str | None
    cancel_requested: bool
