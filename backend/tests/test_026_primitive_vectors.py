"""Spec 026: the shared normalization and calendar vectors hold on the server.

``specs/026-rust-core-sync/contracts/primitive-vectors.json`` is consumed by the
Rust parity tests (``rust/crates/bb-domain/tests/primitives_parity.rs``); this
module proves every row against the backend functions it was generated from, so
the Rust port is compared with the server and not with a copy of itself. The
Swift ``NameNormalizerTests`` / ``CalendarDayTests`` inputs are the rows' source.
"""

from __future__ import annotations

import json
import re
import zoneinfo
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import allure
import pytest

from app.modules.tasks.formulation import due_start
from app.modules.tasks.repository import (
    display_project_name,
    display_tag_name,
    normalize_task_name,
)
from app.modules.tasks.service import TaskService

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTORS_PATH = (
    REPO_ROOT / "specs" / "026-rust-core-sync" / "contracts" / "primitive-vectors.json"
)
VECTORS: dict[str, Any] = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
CALENDAR: dict[str, Any] = VECTORS["calendar"]
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [row["id"] for row in rows]


def _local_day(unix: int, zone: str) -> str:
    return datetime.fromtimestamp(unix, zoneinfo.ZoneInfo(zone)).date().isoformat()


def _strict_iso(value: str) -> date:
    """YYYY-MM-DD with ASCII digits only, as the API's ``due_date`` is sent."""

    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError(value)
    return date.fromisoformat(value)


def test_026_FR_002_primitive_vector_file_has_every_section() -> None:
    """No section is missing or empty, and ids are unique."""

    with allure.step("Check the declared sections"):
        assert VECTORS["schema"] == "brainbuddy-primitive-vectors/v1"
        sections = ["name_normalization", "search", "whitespace", "scalar_length"]
        assert all(VECTORS[name] for name in sections)
        assert all(CALENDAR[name] for name in CALENDAR)
        ids = [row["id"] for name in sections for row in VECTORS[name]]
        ids += _ids(CALENDAR["local_day"]) + _ids(CALENDAR["start_instant"])
        assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    "row", VECTORS["name_normalization"], ids=_ids(VECTORS["name_normalization"])
)
def test_026_FR_002_name_normalization_vector(row: dict[str, Any]) -> None:
    """Project and tag names normalise to the stored and keyed forms."""

    value = row["input"]
    with allure.step("Run the server's name functions"):
        assert display_project_name(value) == row["project_display"]
        assert normalize_task_name(value) == row["project_key"]
        assert display_tag_name(value) == row["tag_display"]
        assert normalize_task_name(value, strip_tag_prefix=True) == row["tag_key"]


@pytest.mark.parametrize("row", VECTORS["search"], ids=_ids(VECTORS["search"]))
def test_026_FR_002_search_key_vector(row: dict[str, Any]) -> None:
    """Task search folds like the server's list filter does."""

    with allure.step("Run the server's search normalisation"):
        if row["input"] is not None:
            assert TaskService._normalize_for_search(row["input"]) == row["search_key"]
        assert TaskService._normalize_search_query(row["input"]) == (
            row["search_query_key"]
        )


@pytest.mark.parametrize("row", VECTORS["whitespace"], ids=_ids(VECTORS["whitespace"]))
def test_026_FR_002_whitespace_vector(row: dict[str, Any]) -> None:
    """``str.strip()`` and ``" ".join(str.split())`` are the whitespace rule."""

    with allure.step("Apply Python's strip and split"):
        assert row["input"].strip() == row["stripped"]
        assert " ".join(row["input"].split()) == row["collapsed"]


@pytest.mark.parametrize(
    "row", VECTORS["scalar_length"], ids=_ids(VECTORS["scalar_length"])
)
def test_026_FR_002_scalar_length_vector(row: dict[str, Any]) -> None:
    """Python counts Unicode scalars; UTF-16 and UTF-8 counts differ."""

    text = row["input"]
    with allure.step("Count scalars, UTF-16 units and UTF-8 bytes"):
        assert len(text) == row["scalars"]
        assert len(text.encode("utf-16-le")) // 2 == row["utf16_units"]
        assert len(text.encode("utf-8")) == row["utf8_bytes"]
        assert (len(text) <= 500) is row["within_500"]


def test_026_FR_017_calendar_day_strict_iso_rows() -> None:
    """Valid rows are real dates; invalid rows are rejected by the strict rule."""

    with allure.step("Parse every valid row"):
        for iso in CALENDAR["valid_iso"]:
            assert _strict_iso(iso).isoformat() == iso
    with allure.step("Reject every invalid row"):
        for iso in CALENDAR["invalid_iso"]:
            with pytest.raises(ValueError):
                _strict_iso(iso)


def test_026_FR_017_calendar_day_arithmetic_rows() -> None:
    """Day numbers, ``add_days`` and February lengths follow ``datetime.date``."""

    with allure.step("Check day numbers and February"):
        for row in CALENDAR["day_number"]:
            assert (date.fromisoformat(row["day"]) - date(1970, 1, 1)).days == (
                row["number"]
            )
        for row in CALENDAR["days_in_february"]:
            first = date(row["year"], 3, 1)
            assert (first - timedelta(days=1)).day == row["days"]
    with allure.step("Add days across months, years and 1582"):
        for row in CALENDAR["add_days"]:
            start = date.fromisoformat(row["start"])
            assert (start + timedelta(days=row["days"])).isoformat() == row["expect"]
    with allure.step("Clamp rows lie outside Python's date range"):
        for row in CALENDAR["clamp"]:
            start = date.fromisoformat(row["start"])
            limit = date.max if row["expect"] == "9999-12-31" else date.min
            assert date.fromisoformat(row["expect"]) == limit
            with pytest.raises((OverflowError, ValueError)):
                start + timedelta(days=row["days"])
            assert limit == (date.max if row["days"] > 0 else date.min)


@pytest.mark.parametrize("row", CALENDAR["local_day"], ids=_ids(CALENDAR["local_day"]))
def test_026_FR_017_local_day_vector(row: dict[str, Any]) -> None:
    """The same instant is a different calendar day in different zones."""

    with allure.step("Convert the instant in its zone"):
        assert _local_day(row["unix"], row["zone"]) == row["day"]


@pytest.mark.parametrize(
    "row", CALENDAR["start_instant"], ids=_ids(CALENDAR["start_instant"])
)
def test_026_FR_017_start_instant_vector_matches_due_start(
    row: dict[str, Any],
) -> None:
    """``due_start`` is the first instant of the day, DST gaps and repeats included."""

    with allure.step("Resolve the day start with the server's due_start"):
        start = due_start(date.fromisoformat(row["day"]), row["zone"])
        assert int((start - EPOCH) / timedelta(seconds=1)) == row["unix"]
    with allure.step("Read the local day just before and at that instant"):
        assert _local_day(row["unix"] - 1, row["zone"]) == row["day_before_instant"]
        assert _local_day(row["unix"], row["zone"]) == row["day_at_instant"]
