"""Spec 020 (T132): the content-free ``review-metrics`` read-out.

``python -m app.cli review-metrics --owner <id> --since <date>`` prints the
post-release acceptance numbers (plan "Post-release acceptance"): the weeks
with a counted review (SC-001), the share of "yes" (SC-003), the median active
minutes per mode (SC-004), the SC-005 real-use rate and the on-device share
labelled as an upper bound, and the parks returned. Every figure carries its
sample size; a figure below its minimum sample reads "insufficient". It prints
aggregates only: no title, note, reason, id or other user content.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app import cli
from app.container import Container
from app.core.config import AppEnvironment
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import TaskDocument

from .conftest import FrozenClock

DAY = timedelta(days=1)
SENTINEL = "SENTINEL-METRICS-TEXT"
SINCE = date(2026, 9, 12)  # the frozen clock is 2026-10-09T14:02Z: 4 weeks


def _at(day: date, hour: int = 10) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


class Seeder:
    """Synthetic review rows written straight to the owner's repository."""

    def __init__(self, container: Container, owner_id: str) -> None:
        self.repo = container.task_repo
        self.owner_id = owner_id

    def session(
        self,
        started: datetime,
        *,
        status: str,
        mode: str = "quick",
        qualifying: bool = True,
        clear_start: str | None = None,
        active_seconds: int = 0,
        ended: datetime | None = None,
    ) -> None:
        document = rd.ReviewSessionDocument(
            id=f"review_{uuid.uuid4()}",
            owner_id=self.owner_id,
            mode=mode,  # type: ignore[arg-type]
            entry="list",
            origin="ios",
            status=status,  # type: ignore[arg-type]
            started_at=started,
            last_activity_at=started + timedelta(minutes=20),
            ended_at=ended,
            qualifying_activity=qualifying,
            clear_start=clear_start,  # type: ignore[arg-type]
            active_seconds_by_step={"wins": active_seconds},
        )
        with self.repo.command_lock(self.owner_id):
            self.repo.save_review_session(document)

    def decision(self, ai_use: str, *, request: bool, decided: datetime) -> None:
        document = rd.ReviewDecisionDocument(
            id=f"decision_{uuid.uuid4()}",
            owner_id=self.owner_id,
            task_id="task_0123456789ab",
            decided_at=decided,
            type="extend",
            ai_use=ai_use,  # type: ignore[arg-type]
            navigator_request_id=str(uuid.uuid4()) if request else None,
            task_revision_before=1,
            task_revision_after=2,
            reason_text=SENTINEL,
            review_counts_as="extended",
        )
        with self.repo.command_lock(self.owner_id):
            self.repo.save_review_decision(document)

    def usage(self, day: date, shown: int) -> None:
        with self.repo.command_lock(self.owner_id):
            self.repo.save_navigator_usage(
                rd.NavigatorUsageDocument(
                    owner_id=self.owner_id, day=day, calls=shown + 1, shown=shown
                )
            )

    def park(self, parked: datetime, *, returned: bool) -> None:
        with self.repo.command_lock(self.owner_id):
            self.repo.save_park_ack(
                rd.ReviewParkAckDocument(
                    owner_id=self.owner_id,
                    task_id=f"task_{uuid.uuid4().hex[:12]}",
                    formulation_id=f"form_{uuid.uuid4().hex[:12]}",
                    parked_at=parked,
                    from_revision=1,
                    source="sweep",
                    returned_at=parked + DAY if returned else None,
                )
            )

    def task(self, now: datetime) -> None:
        task = TaskDocument(
            id=f"task_{uuid.uuid4().hex[:12]}",
            owner_id=self.owner_id,
            title=SENTINEL,
            details=SENTINEL,
            state="next",
            order_key=0,
            created_at=now,
            updated_at=now,
        )
        with self.repo.command_lock(self.owner_id):
            self.repo.create(task)


def _seed(seeder: Seeder, now: datetime) -> None:
    week = [SINCE + timedelta(days=7 * index + 1) for index in range(4)]
    # SC-001: counted reviews in weeks 1, 2 and 4; week 3 only has a review
    # completed without activity and an abandoned one, which never count.
    seeder.session(
        _at(week[0]), status="completed", mode="full", ended=_at(week[0], 11)
    )
    seeder.session(_at(week[1]), status="partial", ended=_at(week[1], 12))
    seeder.session(
        _at(week[2]), status="completed_empty", qualifying=False, ended=_at(week[2], 11)
    )
    seeder.session(
        _at(week[2], 14), status="abandoned", qualifying=False, ended=_at(week[2], 15)
    )
    seeder.session(_at(week[3]), status="open")
    # Before the window: never read.
    seeder.session(
        _at(SINCE - 3 * DAY),
        status="completed",
        clear_start="not_really",
        active_seconds=9_999,
        ended=_at(SINCE - 3 * DAY, 11),
    )
    # SC-003 and SC-004: five completed quick reviews (5 yes of 7 answered
    # with the two full ones) and two more completed full reviews; none in
    # week 3, which stays without a counted review.
    for index, seconds in zip((0, 1, 3, 0, 1), (120, 240, 300, 360, 600), strict=True):
        started = _at(week[index], 16)
        seeder.session(
            started,
            status="completed",
            clear_start="yes",
            active_seconds=seconds,
            ended=started + timedelta(minutes=10),
        )
    for seconds in (900, 1_500):
        started = _at(week[1], 18)
        seeder.session(
            started,
            status="completed",
            mode="full",
            clear_start="not_really",
            active_seconds=seconds,
            ended=started + timedelta(minutes=30),
        )
    # SC-005: 20 shown cloud requests (one shown and then abandoned, so with
    # no decision); 11 accepted as is or edited, one not used.
    seeder.usage(week[0], 12)
    seeder.usage(week[2], 8)
    seeder.usage(SINCE - 2 * DAY, 50)
    for index in range(11):
        seeder.decision(
            "as_is" if index % 2 else "edited",
            request=True,
            decided=_at(week[index % 4]),
        )
    seeder.decision("not_used", request=True, decided=_at(week[1]))
    seeder.decision("as_is", request=True, decided=_at(SINCE - DAY))
    # On-device (no server request id): 3 accepted of 5 shown-and-decided.
    for ai_use in ("as_is", "as_is", "edited", "not_used", "not_used"):
        seeder.decision(ai_use, request=False, decided=_at(week[2]))
    for _ in range(4):
        seeder.decision("none", request=False, decided=_at(week[3]))
    # Parks: one of four parks in the window returned.
    for index in range(4):
        seeder.park(_at(week[index]), returned=index == 0)
    seeder.park(_at(SINCE - 5 * DAY), returned=True)
    seeder.task(now)


def _invoke(monkeypatch: pytest.MonkeyPatch, container: Container, *args: str) -> Any:
    monkeypatch.setattr(
        cli,
        "get_config",
        lambda: SimpleNamespace(environment=AppEnvironment.PRODUCTION),
    )
    monkeypatch.setattr(cli, "build_container", lambda _config: container)
    return CliRunner().invoke(cli.app, ["review-metrics", *args])


@pytest.fixture
def seeded(api_client: TestClient, frozen_clock: FrozenClock) -> tuple[Container, str]:
    container: Container = api_client.app.state.container  # type: ignore[attr-defined]
    owner_id: str = api_client.get("/api/auth/me").json()["id"]
    _seed(Seeder(container, owner_id), frozen_clock())
    return container, owner_id


def test_020_SC_001_020_SC_003_020_SC_004_020_SC_005_read_out_prints_each_figure(
    seeded: tuple[Container, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    container, owner_id = seeded
    with allure.step("python -m app.cli review-metrics --owner <id> --since <date>"):
        result = _invoke(
            monkeypatch, container, "--owner", owner_id, "--since", SINCE.isoformat()
        )
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "review-metrics since 2026-09-12 (4 weeks)",
        "SC-001 weeks with a counted review: 3 of 4 (n=4 weeks)",
        'SC-003 clear start "yes": 71% (5 of 7 answered reviews; n=7)',
        "SC-004 median active minutes, quick: 5.0 (n=5 completed reviews)",
        "SC-004 median active minutes, full: insufficient "
        "(n=3 completed reviews; minimum 4)",
        "SC-005 cloud proposals accepted: 55% (11 of 20 shown requests; n=20)",
        "SC-005 on-device proposals accepted, upper bound: 60% "
        "(3 of 5 decisions with on-device proposals; n=5)",
        "Parks returned: 25% (1 of 4 parks; n=4)",
    ]


def test_020_SC_005_read_out_prints_aggregates_only(
    seeded: tuple[Container, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No title, note, reason or id reaches the output."""

    container, owner_id = seeded
    result = _invoke(
        monkeypatch, container, "--owner", owner_id, "--since", SINCE.isoformat()
    )
    assert result.exit_code == 0, result.output
    assert SENTINEL not in result.output
    assert owner_id not in result.output
    assert not re.search(r"\b(review|decision|task|form|user)_[0-9a-f]", result.output)
    for line in result.stdout.splitlines()[1:]:
        assert re.search(r"[(; ]n=\d+", line), line


def test_020_SC_003_read_out_below_the_minimum_sample_is_insufficient(
    api_client: TestClient, frozen_clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An owner with no review rows: every figure reads insufficient or none."""

    container: Container = api_client.app.state.container  # type: ignore[attr-defined]
    owner_id: str = api_client.get("/api/auth/me").json()["id"]
    result = _invoke(
        monkeypatch, container, "--owner", owner_id, "--since", SINCE.isoformat()
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "review-metrics since 2026-09-12 (4 weeks)",
        "SC-001 weeks with a counted review: 0 of 4 (n=4 weeks)",
        'SC-003 clear start "yes": insufficient (n=0 answered reviews; minimum 6)',
        "SC-004 median active minutes, quick: insufficient "
        "(n=0 completed reviews; minimum 4)",
        "SC-004 median active minutes, full: insufficient "
        "(n=0 completed reviews; minimum 4)",
        "SC-005 cloud proposals accepted: insufficient "
        "(n=0 shown requests; minimum 20)",
        "SC-005 on-device proposals accepted, upper bound: none (n=0)",
        "Parks returned: none (n=0)",
    ]


def test_020_SC_001_read_out_rejects_a_future_or_malformed_since(
    api_client: TestClient, frozen_clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    container: Container = api_client.app.state.container  # type: ignore[attr-defined]
    owner_id: str = api_client.get("/api/auth/me").json()["id"]
    future = (frozen_clock() + 2 * DAY).date().isoformat()
    later = _invoke(monkeypatch, container, "--owner", owner_id, "--since", future)
    assert later.exit_code == 2
    malformed = _invoke(monkeypatch, container, "--owner", owner_id, "--since", "x")
    assert malformed.exit_code == 2
