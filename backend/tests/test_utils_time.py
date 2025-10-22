"""Tests for time helper utilities."""
from __future__ import annotations

from datetime import UTC, datetime

from app.utils.time import from_isoformat, timestamp_id, to_isoformat, utcnow


def test_utcnow_returns_aware_datetime() -> None:
    now = utcnow()
    assert now.tzinfo is not None
    assert now.tzinfo == UTC


def test_isoformat_round_trip() -> None:
    instant = datetime(2024, 4, 6, 12, 30, tzinfo=UTC)
    serialized = to_isoformat(instant)
    assert serialized.endswith("Z")
    parsed = from_isoformat(serialized)
    assert parsed == instant


def test_timestamp_id_uses_iso_format() -> None:
    instant = datetime(2024, 4, 6, 13, 15, tzinfo=UTC)
    identifier = timestamp_id("tree", instant)
    assert identifier == "tree::2024-04-06T13:15:00Z"
