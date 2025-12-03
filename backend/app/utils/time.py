"""Time utilities used across the backend."""

from __future__ import annotations

from datetime import UTC, datetime

ISO_8601_Z_SUFFIX = "Z"


def utcnow() -> datetime:
    """Return the current UTC time with timezone information."""

    return datetime.now(tz=UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Convert a datetime to an aware UTC datetime."""

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_isoformat(dt: datetime | None = None, *, timespec: str = "seconds") -> str:
    """Return an ISO-8601 string in UTC with an explicit Z suffix."""

    target = ensure_utc(dt or utcnow())
    iso_value = target.isoformat(timespec=timespec)
    if iso_value.endswith("+00:00"):
        iso_value = iso_value[:-6] + ISO_8601_Z_SUFFIX
    return iso_value


def from_isoformat(value: str) -> datetime:
    """Parse an ISO-8601 string into an aware UTC datetime."""

    normalized = value.strip()
    if normalized.endswith(ISO_8601_Z_SUFFIX):
        normalized = normalized[:-1] + "+00:00"
    return ensure_utc(datetime.fromisoformat(normalized))


def timestamp_id(prefix: str, dt: datetime | None = None) -> str:
    """Generate a stable identifier using UTC timestamps."""

    return f"{prefix}::{to_isoformat(dt)}"


__all__ = ["ensure_utc", "from_isoformat", "timestamp_id", "to_isoformat", "utcnow"]
