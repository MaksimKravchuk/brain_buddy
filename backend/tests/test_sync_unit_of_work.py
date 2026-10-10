"""One explicit SQLite unit of work for Tasks, Review and job intents (spec 026 PR-25).

026-FR-006, 026-FR-014, 026-FR-015, 026-SC-002, 026-SC-007. These tests run the
real ``TaskRepository`` and ``JobRepository`` over the shared ``tasks.sqlite3``
file. They prove that every aggregate write -- Tasks, Review and the generated
job intents -- is made on one connection, becomes visible in one commit and is
rolled back together; that a read set is loaded under the owner lock and a stale
one is refused; and that a stale or revoked job never opens a unit.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.container import Container
from app.exceptions import ConflictError, RepositoryError
from app.modules.tasks import TaskRepository
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import (
    IdempotencyRecord,
    ProjectDocument,
    TagDocument,
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)
from app.modules.tasks.jobs import JobLease, JobRepository
from app.modules.tasks.jobs.domain import SYSTEM_SCOPE
from app.modules.tasks.jobs.execution import (
    JobExecutionGate,
    ScopeRevokedError,
    StaleExecutorError,
)
from app.modules.tasks.sync.unit_of_work import (
    JobIntent,
    OwnerUnitOfWork,
    ReadSetChangedError,
    TaskUnitOfWork,
    UnitOfWorkError,
)

OWNER = "user_uow_a"
OTHER = "user_uow_b"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
JOB_TYPE = "sync.uow"


@pytest.fixture()
def repo(data_dir: Path) -> TaskRepository:
    return TaskRepository(data_dir)


@pytest.fixture()
def jobs(repo: TaskRepository) -> JobRepository:
    return JobRepository(repo.db_path)


@pytest.fixture()
def uow(repo: TaskRepository, jobs: JobRepository) -> TaskUnitOfWork:
    return TaskUnitOfWork(repo, jobs)


def make_task(
    task_id: str, *, owner: str = OWNER, title: str = "Write it"
) -> TaskDocument:
    return TaskDocument(
        id=task_id,
        owner_id=owner,
        title=title,
        state="inbox",
        order_key=0,
        created_at=T0,
        updated_at=T0,
    )


def make_project(project_id: str, *, owner: str = OWNER) -> ProjectDocument:
    return ProjectDocument(
        id=project_id, owner_id=owner, name="Plan", created_at=T0, updated_at=T0
    )


def make_tag(tag_id: str, *, owner: str = OWNER) -> TagDocument:
    return TagDocument(
        id=tag_id, owner_id=owner, name="home", created_at=T0, updated_at=T0
    )


def make_decision(decision_id: str, task_id: str) -> rd.ReviewDecisionDocument:
    return rd.ReviewDecisionDocument(
        id=decision_id,
        owner_id=OWNER,
        task_id=task_id,
        decided_at=T0,
        type="complete",
        task_revision_before=1,
        task_revision_after=2,
        review_counts_as="done",
    )


def intent(key: str = "uow:one", *, scope: str = OWNER) -> JobIntent:
    return JobIntent(job_type=JOB_TYPE, dedup_key=key, run_at=T0, scope=scope)


def write_aggregate(unit: OwnerUnitOfWork, repo: TaskRepository) -> None:
    """Touch Tasks, every task child table, Review and the idempotency ledger."""

    repo.create_project(make_project("p1"))
    repo.create_tag(make_tag("g1"))
    task = make_task("t1").model_copy(update={"project_id": "p1", "tag_ids": ["g1"]})
    repo.create(task)
    repo.create_subtask(
        TaskSubtaskDocument(
            id="s1",
            owner_id=OWNER,
            task_id="t1",
            title="sub",
            order_key=0,
            created_at=T0,
            updated_at=T0,
        )
    )
    repo.create_comment(
        TaskCommentDocument(
            id="c1",
            owner_id=OWNER,
            task_id="t1",
            actor_id=OWNER,
            body="hi",
            created_at=T0,
        )
    )
    repo.save_idempotency(
        owner_id=OWNER,
        record=IdempotencyRecord(
            key="k1",
            command="create_task",
            request_hash="h",
            resource_id="t1",
            response_body={},
            created_at=T0,
        ),
    )
    repo.save_review_settings(rd.ReviewSettingsDocument(owner_id=OWNER))
    repo.save_review_decision(make_decision("d1", "t1"))
    assert unit.schedule(intent()) is True


def counts(db_path: Path) -> dict[str, int]:
    tables = (
        "projects",
        "tags",
        "tasks",
        "task_tags",
        "subtasks",
        "comments",
        "idempotency_records",
        "review_settings",
        "review_decisions",
        "jobs",
    )
    conn = sqlite3.connect(db_path)
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[
                0
            ]  # noqa: S608
            for table in tables
        }
    finally:
        conn.close()


def mirror_files(repo: TaskRepository) -> list[Path]:
    return sorted(
        path
        for directory in ("tasks", "projects", "contexts", "task-subtasks")
        for path in repo.resolve(directory).glob("**/*.json")
    )


# --- one commit, one rollback ---------------------------------------------------


def test_026_FR_006_a_failure_rolls_back_tasks_review_and_job_intents_together(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    before = counts(repo.db_path)

    with pytest.raises(RuntimeError, match="boom"), uow.begin(OWNER) as unit:
        write_aggregate(unit, repo)
        assert counts(repo.db_path) == before  # not visible from outside yet
        raise RuntimeError("boom")

    assert counts(repo.db_path) == before
    assert mirror_files(repo) == []


def test_026_SC_002_every_aggregate_write_and_job_intent_shares_one_commit(
    repo: TaskRepository,
    uow: TaskUnitOfWork,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[tuple[int, str]] = []
    real_connect = repo._connect

    def traced_connect() -> sqlite3.Connection:
        conn = real_connect()
        conn.set_trace_callback(lambda sql: statements.append((id(conn), sql)))
        return conn

    monkeypatch.setattr(repo, "_connect", traced_connect)

    with uow.begin(OWNER) as unit:
        write_aggregate(unit, repo)
        assert mirror_files(repo) == []  # mirrors wait for the commit

    writers = {
        conn_id
        for conn_id, sql in statements
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    }
    assert len(writers) == 1
    only = next(iter(writers))
    trail = [sql.split()[0].upper() for conn_id, sql in statements if conn_id == only]
    assert trail.count("COMMIT") == 1
    assert trail[-1] == "COMMIT"
    assert trail.count("BEGIN") == 1
    assert any("INTO jobs" in sql for _, sql in statements)
    assert counts(repo.db_path) == {
        "projects": 1,
        "tags": 1,
        "tasks": 1,
        "task_tags": 1,
        "subtasks": 1,
        "comments": 1,
        "idempotency_records": 1,
        "review_settings": 1,
        "review_decisions": 1,
        "jobs": 1,
    }
    assert len(mirror_files(repo)) == 4  # task, project, tag, subtask


def test_026_FR_006_the_unit_records_each_write_it_made_in_order(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    with uow.begin(OWNER) as unit:
        write_aggregate(unit, repo)
        written = [(w.resource, w.record_id) for w in unit.writes]

    assert written == [
        ("Project", "p1"),
        ("Tag", "g1"),
        ("Task", "t1"),
        ("Task subtask", "s1"),
        ("Task comment", "c1"),
        ("Idempotency-Key", "k1"),
        ("Review settings", OWNER),
        ("Review decision", "d1"),
    ]
    assert {w.owner_id for w in unit.writes} == {OWNER}


def test_026_FR_015_replaying_the_same_intent_creates_one_job(
    repo: TaskRepository, uow: TaskUnitOfWork, jobs: JobRepository
) -> None:
    with uow.begin(OWNER) as unit:
        assert unit.schedule(intent("uow:dedup")) is True
        assert unit.schedule(intent("uow:dedup")) is False
        assert unit.intents == (intent("uow:dedup"),)

    job = jobs.find_active("uow:dedup", scope=OWNER)
    assert job is not None
    assert counts(repo.db_path)["jobs"] == 1


def test_026_FR_006_writes_outside_a_unit_keep_their_own_commit_and_mirror(
    repo: TaskRepository, jobs: JobRepository
) -> None:
    repo.create(make_task("solo"))

    assert counts(repo.db_path)["tasks"] == 1
    assert len(mirror_files(repo)) == 1


def test_026_FR_006_a_mirror_failure_after_commit_does_not_undo_the_commit(
    repo: TaskRepository,
    uow: TaskUnitOfWork,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("app.modules.tasks.review_repository.write_json", refuse)

    with uow.begin(OWNER):
        repo.create(make_task("kept"))

    assert counts(repo.db_path)["tasks"] == 1
    assert mirror_files(repo) == []


def test_026_FR_006_undoing_a_created_task_removes_its_mirror_only_on_commit(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    repo.create(make_task("undo"))
    assert len(mirror_files(repo)) == 1

    with pytest.raises(RuntimeError), uow.begin(OWNER):
        repo.delete_task_record(OWNER, "undo")
        raise RuntimeError("abort")
    assert counts(repo.db_path)["tasks"] == 1
    assert len(mirror_files(repo)) == 1

    with uow.begin(OWNER):
        repo.delete_task_record(OWNER, "undo")
    assert counts(repo.db_path)["tasks"] == 0
    assert mirror_files(repo) == []


# --- commit races --------------------------------------------------------------


def probe(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 0")
    return conn


def test_026_SC_002_no_other_writer_or_reader_sees_a_partial_commit(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    other = probe(repo.db_path)
    try:
        with uow.begin(OWNER) as unit:
            write_aggregate(unit, repo)
            # The write lock is held for the whole unit, job intents included.
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
            # A concurrent reader sees the state from before the unit, whole.
            assert other.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
            assert other.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0

        assert other.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert other.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert other.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 1
        other.execute("BEGIN IMMEDIATE")
        other.rollback()
    finally:
        other.close()


def test_026_FR_006_a_second_writer_waits_for_the_commit_and_sees_all_of_it(
    repo: TaskRepository, uow: TaskUnitOfWork, jobs: JobRepository
) -> None:
    inside = threading.Event()
    attempting = threading.Event()
    seen: list[tuple[int, int, int]] = []

    def second_writer() -> None:
        inside.wait()
        attempting.set()
        with uow.begin(OWNER):  # blocks on the owner lock until the first commits
            seen.append(
                (
                    len(repo.list_for_owner(owner_id=OWNER)),
                    len(repo.list_review_decisions(OWNER)),
                    int(jobs.find_active("uow:one", scope=OWNER) is not None),
                )
            )

    worker = threading.Thread(target=second_writer)
    worker.start()
    try:
        with uow.begin(OWNER) as unit:
            inside.set()
            attempting.wait()
            write_aggregate(unit, repo)
    finally:
        worker.join(timeout=30)

    assert not worker.is_alive()
    assert seen == [(1, 1, 1)]


def test_026_FR_006_a_read_set_loaded_under_the_lock_is_owner_scoped(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    repo.create_project(make_project("p1"))
    repo.create_tag(make_tag("g1"))
    repo.create(make_task("t1"))
    repo.create(make_task("theirs", owner=OTHER))

    with uow.begin(OWNER) as unit:
        read_set = unit.load(
            tasks=("t1", "theirs", "t1"), projects=("p1", "nope"), tags=("g1",)
        )

    assert read_set.owner_id == OWNER
    assert read_set.tasks["t1"] is not None
    assert read_set.tasks["theirs"] is None  # another owner's task reads as absent
    assert read_set.projects == {"p1": read_set.projects["p1"], "nope": None}
    assert read_set.tags["g1"] is not None


def test_026_FR_006_a_stale_read_set_is_refused_and_nothing_is_written(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    repo.create(make_task("t1"))
    with uow.begin(OWNER) as unit:
        read_set = unit.load(tasks=("t1", "later"))
        unit.verify(read_set)  # unchanged inside the same unit: fine

    # Another command changes one row and creates the one the first saw absent.
    with uow.begin(OWNER):
        repo.save(make_task("t1", title="Changed elsewhere"))
    before = counts(repo.db_path)

    with pytest.raises(ReadSetChangedError) as stale, uow.begin(OWNER) as unit:
        unit.verify(read_set)
        repo.create_project(make_project("never"))

    assert isinstance(stale.value, ConflictError)
    assert stale.value.identifier == "t1"
    assert counts(repo.db_path) == before

    repo.create(make_task("later"))
    with pytest.raises(ReadSetChangedError) as created, uow.begin(OWNER) as unit:
        fresh = unit.load(tasks=("t1",))
        unit.verify(fresh)  # current rows verify against themselves
        unit.verify(
            read_set.__class__(
                owner_id=OWNER,
                tasks={"later": None},
                projects={},
                tags={},
                fingerprints={("Task", "later"): None},
            )
        )
    assert created.value.identifier == "later"


def test_026_FR_006_a_read_set_cannot_be_verified_for_another_owner(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    with uow.begin(OTHER) as unit:
        foreign = unit.load(tasks=("x",))

    with pytest.raises(UnitOfWorkError, match="another owner"):
        with uow.begin(OWNER) as unit:
            unit.verify(foreign)


# --- boundaries that keep the unit honest ---------------------------------------


def test_026_FR_014_a_write_for_another_owner_is_refused_inside_the_unit(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    with pytest.raises(UnitOfWorkError, match="owner"), uow.begin(OWNER):
        repo.create(make_task("mine"))
        repo.create(make_task("theirs", owner=OTHER))

    assert counts(repo.db_path)["tasks"] == 0


def test_026_FR_014_a_review_write_for_another_owner_is_refused_inside_the_unit(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    with pytest.raises(UnitOfWorkError), uow.begin(OWNER):
        repo.save_review_settings(rd.ReviewSettingsDocument(owner_id=OTHER))

    assert counts(repo.db_path)["review_settings"] == 0


def test_026_FR_014_a_job_intent_may_not_reach_another_owners_scope(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    with pytest.raises(UnitOfWorkError, match="scope"), uow.begin(OWNER) as unit:
        unit.schedule(intent("uow:foreign", scope=OTHER))

    with uow.begin(OWNER) as unit:
        assert unit.schedule(intent("uow:system", scope=SYSTEM_SCOPE)) is True


def test_026_FR_015_units_do_not_nest_on_one_thread(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    with uow.begin(OWNER):
        with pytest.raises(UnitOfWorkError, match="already open"):
            with uow.begin(OWNER):
                pass  # pragma: no cover - refused before the body runs
        with pytest.raises(RepositoryError, match="unit of work"):
            with repo.command_lock(OWNER):
                pass  # pragma: no cover - refused before the body runs
        repo.create(make_task("still-fine"))

    assert counts(repo.db_path)["tasks"] == 1
    with uow.begin(OWNER):  # the failed attempts left no lock or state behind
        pass


def test_026_FR_015_a_unit_is_refused_while_the_thread_holds_the_owner_lock(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    with repo.command_lock(OWNER):
        with pytest.raises(UnitOfWorkError, match="already open"):
            with uow.begin(OWNER):
                pass  # pragma: no cover - refused before the body runs


def test_026_FR_006_the_container_wires_the_unit_over_its_own_repositories(
    container: Container,
) -> None:
    with container.task_unit_of_work.begin(OWNER) as unit:
        container.task_repo.create(make_task("wired"))
        unit.schedule(intent("uow:wired"))

    assert container.task_repo.get_for_owner("wired", owner_id=OWNER).id == "wired"
    assert container.job_repository.find_active("uow:wired", scope=OWNER) is not None


def test_026_FR_006_the_unit_never_spans_a_second_database(
    repo: TaskRepository, data_dir: Path
) -> None:
    elsewhere = JobRepository(data_dir / "elsewhere.sqlite3")

    with pytest.raises(ValueError, match="same SQLite"):
        TaskUnitOfWork(repo, elsewhere)


def test_026_FR_006_a_unit_that_has_ended_accepts_no_more_work(
    repo: TaskRepository, uow: TaskUnitOfWork
) -> None:
    with uow.begin(OWNER) as unit:
        pass

    with pytest.raises(UnitOfWorkError, match="ended"):
        unit.schedule(intent())
    with pytest.raises(UnitOfWorkError, match="ended"):
        unit.load(tasks=("t1",))
    with pytest.raises(UnitOfWorkError, match="ended"):
        unit.after_commit(lambda: None)


# --- job authority is checked inside the unit's lock ----------------------------


class Authority:
    def __init__(self, *owners: str) -> None:
        self.live = set(owners)

    def __call__(self, owner_id: str) -> bool:
        return owner_id in self.live


@pytest.fixture()
def gate(jobs: JobRepository) -> Iterator[JobExecutionGate]:
    yield JobExecutionGate(jobs, owner_current=Authority(OWNER), now=lambda: T0)


def claim(jobs: JobRepository) -> JobLease:
    jobs.ensure_scheduled(job_type=JOB_TYPE, dedup_key="uow:claim", run_at=T0)
    lease = jobs.claim_due(
        owner="w1", types=(JOB_TYPE,), now=T0, lease_for=timedelta(seconds=60)
    )
    assert lease is not None
    return lease


def test_026_SC_007_a_stale_executor_cannot_open_a_unit_or_leave_an_intent(
    repo: TaskRepository,
    uow: TaskUnitOfWork,
    jobs: JobRepository,
    gate: JobExecutionGate,
) -> None:
    lease = claim(jobs)
    jobs.cancel(lease.job_id)
    before = counts(repo.db_path)

    with gate.executing(lease), pytest.raises(StaleExecutorError):
        with uow.begin(OWNER) as unit:
            write_aggregate(unit, repo)  # pragma: no cover

    assert counts(repo.db_path) == before


def test_026_SC_007_a_revoked_scope_cannot_open_a_unit(
    repo: TaskRepository,
    uow: TaskUnitOfWork,
    jobs: JobRepository,
    gate: JobExecutionGate,
) -> None:
    lease = claim(jobs)
    before = counts(repo.db_path)

    with gate.executing(lease), pytest.raises(ScopeRevokedError), uow.begin(OTHER):
        repo.create(make_task("nope", owner=OTHER))  # pragma: no cover

    assert counts(repo.db_path) == before


def test_026_SC_007_a_current_executor_commits_inside_the_unit(
    repo: TaskRepository,
    uow: TaskUnitOfWork,
    jobs: JobRepository,
    gate: JobExecutionGate,
) -> None:
    lease = claim(jobs)

    with gate.executing(lease), uow.begin(OWNER) as unit:
        repo.create(make_task("by-job"))
        unit.schedule(intent("uow:follow-up"))

    assert [task.id for task in repo.list_for_owner(owner_id=OWNER)] == ["by-job"]
    assert jobs.find_active("uow:follow-up", scope=OWNER) is not None


def test_026_SC_007_cleanup_units_need_only_an_existing_owner(
    repo: TaskRepository, jobs: JobRepository
) -> None:
    gate = JobExecutionGate(
        jobs,
        owner_current=lambda _owner: False,
        owner_exists=lambda _owner: True,
        now=lambda: T0,
    )
    uow = TaskUnitOfWork(repo, jobs)
    lease = claim(jobs)

    with gate.executing(lease):
        with pytest.raises(ScopeRevokedError), uow.begin(OWNER):
            pass  # pragma: no cover
        with uow.begin(OWNER, cleanup=True) as unit:
            assert unit.owner_id == OWNER
