"""T029 (PR-29): workflow, operator and job writers cannot bypass receipts/feed.

026-FR-005/011/014/015/021/024 and 026-SC-002/007. With ``rust_core_sync``
effective the Capture task port, the Review maintenance writers (retention,
clock repair, sweep-gap floors, sweep parks, idle close) and the operator seed
are receipts: the Tasks effect and its feed transaction commit together, the
bound job fence and scope are rechecked before anything is written, and the
origin is derived by the server. A static audit pins the inventory of
``contracts/command-catalog.md``; a runtime audit proves no public write
happens outside an owner unit while the boundary is wired.
"""

from __future__ import annotations

import ast
import inspect
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from time import perf_counter_ns
from types import SimpleNamespace
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app import cli
from app import main as app_main
from app.core.config import AppEnvironment
from app.core.rate_limit import navigator_rate_limiter
from app.exceptions import ConflictError
from app.modules.tasks.jobs import JobLease
from app.modules.tasks.jobs.domain import SYSTEM_SCOPE
from app.modules.tasks.jobs.execution import (
    ForgedWriterOriginError,
    JobExecutionGate,
    ScopeRevokedError,
    StaleExecutorError,
)
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.sync.command_handler import LegacyTagCommandHandler
from app.modules.tasks.sync.receipts import ScopeAuthority, SyncCommandError
from app.workflows.voice_brain_dump.task_port import InProcessTaskPort

from .conftest import TEST_USER_EMAIL, FrozenClock
from .test_review_auto_park import keep_alive
from .test_review_navigator import PROVIDER_ENV
from .test_sync_review_projection import Synced

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Task sync writer boundary"),
    allure.story(
        "Workflow, operator and job writers publish through receipts and the feed"
    ),
]

APP = Path(__file__).resolve().parents[1] / "app"
CATALOG = (
    Path(__file__).resolve().parents[2]
    / "specs/026-rust-core-sync/contracts/command-catalog.md"
)
LEASE = timedelta(seconds=60)
JOB_TYPE = "maintenance.writer_boundary"
DAY = timedelta(days=1)
# Rows no client ever reads: idempotency bookkeeping and Navigator usage. Review
# settings outside a unit can only be the per-tick ``last_effective_sweep_at``
# bookkeeping (not in the public settings); a tick that raised the park floor is
# published, and every test using ``bypassed`` also proves feed == stored state.
PRIVATE_RESOURCES = {"Idempotency-Key", "Navigator usage", "Review settings"}


@pytest.fixture(autouse=True)
def _measure_fast_allure_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    # Allure stores millisecond timestamps; a real, sub-ms boundary step can
    # otherwise be misclassified as an empty step by the taxonomy validator.
    original_step = allure.step

    @contextmanager
    def measured_step(title: str) -> Iterator[None]:
        started = perf_counter_ns()
        with original_step(title):
            yield
            elapsed_ns = perf_counter_ns() - started
            if elapsed_ns < 2_000_000:
                allure.attach(str(elapsed_ns), name="Step elapsed nanoseconds")

    monkeypatch.setattr(allure, "step", measured_step)


@pytest.fixture(autouse=True)
def _hermetic_navigator(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(PROVIDER_ENV, "deterministic")
    navigator_rate_limiter.reset()
    yield
    navigator_rate_limiter.reset()


class Admission:
    """The Identity side of the scope authority, closable by a test."""

    def __init__(self) -> None:
        self.open = True

    def __call__(self, unit: Any) -> ScopeAuthority:
        return ScopeAuthority(
            unit.owner_id,
            "server-1",
            "feed-1",
            "access-1",
            "sqlite-1",
            admission_open=self.open,
        )


class Rig:
    """A synced app whose Task service, Review services and jobs share one gate."""

    def __init__(self, synced: Synced) -> None:
        self.s = synced
        self.admission = Admission()
        self.live = {synced.owner}
        container = synced.container
        self.service = container.task_service
        self.review = container.review_service
        self.repo = synced.repo
        boundary = synced.boundary
        boundary._authority = self.admission
        self.service._legacy_tag_handler = LegacyTagCommandHandler(
            boundary._receipts,
            boundary._units,
            self.admission,
            self.service._rust_facade,
            self.repo,
        )
        users = container.user_repo
        self.gate = JobExecutionGate(
            container.job_repository,
            owner_current=lambda owner: owner in self.live,
            owner_exists=lambda owner: users.get_by_id(owner) is not None,
            now=synced.clock,
        )
        self.port = InProcessTaskPort(self.service.create_native_inbox_task)

    def claim(self, key: str = "boundary") -> JobLease:
        jobs = self.s.container.job_repository
        jobs.ensure_scheduled(
            job_type=JOB_TYPE, dedup_key=key, run_at=self.s.clock(), scope=SYSTEM_SCOPE
        )
        lease = jobs.claim_due(
            owner="w1", types=(JOB_TYPE,), now=self.s.clock(), lease_for=LEASE
        )
        assert lease is not None
        return lease

    def capture(self, key: str, title: str = "Buy milk") -> Any:
        return self.port.create_native_inbox_task(
            owner_id=self.s.owner,
            title=title,
            source_capture_ids=["capture_1"],
            idempotency_key=key,
        )

    def receipts(self) -> list[tuple[str, str]]:
        return [
            (r["writer_origin"], json.loads(r["metadata"])["outcome"])
            for r in self.s._rows(
                "SELECT writer_origin, metadata FROM sync_command_receipts "
                "WHERE owner_id=? ORDER BY created_at, command_id",
                self.s.owner,
            )
        ]

    def origins(self) -> list[str]:
        return [origin for origin, _ in self.receipts()]

    def tasks(self) -> list[Any]:
        return self.repo.list_for_owner(owner_id=self.s.owner)

    def published_tasks(self) -> dict[str, dict[str, Any]]:
        return {
            c_value["id"]: c_value
            for (entity, _), c_value in self.s.folded().items()
            if entity == "task"
        }

    def consistent(self) -> None:
        """The feed folded in order equals every stored public record."""

        assert self.s.review_base() == self.s.snapshot()
        published = self.published_tasks()
        for task in self.tasks():
            if task.id in published:
                assert published[task.id]["revision"] == str(task.revision)
                assert published[task.id]["state"] == task.state


@pytest.fixture
def rig(api_client: TestClient, frozen_clock: FrozenClock) -> Rig:
    return Rig(Synced(api_client, frozen_clock))


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """Every repository write from now on: ``(resource, inside_an_owner_unit)``."""

    log: list[tuple[str, bool]] = []
    original = TaskRepository._note_write

    def spy(self: TaskRepository, owner_id: str, resource: str, record_id: str) -> None:
        log.append((resource, self.active_unit() is not None))
        original(self, owner_id, resource, record_id)

    monkeypatch.setattr(TaskRepository, "_note_write", spy)
    return log


def bypassed(log: list[tuple[str, bool]]) -> list[str]:
    return [r for r, in_unit in log if not in_unit and r not in PRIVATE_RESOURCES]


# --------------------------------------------------------------- the inventory
# Every call site of the Tasks store's write API outside the repository, with how
# it reaches the boundary. ``routed`` writers publish; an ``exception`` is named in
# contracts/command-catalog.md. A new site fails the audit until it is catalogued.
WRITE_PREFIXES = ("create", "save", "delete", "purge")
INVENTORY: dict[str, tuple[str, set[str]]] = {
    "modules/tasks/service.py": (
        "routed: serialized_write dispatches REST/MCP/CLI/workflow commands",
        {
            "create",
            "create_comment",
            "create_project",
            "create_subtask",
            "create_tag",
            "purge_expired_idempotency",
            "save",
            "save_comment",
            "save_idempotency",
            "save_park_ack",
            "save_project",
            "save_subtask",
            "save_tag",
        },
    ),
    "modules/tasks/sync/command_handler.py": (
        "the boundary: every write sits inside its receipt unit",
        {
            "create",
            "create_project",
            "create_tag",
            "purge_expired_idempotency",
            "save",
            "save_park_ack",
            "save_project",
            "save_tag",
        },
    ),
    "modules/tasks/review_service.py": (
        "routed: Review commands via serialized_write, maintenance via internal_write",
        {
            "create",
            "delete_navigator_usage_before",
            "delete_review_decision",
            "delete_review_receipt",
            "delete_task_record",
            "purge_expired_idempotency",
            "save",
            "save_bulk_release",
            "save_park_ack",
            "save_review_decision",
            "save_review_receipt",
            "save_review_session",
            "save_review_settings",
        },
    ),
    "modules/tasks/review_flow.py": (
        "routed: run commands via serialized_write, idle close via internal_write",
        {"save_review_session"},
    ),
    "modules/tasks/navigator.py": (
        "routed: consent grant/revoke via the Review boundary; usage is private",
        {"save_idempotency", "save_navigator_consent", "save_navigator_usage"},
    ),
    "cli.py": (
        "routed: the TEST-only seed backdates through ReviewService.internal_write",
        {"save"},
    ),
    "services/account_service.py": (
        "exception: GDPR purge is a control operation, not a task command",
        {"delete_all_for_owner"},
    ),
}


def _write_api() -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(TaskRepository, inspect.isfunction)
        if name.startswith(WRITE_PREFIXES)
    }


def _call_sites() -> dict[str, set[str]]:
    api = _write_api()
    found: dict[str, set[str]] = {}
    for path in APP.rglob("*.py"):
        relative = path.relative_to(APP).as_posix()
        if relative in {
            "modules/tasks/repository.py",
            "modules/tasks/review_repository.py",
        }:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            ):
                continue
            receiver = ast.unparse(node.func.value)
            if node.func.attr in api and (
                receiver.endswith("task_repo") or receiver in {"self._repo", "repo"}
            ):
                found.setdefault(relative, set()).add(node.func.attr)
    return found


def test_026_FR_014_every_task_store_write_site_is_inventoried(
    rig: Rig,
) -> None:
    """A writer outside the catalogued inventory is a bypass: the audit fails."""

    with allure.step("scan the backend for Tasks store write call sites"):
        sites = _call_sites()
    with allure.step("the sites and their write calls equal the inventory"):
        assert {k: sorted(v) for k, v in sites.items()} == {
            k: sorted(v) for k, (_, v) in INVENTORY.items()
        }
    with allure.step("routes, MCP and workflows reach the store only via services"):
        assert not [site for site in sites if site.startswith(("api/", "workflows/"))]
    with allure.step("the catalog names every inventoried writer file"):
        catalog = CATALOG.read_text()
        for site in INVENTORY:
            assert site.rsplit("/", 1)[-1] in catalog, site


def test_026_FR_014_job_origin_locks_are_taken_only_through_the_boundary(
    rig: Rig,
) -> None:
    """``owner_write_lock`` has exactly the catalogued callers."""

    callers = {
        path.relative_to(APP).as_posix()
        for path in APP.rglob("*.py")
        if any(
            isinstance(node, ast.Call)
            and ast.unparse(node.func).endswith("owner_write_lock")
            for node in ast.walk(ast.parse(path.read_text()))
        )
    }
    assert callers == {
        "modules/tasks/service.py",
        "modules/tasks/review_service.py",
        "modules/tasks/sync/command_handler.py",
        "modules/tasks/sync/unit_of_work.py",
    }


# ------------------------------------------------------------- Capture task port
def test_026_FR_005_capture_task_is_one_receipt_with_the_feed_and_keeps_its_record(
    rig: Rig, writes: list[tuple[str, bool]]
) -> None:
    """The Tasks effect and its feed transaction commit together; the commit
    record stays the replay source until account purge."""

    s, clock = rig.s, rig.s.clock
    with allure.step("a confirmed Capture action creates one Inbox task"):
        task = rig.capture("voice-commit-1")
        assert (task.state, task.source_capture_ids) == ("inbox", ["capture_1"])
    with allure.step("one receipt, one feed transaction holding the task"):
        assert rig.origins() == ["legacy"]
        assert [[c["entity_type"] for c in t["changes"]] for t in s.transactions()] == [
            ["task"]
        ]
        assert rig.published_tasks()[task.id]["title"] == "Buy milk"
        assert bypassed(writes) == []
    with allure.step("a replay answers the same task and adds no feed commit"):
        again = rig.capture("voice-commit-1")
        assert again.id == task.id and len(rig.tasks()) == 1
        assert len(s.transactions()) == 1
    with allure.step("the commit record outlives the 24 hour purge"):
        clock.advance(days=3)
        rig.repo.purge_expired_idempotency(owner_id=s.owner, now=clock())
        survivor = rig.repo.get_idempotency(owner_id=s.owner, key="voice-commit-1")
        assert survivor is not None and survivor.command == "create_native_inbox_task"
        assert rig.capture("voice-commit-1").id == task.id
        assert len(s.transactions()) == 1
    with (
        allure.step("the same key for another action is a conflict"),
        pytest.raises(ConflictError),
    ):
        rig.capture("voice-commit-1", title="Another action")


def test_026_FR_014_job_bound_capture_derives_job_origin_and_replays_across_origins(
    rig: Rig,
) -> None:
    """The origin is never an input, and a retry under another origin finds the
    kept commit record instead of creating a second task."""

    lease = rig.claim()
    with allure.step("under a bound execution the receipt origin is job"):
        with rig.gate.executing(lease):
            task = rig.capture("voice-commit-2")
        assert rig.origins() == ["job"]
        assert rig.published_tasks()[task.id]["title"] == "Buy milk"
    with allure.step("a retry outside the job adopts the same task"):
        retried = rig.capture("voice-commit-2")
        assert retried.id == task.id and len(rig.tasks()) == 1
        assert len(rig.s.transactions()) == 1
        rig.consistent()
    with allure.step("a caller-supplied origin is refused before any write"):
        with pytest.raises(ForgedWriterOriginError):
            rig.service.create_native_inbox_task(
                owner_id=rig.s.owner,
                title="Forged",
                source_capture_ids=[],
                idempotency_key="voice-commit-forged",
                writer_origin="job",
            )
        assert len(rig.tasks()) == 1


def test_026_SC_007_capture_task_fails_before_mutation_on_revoked_authority_or_stale_fence(
    rig: Rig,
) -> None:
    s = rig.s
    with allure.step("closed admission refuses the command and rolls it back"):
        rig.admission.open = False
        with pytest.raises(SyncCommandError) as refused:
            rig.capture("voice-revoked")
        assert refused.value.code == "RESOURCE_NOT_FOUND"
        rig.admission.open = True
        assert rig.tasks() == [] and rig.receipts() == []
        assert rig.repo.get_idempotency(owner_id=s.owner, key="voice-revoked") is None
    with allure.step("a cancelled lease cannot create a task"):
        lease = rig.claim()
        s.container.job_repository.cancel(lease.job_id)
        with rig.gate.executing(lease), pytest.raises(StaleExecutorError):
            rig.capture("voice-stale")
        assert rig.tasks() == [] and rig.receipts() == []
    with allure.step("an owner whose deletion began is not current for job writes"):
        live = rig.claim("revoked-scope")
        rig.live.discard(s.owner)
        with rig.gate.executing(live), pytest.raises(ScopeRevokedError):
            rig.capture("voice-deleting")
        assert rig.tasks() == [] and s.transactions() == []


# ------------------------------------------------------------ Review maintenance
def _activate(rig: Rig) -> None:
    response = rig.s.post("/api/review/explainer/acknowledge", {"time_zone": "UTC"})
    assert response.status_code == 200, response.text


def _decided(rig: Rig) -> str:
    """One live decision whose seven-day Undo snapshot is still stored."""

    _activate(rig)
    waiting = rig.s.api.create("Quote", state="waiting", waiting_for="Ann")
    decided = rig.s.api.decide_raw(waiting, "follow_up", title="Call Ann")
    assert decided.status_code == 200, decided.text
    return str(decided.json()["decision"]["id"])


def test_026_FR_014_sweep_park_publishes_task_marker_and_receipt_in_one_commit(
    rig: Rig, writes: list[tuple[str, bool]]
) -> None:
    s = rig.s
    _activate(rig)
    task = s.api.create("Call Bob", state="next")
    s.clock.advance(days=21)
    keep_alive(s.container)
    writes.clear()
    before = len(s.transactions())
    with allure.step("one sweep parks the lapsed Next task"):
        result = app_main._run_review_maintenance_sweep(s.container)
        assert result is not None and result.parked == 1
    with allure.step("the park is one transaction: task, marker, no private member"):
        assert len(s.transactions()) == before + 1
        assert {c["entity_type"] for c in s.transactions()[-1]["changes"]} == {
            "task",
            "review_park_ack",
        }
        assert rig.published_tasks()[task["id"]]["state"] == "someday"
        assert bypassed(writes) == []
        rig.consistent()
    with allure.step("the receipt names the scheduler as the derived origin"):
        assert rig.origins()[-1] == "legacy"
    with allure.step("the next tick finds nothing and adds no receipt or feed noise"):
        receipts, transactions = len(rig.receipts()), len(s.transactions())
        s.clock.advance(minutes=1)
        keep_alive(s.container)
        app_main._run_review_maintenance_sweep(s.container)
        assert (len(rig.receipts()), len(s.transactions())) == (receipts, transactions)


def test_026_FR_014_job_bound_sweep_uses_job_origin_and_the_auto_park_effect_key(
    rig: Rig, writes: list[tuple[str, bool]]
) -> None:
    s = rig.s
    _activate(rig)
    task = s.api.create("Call Bob", state="next")
    s.clock.advance(days=21)
    keep_alive(s.container)
    writes.clear()
    lease = rig.claim()
    with allure.step("the claimed lease binds the sweep"):
        with rig.gate.executing(lease):
            result = s.container.review_service.run_maintenance_sweep()
        assert result.parked == 1
    with allure.step("the park receipt is job-origin and complete"):
        assert rig.origins()[-1] == "job"
        assert rig.published_tasks()[task["id"]]["state"] == "someday"
        assert bypassed(writes) == []
        rig.consistent()
    with allure.step("a retry of the same occurrence repeats no effect"):
        count = len(s.transactions())
        with rig.gate.executing(lease):
            s.container.review_service.run_maintenance_sweep()
        assert len(s.transactions()) == count


def test_026_FR_014_clock_repair_and_the_gap_floor_publish_their_public_state(
    rig: Rig, writes: list[tuple[str, bool]]
) -> None:
    from .test_review_auto_park import seed_old_next_task

    s = rig.s
    _activate(rig)
    broken = seed_old_next_task(s.api, age=5 * DAY, clock=False)
    s.clock.advance(days=2)
    writes.clear()
    with allure.step("a sweep after a gap raises the floor and repairs the clock"):
        result = app_main._run_review_maintenance_sweep(s.container)
        assert result is not None and (result.repaired, result.gap_floors) == (1, 1)
    with allure.step("both are public changes committed with their receipts"):
        kinds = [
            {c["entity_type"] for c in t["changes"]} for t in s.transactions()[-2:]
        ]
        assert {"review_settings"} in kinds and {"task"} in kinds
        floor = next(v for k, v in s.folded().items() if k[0] == "review_settings")[
            "owner_park_floor_at"
        ]
        assert floor is not None
        assert rig.published_tasks()[broken.id]["revision"] == str(broken.revision)
        assert bypassed(writes) == []
        rig.consistent()
    with allure.step("a sweep inside the gap changes nothing public"):
        receipts, transactions = len(rig.receipts()), len(s.transactions())
        s.clock.advance(minutes=1)
        app_main._run_review_maintenance_sweep(s.container)
        assert (len(rig.receipts()), len(s.transactions())) == (receipts, transactions)


def test_026_FR_014_retention_nulls_snapshots_and_publishes_the_public_change(
    rig: Rig, writes: list[tuple[str, bool]]
) -> None:
    s = rig.s
    _decided(rig)
    s.clock.advance(days=8)
    with allure.step("a decision still advertises its Undo deadline"):
        decision = next(v for k, v in s.folded().items() if k[0] == "review_decision")
        assert "undo_available_until" in decision
    writes.clear()
    with allure.step("retention nulls the seven-day snapshots"):
        nulled, _closed = s.container.review_service.run_review_retention(s.clock())
        assert nulled >= 1
    with allure.step("the deadline leaves the feed in the same commit"):
        decision = next(v for k, v in s.folded().items() if k[0] == "review_decision")
        assert decision["undo_available_until"] is None
        assert bypassed(writes) == []
        rig.consistent()
    with allure.step("a second pass finds nothing to publish"):
        receipts = len(rig.receipts())
        assert s.container.review_service.run_review_retention(s.clock()) == (0, 0)
        assert len(rig.receipts()) == receipts


def test_026_FR_015_retention_still_runs_for_an_owner_whose_deletion_began(
    rig: Rig,
) -> None:
    s = rig.s
    _decided(rig)
    s.clock.advance(days=8)
    lease = rig.claim()
    rig.live.discard(s.owner)
    with (
        allure.step("an ordinary job write is refused: the owner is not current"),
        rig.gate.executing(lease),
        pytest.raises(ScopeRevokedError),
    ):
        rig.capture("deleting-owner")
    with allure.step("cleanup retention is the narrower check and publishes"):
        before = len(s.transactions())
        with rig.gate.executing(lease):
            nulled, _ = s.container.review_service.run_review_retention(s.clock())
        assert nulled >= 1 and len(s.transactions()) == before + 1
        assert rig.origins()[-1] == "job"
        rig.consistent()


def test_026_SC_007_stale_fence_stops_retention_and_idle_close_before_mutation(
    rig: Rig,
) -> None:
    s = rig.s
    _decided(rig)
    s.clock.advance(days=8)
    session = s.api.start()
    s.clock.advance(days=8)
    lease = rig.claim()
    s.container.job_repository.cancel(lease.job_id)
    state = (len(rig.receipts()), len(s.transactions()))
    with (
        allure.step("retention and idle close both stop at the fence"),
        rig.gate.executing(lease),
    ):
        with pytest.raises(StaleExecutorError):
            s.container.review_service.run_review_retention(s.clock())
        with pytest.raises(StaleExecutorError):
            s.container.review_flow_service.close_idle_sessions(s.owner, s.clock())
    with allure.step("nothing was written, published or received"):
        assert (len(rig.receipts()), len(s.transactions())) == state
        assert s.repo.get_review_session(s.owner, session["id"]).status == "open"
    with allure.step("revoked admission refuses the idle close before mutation"):
        rig.admission.open = False
        with pytest.raises(SyncCommandError):
            s.container.review_flow_service.close_idle_sessions(s.owner, s.clock())
        rig.admission.open = True
        assert s.repo.get_review_session(s.owner, session["id"]).status == "open"


def test_026_FR_014_idle_close_publishes_the_ended_run_with_its_queue(
    rig: Rig, writes: list[tuple[str, bool]]
) -> None:
    s = rig.s
    session = s.api.start()
    s.clock.advance(days=8)
    writes.clear()
    with allure.step("the sweep closes the run idle for seven days"):
        result = app_main._run_review_maintenance_sweep(s.container)
        assert result is not None and result.closed == 1
    with allure.step("the ended run and its queue are one feed commit"):
        assert {c["entity_type"] for c in s.transactions()[-1]["changes"]} >= {
            "review_session",
            "review_decision_queue",
        }
        ended = next(v for k, v in s.folded().items() if k[0] == "review_session")
        assert ended["id"] == session["id"] and ended["status"] != "open"
        assert bypassed(writes) == []
        rig.consistent()


# ------------------------------------------------------------- operator paths
def test_026_FR_024_operator_seed_and_sweep_publish_through_the_same_boundary(
    rig: Rig, writes: list[tuple[str, bool]], monkeypatch: pytest.MonkeyPatch
) -> None:
    s = rig.s
    monkeypatch.setattr(
        cli, "get_config", lambda: SimpleNamespace(environment=AppEnvironment.TEST)
    )
    monkeypatch.setattr(cli, "build_container", lambda _config: s.container)
    runner = CliRunner()
    with allure.step("the TEST-only seed creates and backdates a task"):
        seeded = runner.invoke(
            cli.app,
            ["review-seed-aged-task", "--email", TEST_USER_EMAIL, "--days", "22"],
        )
        assert seeded.exit_code == 0, seeded.output
        task_id = seeded.stdout.strip()
    with allure.step("the backdated clock is in the feed, not only in storage"):
        published = rig.published_tasks()[task_id]
        stored = rig.repo.get_for_owner(task_id, owner_id=s.owner)
        assert published["formulation"]["started_at"].startswith(
            stored.formulation_started_at.strftime("%Y-%m-%dT%H:%M:%S")
        )
    with allure.step("the operator sweep parks it through the boundary"):
        swept = runner.invoke(cli.app, ["review-run-sweep"])
        assert swept.exit_code == 0, swept.output
        assert rig.published_tasks()[task_id]["state"] == "someday"
    with allure.step("no public write left an owner unit"):
        assert bypassed(writes) == []
        rig.consistent()
